# omp-live

One memory, three systems and an agent, synced in real time. No hub, no
hooks: a folder of OMP interchange files is the bus, and one script with a
file watcher moves changes through it.

```
wiki/        Markdown files, standard links, optional front matter
graph/       nodes and typed edges in SQLite
search/      an FTS5 index
omp-export/  manifest.json · memories/ · tombstones/ · conflicts/ · receipts/
```

The agent (`omp_live/agent/`) is an ordinary coding-agent harness, not a
fourth store: its working directory is the wiki folder and its tools are
`ls`, `read`, `write`, `edit` and `bash`. Each turn it gets `MEMORY.md` in
full and an index of the other files, which it reads on demand (the markdown
loading contract, §10.2). It remembers by writing a markdown file with
provenance front matter; a new file's path is its identifier. Unknown
creation dates are omitted. It forgets with
`rm`; the sync tombstones. It uses OpenRouter; `OPENROUTER_API_KEY` is read
from the environment, `omp-live/.env` or `../.env` (either case), and
`OMP_AGENT_MODEL` picks the model (default `deepseek/deepseek-v4.1-flash`).

Each system implements one `import(record)` and one `export() -> records`
(`omp_live/system.py`). `omp-sync` (`omp_live/sync.py`) watches all four
folders: a change in a system goes into `omp-export/` as a new revision; a
new revision in `omp-export/` goes into every other system. Conflicts are
parked, forgets leave tombstones, every outcome is a receipt (spec §6.5,
§8.4). The plan and the rationale are in `../PROTOTYPE-PLAN.md`.

## Run

```sh
cd omp-live
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
omp-sync seed fictional-memories.json    # invented Cloudberry Observatory notes
omp-sync demo                             # opens http://127.0.0.1:8700
```

The included Cloudberry Observatory fixture contains 23 entirely fictional memories (including 7 personal notes about an invented observer, Juniper Hale)
and one retained earlier revision. All people, places, equipment, and operating
rules are invented. Records have `attributes.fictional: true`; no creation dates
are fabricated. Seeding adds records to a folder, so use a clean folder when
starting a new demo.

The dashboard keeps the agent on the right and shows one system at a
time on the left: Wiki, Graph, Search or Trace (keys 1–4, F for full
screen), with the receipt log underneath. Each new or edited memory starts
an automatic journey: wiki → OMP → graph → search. The conversion shows the
original body beside the record, filling `identifier`, `media_type`, `body`,
`attributes`, then each explicit `links` target. No presentation clicks are
needed. Changes queue in order and each event keeps its own record snapshot.
The live panes follow the same identifier. Forgetting a memory cancels its
queued or active conversion and clears the displayed content.
Each system is also its own page: wiki
8701, graph 8702, search 8703, agent 8704, trace `8700/trace`. Edit
`demo/wiki/*.md` in any editor and watch the others follow. Every system
edits title, tags and body in its own UI; the graph also draws edges.

Trace shows one memory through every system: the markdown file, the OMP
record, the graph's node and edges, the search row, side by side and live,
with a table of what each system keeps, drops or restructures per field.

```sh
omp-sync status                 # what each system holds
omp-sync receipts               # the last receipts
omp-sync forget <identifier>    # tombstone a memory everywhere
omp-sync rebuild graph          # wipe a system and restore it from omp-export/
omp-sync resolve <identifier> --keep wiki|graph|search|export
omp-sync --root /some/dir demo  # a different demo folder
```

`demo/script.md` is the run of show. The tests:

```sh
python3 tests/test_core.py          # the sync loop, headless
python3 tests/test_agent.py         # the agent's tools with a scripted model
python3 tests/test_conversion.py    # minimal records, Markdown links, event snapshots
python3 tests/test_live.py <legacy-test-root>  # uses the nine-record sample, not the live fictional demo
```

## How the sync decides

For each system S and memory id, the sync keeps two checksums: `held`, S's
own rendition (change detection and echo suppression), and `base`, the
export record S last synced with (conflict detection). S re-exporting what
it just imported is a no-op. S changing a record whose export has moved on
since S last saw it is a conflict: the revision is parked in `conflicts/`,
every copy gets an `x_conflicts` marker, and a person picks a winner. A
forgotten identifier never comes back; a system that re-presents one gets a
`rejected` receipt.

The minimal record has `identifier`, `media_type`, `body` and `attributes`.
Standard Markdown links such as `[Vegan](vegan.md)` stay in the body and
are exported into an explicit `links` list. Local paths resolve relative to
the source file and use an existing target identifier where available.
Legacy wikilinks and existing identifiers still round-trip. Additional
stored metadata is available in the record's expandable section.

## MCP access for other agents

`omp-sync demo` also starts a local Streamable HTTP MCP server at
**http://127.0.0.1:8705/mcp**. The project-level `.mcp.json` points to it.
The dashboard's **MCP** button shows the address for the running instance.
Use these tools:

- `about_omp(topic=None)`: what OMP and OMPI are, the record format, lifecycle, open issues, and links to the [Open Memory Protocol repository](https://github.com/The-AI-Disclosures-Project/Open-Memory-Protocol). Also served as the `omp://about` resource.
- `search_memories(query, limit=20, path_prefix=None)`: full-text search; an empty query lists items.
- `get_memory(identifier)`: the complete current OMP record for an indexed item.
- `supersede_memory(identifier, body, reason, contributor, title=None, if_version=None)`: explicitly replace a revision while retaining history.
- `add_memory(body, title=None, identifier=None, path=None, attributes=None, tags=None, links=None, valid_until=None, contributor=None)`.
- `update_memory(identifier, body=None, title=None, attributes=None, tags=None, links=None, if_version=None, valid_until=None, contributor=None)`: attributes merge (null removes a key).
- `move_memory(identifier, path, contributor=None)`: change its wiki location without changing identity.
- `list_folders()`: existing folders; `""` means the wiki root.

Pass `contributor` (e.g. `"agent:claude-code"`) on writes so provenance records who made the change; unknown arguments are rejected. Results describe each record's search embedding (model, dimensions) but omit the vector.

MCP writes originate in the **search index**, then go through the same OMP
export, wiki import and graph import as UI changes. They do not run the
conversion presentation, flash wiki/search content, or pulse graph nodes.
Normal human edits continue to animate. Presentation flags are event metadata,
not fields added to memory records.

A new item without a path is assigned a unique file under `uncategorized/`.
An explicit link is an object with `target` and optionally `rel`, for example:

```json
{
  "body": "Prefer the existing Postgres decision.",
  "title": "Database preference",
  "links": [{"target": "0d6e4f88-ledger-decision", "rel": "derived_from"}]
}
```

Targets use stable memory identifiers; supplying an existing wiki path also
resolves to that memory's identifier. Unknown targets are preserved as references.
Markdown links in the body are inferred independently. On update, omitted
`links` preserves explicit links and `links: []` removes them. `if_version`
rejects a stale update rather than overwriting a newer revision.

For clients that require **stdio**, start the bridge:

```sh
omp-sync mcp --site http://127.0.0.1:8700
```

`mcp.stdio.example.json` contains a configuration for this checkout. The bridge
uses the running site's API; it does not start a second sync process or access
its databases independently. The MCP implementation uses the official
[Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk/tree/v1.30.0).

## Reorganizing the wiki

Drag a note in the wiki sidebar onto a folder header. Use **New folder** to add
a destination, or the note's **Folder** selector and **Move** button for keyboard
and touch use. The move updates the wiki file, OMP path, search folder facet and
graph record together. The identifier and typed links stay stable; incoming and
outgoing Markdown URLs are rebased so the links keep working. Existing files
are never overwritten. Folder moves are quiet organizational changes.

Additional checks:

```sh
python3 tests/test_memory_service.py
python3 tests/test_mcp.py
python3 tests/test_watcher.py
```

The graph starts with one memory and its direct connections, using the demo's
small nodes and cyan links. Choose a memory to focus it, or use **All memories**
to browse the full graph. Click a node (or press Enter/Space) to expand its body and reveal further
connections; click again to collapse it. **Details** opens the editor. The
**All memories** overview displays filled node markers and fits them in the
available pane when space permits; expanded cards can scroll. Shift-drag
between nodes to add a typed link. MCP changes refresh this view quietly.

## Supersession and historical reads

OMP JSON, search and graph retain revision snapshots; Markdown keeps one editable
file per memory. An ordinary save records a revision without claiming that it
replaces another description of the world. For an explicit replacement, use
`supersede_memory`, or check **Replaces the previous description** in the search
editor. Supply the real contributor identity and the reason. The newer record
carries a link, never evidence:

```json
{"target":"memory-id","version":2,"rel":"supersedes","reason":"correction","contributor":{"id":"user:actual-editor","kind":"human"}}
```

Explicit supersedes links may target another memory too. Known targets without
a supplied version resolve to the existing revision. Audit-profile imports
require a contributor. Missing recommended context and disagreements with a
carried `invalidated_by` are reported in receipts; contradictory pointers are
preserved and current reads do not choose between them.

Current search/graph reads exclude superseded and expired records. Choose
**History** in Search for read-only revisions, call
`get_memory(identifier, version=2)` for a retained revision, or use
`include_history=True` with MCP search/get. The HTTP APIs accept the same query
parameters. `/api/graph?include_history=true` exposes `revisions` and
`revision_edges`, including target versions, reasons and contributors. Graph
details show replaced revisions without crowding the current graph.

History starts from retained records when this feature is enabled; earlier
content cannot be reconstructed. Metadata-only checksum variants can share a
version. Forgetting erases retained content from the export and adapter history
as well as the current views. Rebuilding a non-Markdown adapter restores retained
history from the OMP export.

Additional checks: `tests/test_revision_history.py`, `tests/test_supersession.py`
and `tests/test_ui_writes.py`. Run test scripts individually; `test_live.py` is
an explicit destructive run of show against a separately launched demo.
