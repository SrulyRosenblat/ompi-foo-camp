"""The search index: SQLite FTS5 over titles and bodies, plus embeddings.

The same shape as `prototypes/acp_memory_server`'s index. Each row keeps the
full interchange record; a body edited in the search console is written back
into that record, so export is the record with the new body.

With an embedder started, a background worker embeds each memory and writes
the vector into the record's `attributes.embedding` (see `omp_live.embedding`).
That changes this system's export, so the sync publishes the vector as a
revision contributed by search. Queries then rank by keywords and by meaning.
"""
from __future__ import annotations

import html
import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from ...model import checksum, title_of, version_value
from ...system import System
from ...paths import default_wiki_path
from ...lifecycle import current_records
from ... import revisions
from ... import embedding

log = logging.getLogger("omp-sync")

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
  identifier TEXT PRIMARY KEY, path TEXT, title TEXT, body TEXT, tags TEXT,
  authors TEXT, record TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
  identifier UNINDEXED, title, body, tags, tokenize='porter unicode61'
);
CREATE TABLE IF NOT EXISTS embeddings (
  model TEXT, text_checksum TEXT, vector TEXT NOT NULL, PRIMARY KEY (model, text_checksum)
);
"""


class SearchSystem(System):
    name = "search"

    def __init__(self, root: Path):
        super().__init__(root)
        self.db_path = self.root / "index.db"
        with self._db() as db:
            db.execute("PRAGMA journal_mode=DELETE")
            db.executescript(SCHEMA)
            db.executescript(revisions.SCHEMA)
        self.embedder = None
        self.embed_status = "off"
        self._query_vectors: dict[str, list[float]] = {}

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def import_(self, record: dict) -> None:
        record = {**record, "path": default_wiki_path(record)}
        model = self.embedder.model if self.embedder else None
        if embedding.carried(record):
            if embedding.valid(record, model):
                emb = embedding.carried(record)
                with self._db() as db:
                    db.execute("INSERT OR IGNORE INTO embeddings VALUES(?,?,?)",
                               (emb["model"], emb["text_checksum"], json.dumps(emb["vector"])))
            elif model:
                record = embedding.without(record)  # stale or another model's; the worker re-embeds
        ident = record["identifier"]
        authors = ",".join(sorted({str(p.get("kind")) for p in record.get("provenance") or [] if isinstance(p, dict)}))
        tags = " ".join(record.get("tags") or [])
        with self._db() as db:
            db.execute("DELETE FROM docs WHERE identifier=?", (ident,))
            db.execute("DELETE FROM docs_fts WHERE identifier=?", (ident,))
            db.execute("INSERT INTO docs VALUES(?,?,?,?,?,?,?)",
                       (ident, record.get("path"), title_of(record), record["body"], tags, authors,
                        json.dumps(record, ensure_ascii=False)))
            db.execute("INSERT INTO docs_fts(identifier, title, body, tags) VALUES(?,?,?,?)",
                       (ident, title_of(record), record["body"], tags))

    def export(self) -> list[dict]:
        with self._db() as db:
            return [json.loads(r["record"]) for r in db.execute("SELECT record FROM docs ORDER BY identifier")]

    def remember_revisions(self, records):
        with self._db() as db:
            revisions.remember(db, records)

    def history(self, identifier=None):
        with self._db() as db:
            return revisions.history(db, identifier)

    def forget(self, identifier: str) -> None:
        with self._db() as db:
            db.execute("DELETE FROM docs WHERE identifier=?", (identifier,))
            db.execute("DELETE FROM docs_fts WHERE identifier=?", (identifier,))
            revisions.forget(db, identifier)

    def reset(self) -> None:
        with self._db() as db:
            db.execute("DELETE FROM docs")
            db.execute("DELETE FROM docs_fts")
            revisions.reset(db)

    # ---- embeddings ----------------------------------------------------------
    def start_embedding(self, embedder) -> None:
        """Embed every memory in the background and keep the vectors current."""
        self.embedder = embedder
        self.embed_status = "starting"
        self._wake = threading.Event()
        threading.Thread(target=self._embed_loop, name="search-embed", daemon=True).start()

    def _embed_loop(self) -> None:
        backoff = 5
        while True:
            try:
                n = self.embed_pending()
                backoff = 5
                time.sleep(0.2 if n else 1)
            except Exception as e:  # keep keyword search working; try again later
                self.embed_status = f"error: {e}"
                log.warning("embedding with %s failed: %s", self.embedder.model, e)
                self._wake.wait(backoff)  # a search wakes it early, so a fixed account setting shows up at once
                self._wake.clear()
                backoff = min(backoff * 2, 60)

    def embed_pending(self, batch: int = 16) -> int:
        """Attach vectors to records that lack a current one. Returns how many changed."""
        model = self.embedder.model
        with self._db() as db:
            records = [json.loads(r["record"]) for r in db.execute("SELECT record FROM docs")]
            pending = [r for r in records if not embedding.valid(r, model)]
            if not pending:
                self.embed_status = f"{model}: {len(records)} embedded"
                return 0
            cached = {r["text_checksum"]: json.loads(r["vector"]) for r in db.execute(
                "SELECT text_checksum, vector FROM embeddings WHERE model=?", (model,))}
        todo = {embedding.text_checksum(r): embedding.embed_text(r) for r in pending
                if embedding.text_checksum(r) not in cached}
        todo = dict(list(todo.items())[:batch])
        if todo:
            self.embed_status = f"{model}: embedding {len(todo)}"
            for key, vec in zip(todo, self.embedder.embed(list(todo.values()))):
                cached[key] = vec
                with self._db() as db:
                    db.execute("INSERT OR REPLACE INTO embeddings VALUES(?,?,?)", (model, key, json.dumps(vec)))
        changed = 0
        for r in pending:
            key = embedding.text_checksum(r)
            if key not in cached:
                continue
            with self._db() as db:  # write only if the text is still what we embedded
                row = db.execute("SELECT record FROM docs WHERE identifier=?", (r["identifier"],)).fetchone()
                if row is None:
                    continue
                current = json.loads(row["record"])
                if embedding.text_checksum(current) != key or embedding.valid(current, model):
                    continue
                db.execute("UPDATE docs SET record=? WHERE identifier=?",
                           (json.dumps(embedding.attach(current, model, cached[key]), ensure_ascii=False), r["identifier"]))
                changed += 1
        return changed

    def _semantic(self, q: str, visible: set[str]) -> list[tuple[str, float]]:
        if not self.embedder:
            return []
        try:
            qv = self._query_vectors.get(q) or self.embedder.embed([q], timeout=8)[0]
        except Exception as e:
            log.warning("query embedding failed: %s", e)
            return []
        self._query_vectors[q] = qv
        del_keys = list(self._query_vectors)[:-200]
        for k in del_keys:
            self._query_vectors.pop(k, None)
        scored = []
        for rec in self.export():
            emb = embedding.carried(rec)
            if rec["identifier"] in visible and emb and emb.get("model") == self.embedder.model:
                scored.append((rec["identifier"], embedding.cosine(qv, emb["vector"])))
        scored.sort(key=lambda x: -x[1])
        if not scored:
            return []
        best = scored[0][1]  # keep the clear front-runners, not the whole collection
        return [(i, c) for i, c in scored[:6] if c >= best - 0.08]

    # ---- the search console's own operations -------------------------------
    def docs(self, include_history=False) -> list[dict]:
        records = self.history() if include_history else current_records(self.export())
        out = []
        for rec in sorted(records, key=lambda r: (r.get('path', ''), title_of(r))):
            out.append({"identifier": rec['identifier'], "path": rec.get('path'), "title": title_of(rec),
                        "body": rec['body'], "tags": rec.get('tags') or [],
                        "authors": sorted({str(p.get('kind')) for p in rec.get('provenance') or [] if isinstance(p, dict)}),
                        "valid_until": rec.get('valid_until'), "media_type": rec.get('media_type'),
                        "conflicts": len(rec.get('x_conflicts') or []),
                        "dangling": sum(1 for link in rec.get('links') or [] if isinstance(link, dict) and link.get('dangling')),
                        "version": version_value(rec)})
        return out

    def search(self, q: str, limit: int = 50, include_history: bool = False) -> list[dict]:
        q = q.strip()
        if include_history:
            return [{'identifier': hit['memory']['identifier'], 'version': version_value(hit['memory']),
                     'memory': hit['memory'], **({'score': hit['score']} if 'score' in hit else {})}
                    for hit in self.search_history(q, limit)]
        if not q:
            return []
        # quote each term so punctuation in queries doesn't break FTS syntax
        terms = " ".join('"' + t.replace('"', '""') + '"' for t in q.split())
        with self._db() as db:
            rows = db.execute(
                "SELECT identifier, snippet(docs_fts, 2, '<mark>', '</mark>', '…', 18) AS snip, bm25(docs_fts) AS score "
                "FROM docs_fts WHERE docs_fts MATCH ? ORDER BY score", (terms,)).fetchall()
        current = {r['identifier']: r for r in current_records(self.export())}
        keyword = [r for r in rows if r['identifier'] in current]
        if getattr(self, "_wake", None) and self.embed_status.startswith("error"):
            self._wake.set()
        meaning = self._semantic(q, set(current))
        # Reciprocal rank fusion: a memory found both ways ranks above one found either way.
        fused: dict[str, float] = {}
        for rank, r in enumerate(keyword):
            fused[r['identifier']] = fused.get(r['identifier'], 0) + 1 / (60 + rank)
        for rank, (ident, _) in enumerate(meaning):
            fused[ident] = fused.get(ident, 0) + 1 / (60 + rank)
        snips = {r['identifier']: r['snip'] for r in keyword}
        cos = dict(meaning)
        hits = []
        for ident in sorted(fused, key=lambda i: -fused[i])[:limit]:
            match = "both" if ident in snips and ident in cos else "keyword" if ident in snips else "meaning"
            snip = snips.get(ident) or "≈ " + html.escape(" ".join(current[ident]["body"].split())[:140]) + "…"
            hits.append({"identifier": ident, "snippet": snip, "score": fused[ident], "match": match,
                         **({"similarity": round(cos[ident], 3)} if ident in cos else {})})
        return hits

    def search_history(self, q: str, limit: int = 100000) -> list[dict]:
        records = self.history()
        if not q.strip():
            return [{'memory': r} for r in records][:limit]
        terms = ' '.join('"' + t.replace('"', '""') + '"' for t in q.split())
        with self._db() as db:
            hits = db.execute("SELECT key, bm25(memory_revision_fts) AS score FROM memory_revision_fts "
                              "WHERE memory_revision_fts MATCH ? ORDER BY score", (terms,)).fetchall()
        ranked = {r['key']: r['score'] for r in hits}
        return sorted([{'memory': r, 'score': ranked[checksum(r)]} for r in records if checksum(r) in ranked],
                      key=lambda item: item['score'])[:limit]

    def write_doc(self, identifier: str, body: str | None = None, title: str | None = None, tags: list[str] | None = None) -> bool:
        with self._db() as db:
            row = db.execute("SELECT record FROM docs WHERE identifier=?", (identifier,)).fetchone()
            if row is None:
                return False
            rec = json.loads(row["record"])
        if body is not None:
            rec["body"] = body
        if title is not None:
            rec["title"] = title
        if tags is not None:
            rec["tags"] = [t for t in tags if t]
        self.import_(rec)
        return True

    def write_body(self, identifier: str, body: str) -> bool:
        return self.write_doc(identifier, body=body)
