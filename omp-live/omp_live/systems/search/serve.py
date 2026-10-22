from __future__ import annotations

from pathlib import Path

from ...httpkit import make_server
from .adapter import SearchSystem

HTML = Path(__file__).with_name("ui.html")


def server(system: SearchSystem, port: int, sync=None, service=None):
    def docs(q, b):
        return {"docs": system.docs(include_history=q.get('include_history', '').lower() in ('true', '1')), "silent_identifiers": sync.silent_identifiers() if sync else [], "embedding": system.embed_status}

    def search(q, b):
        return {"hits": system.search(q.get("q", ""), include_history=q.get('include_history', '').lower() in ('true', '1'))}

    def write(q, b):
        if service:
            if b.get('supersession'):
                context = b['supersession']
                record = service.supersede_memory(b['identifier'], b['body'], context.get('reason'),
                                                  context.get('contributor'), title=b.get('title'),
                                                  tags=b.get('tags'), if_version=b.get('if_version'), actor='ui', animate=True)
                return {'ok': True, 'memory': record}
            record = service.update_memory(b["identifier"], b.get("body"), b.get("title"),
                                           tags=b.get("tags"), if_version=b.get('if_version'), actor="ui", animate=True)
            return {"ok": True, "memory": record}
        return {"ok": system.write_doc(b["identifier"], b.get("body"), b.get("title"), b.get("tags"))}

    return make_server(port, HTML, {
        ("GET", "/api/docs"): docs,
        ("GET", "/api/search"): search,
        ("POST", "/api/doc"): write,
    }, name="search")
