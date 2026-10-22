from __future__ import annotations

from pathlib import Path
from contextlib import nullcontext

from ...httpkit import make_server
from .adapter import WikiSystem, slug
from ...model import version_value
from ...paths import inside, wiki_path

HTML = Path(__file__).with_name("ui.html")


def server(system: WikiSystem, port: int, sync=None, service=None):
    def pages(q, b):
        with sync._lock if sync else nullcontext():
            return {"pages": system.pages(),
                    "folders": service.list_folders()["folders"] if service else [],
                    "silent_identifiers": sync.silent_identifiers() if sync else []}

    def write(q, b):
        with sync._lock if sync else nullcontext():
            if sync and b.get('if_version') is not None:
                sync.reconcile()  # detect pending filesystem edits before the precondition check
                page = next((p for p in system.pages() if p['path'] == b['path']), None)
                record = sync.export.get(page['meta']['identifier']) if page else None
                if record is None or version_value(record) != b['if_version']:
                    raise ValueError('This file changed elsewhere. Your draft was not saved; review the latest version.')
            system.write_page(b["path"], b["body"], b.get("title"), b.get("tags"))
            if sync:
                sync.reconcile()
        return {"ok": True}

    def new(q, b):
        rel = b.get("path") or (slug(b["title"]) + ".md")
        with sync._lock if sync else nullcontext():
            if inside(system.root, wiki_path(rel)).exists():
                raise ValueError('A file already exists at this path. Open it or choose another name.')
            system.write_page(rel, b.get("body", ""), b.get("title"))
            if sync:
                sync.reconcile()
        return {"ok": True, "path": rel}

    def delete(q, b):
        with sync._lock if sync else nullcontext():
            system.delete_page(q["path"])
            if sync:
                sync.reconcile()
        return {"ok": True}

    return make_server(port, HTML, {
        ("POST", "/api/move"): lambda q, b: service.move_memory(b["identifier"], b["path"], actor="ui"),
        ("POST", "/api/folder"): lambda q, b: service.create_folder(b["folder"]),
        ("GET", "/api/pages"): pages,
        ("POST", "/api/page"): write,
        ("POST", "/api/new"): new,
        ("DELETE", "/api/page"): delete,
    }, name="wiki")
