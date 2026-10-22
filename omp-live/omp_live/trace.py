"""Trace one memory through every system: its native form in each, and a
field-by-field account of what each system keeps, drops or restructures.

This is what the projector's "Trace" view shows. Nothing here is used by the
sync; it only reads.
"""
from __future__ import annotations

import json
import sqlite3

from .sync import Sync

# How each system carries each interchange field, in plain words. Anything not
# listed is "carried along, not used" for graph/search and "file header" for the wiki.
KEPT = "carried along, not used"
WIKI = {
    "identifier": "file header", "title": "file header", "tags": "file header", "created_at": "file header",
    "body": "the text of the file", "path": "which folder the file is in", "media_type": "file header",
    "links": "links written in the text", "provenance": "file header",
    "attributes": "file header",
    "evidence": "file header", "checksum": "not saved; worked out again on export", "version": "file header",
    "updated_at": "file header", "valid_until": "file header", "valid_from": "file header", "scope": "file header",
    "x_conflicts": "file header", "stub": "file header",
}
GRAPH = {
    "identifier": "the node's id", "title": "the node's label", "links": "edges: one line per link",
    "provenance": "who-wrote-it nodes, linked to this one", "tags": "carried along, not drawn", "body": "shown when you expand the node",
    "path": "carried along, not used (a graph has no folders)", "valid_until": "fades the node", "x_conflicts": "ring on the node",
}
SEARCH = {
    "identifier": "the row's key", "title": "searchable", "body": "searchable", "tags": "searchable",
    "path": "the folder filter", "provenance": "the written-by filter", "links": "only counts links that go nowhere",
    "valid_until": "fades the row", "x_conflicts": "flagged",
}
EXPORT = {"checksum": "worked out here", "version": "goes up here on each change", "updated_at": "set here", "provenance": "systems add themselves here"}


def trace(sync: Sync, identifier: str) -> dict:
    export = sync.export.get(identifier)
    wiki = sync.systems["wiki"]
    graph = sync.systems["graph"]
    search = sync.systems["search"]

    wiki_file = None
    wiki_path = wiki._find(identifier)
    if wiki_path is not None:
        wiki_file = {"path": str(wiki_path.relative_to(wiki.root)), "text": wiki_path.read_text(encoding="utf-8")}

    graph_view = None
    with graph._db() as db:
        node = db.execute("SELECT id, kind, label FROM nodes WHERE id=?", (identifier,)).fetchone()
        if node:
            edges = [dict(r) for r in db.execute("SELECT id, src, dst, rel, carrier FROM edges WHERE src=? OR dst=? ORDER BY id", (identifier, identifier))]
            graph_view = {"node": dict(node), "edges": edges}

    search_view = None
    with search._db() as db:
        row = db.execute("SELECT identifier, path, title, body, tags, authors FROM docs WHERE identifier=?", (identifier,)).fetchone()
        if row:
            search_view = dict(row)

    fields = [{"field": "embedding", "wiki": "dropped; markdown never holds the vector", "export": "in attributes, from the search index",
               "graph": KEPT, "search": "made here; ranks results by meaning"}]
    keys = list((export or {}).keys())
    for k in keys:
        fields.append({
            "field": k,
            "wiki": WIKI.get(k, "file header"),
            "export": EXPORT.get(k, "copied as is"),
            "graph": GRAPH.get(k, KEPT),
            "search": SEARCH.get(k, KEPT),
        })
    receipts = [r for r in sync.export.receipts(300) if r["identifier"] == identifier][-12:]
    state = {name: {"held": sync.held[name].get(identifier), "base": sync.base[name].get(identifier)} for name in sync.systems}
    # The live event stream (in memory, so empty after a restart) gives the journey's timings.
    events = [{k: v for k, v in e.items() if k != "record"} for e in sync.events if e["identifier"] == identifier][-40:]
    return {"identifier": identifier, "events": events, "wiki": wiki_file, "export": export, "graph": graph_view, "search": search_view,
            "animate": identifier not in sync.silent_identifiers(),
            "fields": fields, "receipts": receipts, "state": state,
            "tombstone": sync.export.is_tombstoned(identifier), "conflicts": sync.export.conflicts(identifier)}
