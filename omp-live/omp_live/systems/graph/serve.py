from __future__ import annotations

from pathlib import Path

from ...httpkit import make_server
from .adapter import GraphSystem

HTML = Path(__file__).with_name("ui.html")


def server(system: GraphSystem, port: int, sync=None):
    def graph(q, b):
        return {**system.snapshot(include_history=q.get('include_history', '').lower() in ('true', '1')), "silent_identifiers": sync.silent_identifiers() if sync else []}

    def add_edge(q, b):
        if b.get('rel') == 'supersedes' and sync:
            from ...memory_service import MemoryService
            service = MemoryService(sync)
            with sync._lock:
                current = service._get_stored(b['src'])
                links = [l for l in current.get('links', []) if l.get('x_carrier') != 'inline']
                links.append({'target': b['dst'], 'rel': 'supersedes',
                              'reason': b.get('reason'), 'contributor': b.get('contributor')})
                service.update_memory(b['src'], links=links, actor='ui', animate=True)
            return {'ok': True}
        system.add_edge(b["src"], b["dst"], b.get("rel") or "relates_to")
        return {"ok": True}

    def remove_edge(q, b):
        system.remove_edge(int(q["id"]))
        return {"ok": True}

    def update_node(q, b):
        return {"ok": system.update_node(b["id"], b.get("title"), b.get("tags"), b.get("body"))}

    return make_server(port, HTML, {
        ("POST", "/api/node"): update_node,
        ("GET", "/api/graph"): graph,
        ("POST", "/api/edge"): add_edge,
        ("DELETE", "/api/edge"): remove_edge,
    }, name="graph")
