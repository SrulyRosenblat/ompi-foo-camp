"""The graph store: nodes and typed edges in SQLite.

Memories are nodes. `links` become edges (both carriers from §5.3 arrive the
same way; `x_carrier` is kept on the edge so the UI can draw them
differently). Contributors from `provenance` become person/agent/system nodes
with `provenance:<contribution>` edges. A link to something the store does
not hold becomes a dashed edge to a ghost node (§8.5: dangling references are
kept and marked, never dropped). The full interchange record is kept on the
node so export is lossless; edges added in the graph UI are overlaid as
typed `links`.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from ...model import title_of
from ...system import System
from ...lifecycle import current_records, edge_version
from ... import revisions

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, label TEXT NOT NULL, record TEXT
);
CREATE TABLE IF NOT EXISTS edges (
  id INTEGER PRIMARY KEY AUTOINCREMENT, src TEXT NOT NULL, dst TEXT NOT NULL,
  rel TEXT NOT NULL, carrier TEXT, link TEXT, position INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS edges_src ON edges(src);
"""


class GraphSystem(System):
    name = "graph"

    def __init__(self, root: Path):
        super().__init__(root)
        self.db_path = self.root / "store.db"
        with self._db() as db:
            db.execute("PRAGMA journal_mode=DELETE")
            db.executescript(SCHEMA)
            db.executescript(revisions.SCHEMA)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    # ---- import -----------------------------------------------------------
    def import_(self, record: dict) -> None:
        ident = record["identifier"]
        with self._db() as db:
            db.execute("INSERT INTO nodes(id, kind, label, record) VALUES(?,?,?,?) "
                       "ON CONFLICT(id) DO UPDATE SET kind='memory', label=excluded.label, record=excluded.record",
                       (ident, "memory", title_of(record), json.dumps(record, ensure_ascii=False)))
            db.execute("DELETE FROM edges WHERE src=?", (ident,))
            for pos, link in enumerate(record.get("links") or []):
                if not isinstance(link, dict) or "target" not in link:
                    continue
                target = str(link["target"])
                self._ensure_node(db, target, "ghost", target)
                db.execute("INSERT INTO edges(src, dst, rel, carrier, link, position) VALUES(?,?,?,?,?,?)",
                           (ident, target, link.get("rel", "relates_to"), link.get("x_carrier", "typed"),
                            json.dumps(link, ensure_ascii=False), pos))
            for entry in record.get("provenance") or []:
                if not isinstance(entry, dict) or "id" not in entry:
                    continue
                cid = str(entry["id"])
                self._ensure_node(db, cid, entry.get("kind", "system"), entry.get("name") or cid, force_kind=True)
                db.execute("INSERT INTO edges(src, dst, rel, carrier, link, position) VALUES(?,?,?,?,NULL,0)",
                           (ident, cid, "provenance:" + str(entry.get("contribution", "contributed")), "provenance"))

    @staticmethod
    def _ensure_node(db, node_id: str, kind: str, label: str, force_kind: bool = False) -> None:
        row = db.execute("SELECT kind FROM nodes WHERE id=?", (node_id,)).fetchone()
        if row is None:
            db.execute("INSERT INTO nodes(id, kind, label, record) VALUES(?,?,?,NULL)", (node_id, kind, label))
        elif force_kind and row["kind"] == "ghost":
            db.execute("UPDATE nodes SET kind=?, label=? WHERE id=?", (kind, label, node_id))

    # ---- export -----------------------------------------------------------
    def export(self) -> list[dict]:
        out = []
        with self._db() as db:
            for row in db.execute("SELECT id, record FROM nodes WHERE kind='memory' AND record IS NOT NULL ORDER BY id"):
                record = json.loads(row["record"])
                links = [json.loads(e["link"]) for e in db.execute(
                    "SELECT link FROM edges WHERE src=? AND link IS NOT NULL ORDER BY position, id", (row["id"],))]
                if links:
                    record["links"] = links
                else:
                    record.pop("links", None)
                out.append(record)
        return out

    def remember_revisions(self, records):
        with self._db() as db:
            revisions.remember(db, records)

    def history(self, identifier=None):
        with self._db() as db:
            return revisions.history(db, identifier)

    def forget(self, identifier: str) -> None:
        with self._db() as db:
            revisions.forget(db, identifier)
            db.execute("DELETE FROM edges WHERE src=?", (identifier,))
            referenced = db.execute("SELECT 1 FROM edges WHERE dst=? LIMIT 1", (identifier,)).fetchone()
            if referenced:  # others still point here: keep a marked, content-free ghost (§8.5)
                db.execute("UPDATE nodes SET kind='ghost', record=NULL WHERE id=?", (identifier,))
            else:
                db.execute("DELETE FROM nodes WHERE id=?", (identifier,))
            self._sweep(db)

    @staticmethod
    def _sweep(db) -> None:
        db.execute("DELETE FROM nodes WHERE kind!='memory' AND id NOT IN (SELECT dst FROM edges)")

    def reset(self) -> None:
        with self._db() as db:
            revisions.reset(db)
            db.execute("DELETE FROM edges")
            db.execute("DELETE FROM nodes")

    # ---- the graph UI's own operations -------------------------------------
    def snapshot(self, include_history=False) -> dict:
        visible = {r['identifier'] for r in current_records(self.export())}
        with self._db() as db:
            nodes = []
            for r in db.execute("SELECT id, kind, label, record FROM nodes ORDER BY id"):
                rec = json.loads(r["record"]) if r["record"] else None
                nodes.append({"id": r["id"], "kind": r["kind"], "label": r["label"],
                              "tags": (rec or {}).get("tags", []),
                              "valid_until": (rec or {}).get("valid_until"),
                              "conflicts": len((rec or {}).get("x_conflicts") or []),
                              "version": ((rec or {}).get("version") or {}).get("value") if isinstance((rec or {}).get("version"), dict) else (rec or {}).get("version"),
                              "revision_links": [l for l in (rec or {}).get('links', []) if isinstance(l, dict) and l.get('rel') == 'supersedes'],
                              "body": (rec or {}).get("body", "")})
            edges = []
            for row in db.execute("SELECT id, src, dst, rel, carrier, link FROM edges ORDER BY id"):
                edge = dict(row)
                link = json.loads(edge.pop('link')) if row['link'] else {}
                edge.update({k: v for k, v in link.items() if k not in ('target', 'rel', 'x_carrier')})
                # A prior revision is not a self-edge to the current graph node.
                if edge['rel'] == 'supersedes' and edge_version(link) is not None:
                    continue
                edges.append(edge)
        if not include_history:
            allowed = {n['id'] for n in nodes if n['kind'] != 'memory' or n['id'] in visible}
            edges = [e for e in edges if e['src'] in allowed and e['dst'] in allowed]
            mentioned = {e[k] for e in edges for k in ('src', 'dst')}
            nodes = [n for n in nodes if n['id'] in visible or (n['kind'] != 'memory' and n['id'] in mentioned)]
        result = {"nodes": nodes, "edges": edges}
        if include_history:
            history = self.history()
            result['revisions'] = history
            result['revision_edges'] = [dict(source={'identifier': r['identifier'], 'version': revisions.version_value(r)}, **link)
                                        for r in history for link in r.get('links', []) if isinstance(link, dict) and link.get('rel') == 'supersedes']
        return result

    def add_edge(self, src: str, dst: str, rel: str) -> None:
        with self._db() as db:
            self._ensure_node(db, dst, "ghost", dst)
            pos = db.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM edges WHERE src=?", (src,)).fetchone()[0]
            db.execute("INSERT INTO edges(src, dst, rel, carrier, link, position) VALUES(?,?,?,?,?,?)",
                       (src, dst, rel, "typed", json.dumps({"target": dst, "rel": rel}), pos))

    def update_node(self, node_id: str, title: str | None = None, tags: list[str] | None = None, body: str | None = None) -> bool:
        """Edit a memory in place; the graph keeps the full record, so this is a record edit."""
        with self._db() as db:
            row = db.execute("SELECT record FROM nodes WHERE id=? AND kind='memory'", (node_id,)).fetchone()
            if row is None:
                return False
            rec = json.loads(row["record"])
        if title is not None:
            rec["title"] = title
        if tags is not None:
            rec["tags"] = [t for t in tags if t]
        if body is not None:
            rec["body"] = body
        self.import_(rec)
        return True

    def remove_edge(self, edge_id: int) -> None:
        with self._db() as db:
            db.execute("DELETE FROM edges WHERE id=? AND link IS NOT NULL", (edge_id,))
            self._sweep(db)
