"""The wiki: a folder of markdown files, the "markdown loading profile" (§10.2).

Metadata travels as YAML front matter. `path` is where the file sits (§3.2,
kept separate from `identifier`). Links come in both carriers of §5.3:
standard Markdown links inside the body and typed `links:` entries in the front
matter. Legacy wikilinks are also accepted. Inline links are exported as edges marked
`x_carrier: inline`, and never written back into the front matter.

A file with no identifier uses its relative path. No creation time or
author is invented for it.
"""
from __future__ import annotations

import copy
import functools
import os
import posixpath
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

from ...system import System
from ... import embedding
from ...paths import default_wiki_path, inside, wiki_path

WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
MARKDOWN_LINK = re.compile(r'(?<!!)\[([^\]\n]+)\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+"[^"\n]*")?\s*\)')
H1 = re.compile(r"^#\s+(.+?)\s*$", re.M)
FENCE = re.compile(r"^```[^\n]*\n(.*)\n```\s*$", re.S)


class _Loader(yaml.SafeLoader):
    """YAML without the implicit timestamp type, so dates stay strings."""


_Loader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:timestamp"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


@functools.lru_cache(maxsize=1024)
def _parse_front_matter(raw: str):
    """YAML parsing dominated the sync's CPU (every file, several times a pass); unchanged headers parse once."""
    try:
        return yaml.load(raw, Loader=_Loader) or {}
    except yaml.YAMLError:
        return {}


def split_front_matter(text: str) -> tuple[dict, str]:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            raw = text[4:end]
            rest = text[end + 4:]
            if rest.startswith("\n"):
                rest = rest[1:]  # end of the closing --- line
            if rest.startswith("\n"):
                rest = rest[1:]  # the blank line join_front_matter adds
            meta = _parse_front_matter(raw)
            if isinstance(meta, dict):
                return copy.deepcopy(meta), rest
    return {}, text


def join_front_matter(meta: dict, body: str) -> str:
    if not meta:
        return body
    fm = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=1000)
    return f"---\n{fm}---\n\n{body}"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "page"


class WikiSystem(System):
    name = "wiki"
    MARKDOWN = "text/markdown"

    # ---- reading --------------------------------------------------------
    def files(self) -> list[Path]:
        out = []
        for p in sorted(self.root.rglob("*.md")):
            rel = p.relative_to(self.root)
            if any(part.startswith(".") for part in rel.parts) or p.name.endswith("~"):
                continue
            out.append(p)
        return out

    def _read(self, p: Path) -> tuple[dict, str, str]:
        text = p.read_text(encoding="utf-8")
        meta, body = split_front_matter(text)
        return meta, body, str(p.relative_to(self.root)).replace(os.sep, "/")

    def pages(self) -> list[dict]:
        """What the wiki UI shows: the file as it is, plus resolved links."""
        out = []
        for p in self.files():
            meta, body, rel = self._read(p)
            out.append({"path": rel, "meta": meta, "body": body,
                        "title": meta.get("title") or self._title(body, rel)})
        return out

    @staticmethod
    def _title(body: str, rel: str) -> str:
        m = H1.search(body)
        return m.group(1) if m else Path(rel).stem

    def normalize(self) -> None:
        for p in self.files():
            meta, body, rel = self._read(p)
            changed = False
            if not meta.get("identifier"):
                meta = {"identifier": rel, **meta}
                changed = True
            if changed:
                p.write_text(join_front_matter(meta, body), encoding="utf-8")

    def _index(self) -> dict[str, str]:
        """title/path/stem (lowercased) -> identifier, for resolving [[wikilinks]]."""
        idx = {}
        for p in self.files():
            meta, body, rel = self._read(p)
            ident = meta.get("identifier")
            if not ident:
                continue
            for key in (meta.get("title"), self._title(body, rel), rel, Path(rel).stem, rel[:-3]):
                if key:
                    idx.setdefault(key.lower(), ident)
        return idx

    def export(self) -> list[dict]:
        out = []
        idx = self._index()
        for p in self.files():
            meta, body, rel = self._read(p)
            if not meta.get("identifier"):
                continue  # normalize() will assign the relative path on the next tick
            record = dict(meta)
            record.setdefault("attributes", {})
            record["path"] = rel
            record.setdefault("media_type", self.MARKDOWN)
            record.setdefault("title", self._title(body, rel))
            if record["media_type"] != self.MARKDOWN:
                m = FENCE.match(body.strip())
                body = m.group(1) if m else body
            else:
                body = body.rstrip("\n")
            record["body"] = body
            links = self.links_for(body, rel, meta.get("links"), idx=idx)
            if links:
                record["links"] = links
            else:
                record.pop("links", None)
            out.append(record)
        return out

    def links_for(self, body: str, rel: str, explicit: list[dict] | None = None, *, idx: dict | None = None) -> list[dict]:
        if idx is None:
            idx = self._index()
        links = [dict(l) for l in (explicit or []) if isinstance(l, dict)]
        # Code examples and images are not outgoing memory links.
        link_text = re.sub(r"```[^\n]*\n[\s\S]*?```|~~~[^\n]*\n[\s\S]*?~~~|`[^`\n]*`", "", body)
        for m in MARKDOWN_LINK.finditer(link_text):
            href = m.group(2).strip("<>")
            url = urlsplit(href)
            if url.scheme and url.scheme not in ("http", "https", "mailto"):
                continue
            if url.scheme or url.netloc:
                target = href
            else:
                path = (posixpath.normpath(unquote(url.path).lstrip("/")) if url.path.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(rel), unquote(url.path)))) if url.path else rel
                target = idx.get(path.lower(), path)
            link = {"target": target, "x_carrier": "inline"}
            if link not in links:
                links.append(link)
        # Existing notes with legacy wikilinks continue to round-trip.
        for m in WIKILINK.finditer(link_text):
            text = m.group(1).strip()
            target = idx.get(text.lower())
            link = {"target": target or f"title:{text}", "rel": "relates_to", "x_carrier": "inline"}
            if not target:
                link["dangling"] = True
            if link not in links:
                links.append(link)
        return links

    # ---- writing --------------------------------------------------------
    def _path_for(self, record: dict) -> Path:
        return inside(self.root, default_wiki_path(record))

    def _find(self, identifier: str) -> Path | None:
        for p in self.files():
            meta, _, _ = self._read(p)
            if meta.get("identifier") == identifier:
                return p
        return None

    def import_(self, record: dict) -> None:
        target = self._path_for(record)
        existing = self._find(record["identifier"])
        if existing is not None and existing != target:
            target.parent.mkdir(parents=True, exist_ok=True)
            existing.replace(target)
        # The embedding vector is for search; it never goes into a markdown file.
        meta = {k: v for k, v in embedding.without(record).items() if k not in ("body", "path", "checksum")}
        links = [{k: v for k, v in l.items() if k != "x_carrier"}
                 for l in record.get("links") or []
                 if not (isinstance(l, dict) and l.get("x_carrier") == "inline")]
        if links:
            meta["links"] = links
        else:
            meta.pop("links", None)
        body = record["body"]
        if record.get("media_type", self.MARKDOWN) != self.MARKDOWN:
            lang = {"application/json": "json", "text/csv": "csv"}.get(record["media_type"], "")
            body = f"```{lang}\n{body}\n```"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(join_front_matter(meta, body.rstrip("\n") + "\n"), encoding="utf-8")

    def forget(self, identifier: str) -> None:
        p = self._find(identifier)
        if p is not None:
            p.unlink()

    def reset(self) -> None:
        for p in self.files():
            p.unlink()

    # ---- UI writes (the wiki's own editor) --------------------------------
    def write_page(self, rel: str, body: str, title: str | None = None, tags: list[str] | None = None) -> None:
        p = inside(self.root, wiki_path(rel))
        meta = {}
        if p.exists():
            meta, _, _ = self._read(p)
        if title:
            meta["title"] = title
        if tags is not None:
            meta["tags"] = [t for t in tags if t]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(join_front_matter(meta, body.rstrip("\n") + "\n"), encoding="utf-8")

    def delete_page(self, rel: str) -> None:
        p = inside(self.root, wiki_path(rel))
        if p.exists():
            p.unlink()
