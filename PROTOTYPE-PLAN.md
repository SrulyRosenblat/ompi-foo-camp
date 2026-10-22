# omp-live: one memory, three systems, synced in real time

Prototype plan for the FOO session demo. Builds on the OMP v0.2 editors' draft
(PR #13) and the `sample/` export this deck already embeds.

## The claim the demo makes

> Write a memory anywhere, and it shows up everywhere, with its identity,
> links, provenance and lifecycle intact. Each system implements one import
> and one export. Nobody writes a pairwise converter, and nothing sits in
> the middle.

Three systems, visibly different, all live at once:

| System | What it is | Native shape | Look |
|---|---|---|---|
| **Wiki** | an LLM-maintained markdown wiki (a folder on disk; Obsidian/VS Code/Claude Code can edit it) | `.md` files, YAML front matter, `[[wikilinks]]` in the body | cream paper, serif, rendered page + backlinks panel |
| **Graph** | a graph memory store | nodes = memories, people, sources; typed edges | dark, force-directed, nodes colored by tag |
| **Search** | a full-text markdown index | SQLite FTS5 rows (same pattern as `acp_memory_server`) | monospace console, hit highlighting, facets |

OMP is the only thing that moves between them.

## Architecture: no hub, the export folder is the bus

```
 Obsidian / VS Code / Claude Code / Dropbox
               │ writes .md
               ▼
   ┌──────────────────┐                      ┌──────────────────┐
   │  wiki/           │   wiki.export()      │  omp-export/     │
   │  (markdown)      │─────────────────────▶│   manifest.json  │
   │                  │◀─────────────────────│   memories/*.json│
   └──────────────────┘   wiki.import()      │   tombstones/    │
                                             │   receipts/      │
   ┌──────────────────┐   graph.export()     │                  │
   │  graph/          │─────────────────────▶│                  │
   │  (sqlite edges)  │◀─────────────────────│                  │
   └──────────────────┘   graph.import()     │                  │
                                             │                  │
   ┌──────────────────┐   search.export()    │                  │
   │  search/         │─────────────────────▶│                  │
   │  (sqlite fts5)   │◀─────────────────────│                  │
   └──────────────────┘   search.import()    └──────────────────┘

              one process: omp-sync, watching all four folders
```

- **No central store.** The OMP export directory (§8: manifest, one JSON
  file per memory, tombstones, receipts) is a plain folder. Any system can
  be deleted and rebuilt from it; the export is the interchange form (§7.1),
  the three systems hold runtime projections.
- **One sync script** (`omp-sync`) runs a `watchdog` observer on the wiki
  folder, the graph store, the search store and the export folder. A change
  in a system calls that system's `export()` to update the export folder; a
  change in the export folder calls every other system's `import()`. That's
  the whole algorithm. No server, no SSE, no hooks.
- **Each system is self-contained**: its own store, its own `import(omp)` /
  `export() -> omp`, its own small UI reading only its own store. The three
  UIs don't know about each other or about OMP. That is the point: the
  audience sees three unrelated tools agreeing because of a file format.
- The symmetry (one import, one export per system) is the slide-3 argument
  made concrete.

### Which OMP fields do the work

| Field | Role in the demo |
|---|---|
| `identifier` + manifest `origin` | identity survives renames and round-trips; a wiki page renamed keeps its node in the graph. New files without front matter get a UUID minted and written back once |
| `path` | the wiki's folder structure; shown as the search facet tree; graph ignores it (I-19 made visible) |
| `links` (typed edges) **and** inline `[[wikilink]]` | both carriers from §5.3 / I-5: `[[Page]]` in a body becomes a `relates_to` edge in the graph; an edge drawn in the graph becomes a `links:` entry in front matter. Audience sees that both work and where they differ |
| `version` + `updated_at` + `checksum` | echo suppression and conflict detection. Checksum canonicalization is the one already in `sample/build_sample.py` |
| `provenance` | every system's `export()` appends itself as a contributor (`imported`, `edited`); the wiki shows it as a byline, the graph as faint edges to person/agent nodes, search as a column. Files with no front matter travel with **no** provenance (§4.5): the UIs render "author unknown". An agent that wants a byline writes it into the front matter itself |
| `valid_until` | expired memories gray out in all three; they're not deleted |
| tombstones + `exported_at` | delete a wiki page → tombstone file → node and index row vanish → re-dropping the old `.md` is rejected with a receipt (anti-resurrection) |
| dangling references (§8.5) | `[[A page that doesn't exist]]` becomes a dashed edge to a ghost node; search shows it in a "dangling" facet. Nothing fails |

## Sync mechanics

**File watcher only.** `watchdog`, debounce 150 ms, treat `moved` as modified
(editors write temp-then-rename), ignore dotfiles and `~` suffixes. One
mechanism covers every writer that lands on disk: a human in Obsidian,
Claude Code, `cp`, Dropbox or iCloud sync.

**Echo suppression** (the thing that will bite): when `wiki.import()` writes
a `.md` because the graph changed a link, the wiki watcher fires. Each
`import()` records the checksum of what it wrote; the sync script drops a
change event whose on-disk checksum matches that record. Same rule in every
adapter, and in the export folder itself.

**Conflict:** an edit in two systems inside the same window produces two
export files with the same base `version`. The export folder keeps both
(`<identifier>.<version>.json`), marked incomparable (§6.1); all three UIs
show a "2 versions" badge. OMP does not resolve it; a person picks one in any
UI, which writes a `supersedes` link. This is slide 8's conflict step, live.

**Hosted stores**, out of scope for the demo: a system with no filesystem
replaces the watcher with a poll on an `updated_at` watermark (the
`acp_memory_server` poller pattern). Nothing else changes.

## Repo layout

```
omp-live/
  omp_live/
    model.py          OMP memory + manifest dataclasses, checksum, validation
                      (reuse prototypes/python-loader-validator where it fits)
    export_dir.py     read/write the export folder: memories, tombstones, receipts
    sync.py           the watcher loop; echo filter; conflict detection
    cli.py            omp-sync run | rebuild <system> | forget <id> | receipts
  systems/
    wiki/             adapter.py (front matter ⇄ OMP, [[wikilink]] ⇄ links), serve.py, ui.html
    graph/            adapter.py (OMP ⇄ nodes/edges in sqlite), serve.py, ui.html
    search/           adapter.py (OMP ⇄ FTS5 rows), serve.py, ui.html
  ui/
    index.html        three iframes for the projector
  demo/
    wiki/             seeded from ../sample (same 9 memories, as .md with front matter)
    script.md         the click-by-click run of show below
```

Stack: Python 3.12, `watchdog`, `python-frontmatter`, SQLite (+FTS5),
`http.server` per system (each UI polls its own store every 500 ms; no
websockets). Frontend: vanilla JS, `marked` for the wiki, `d3-force` for the
graph, nothing else. Runs offline, like the deck.

## Build order

| # | Milestone | Done when | Est. |
|---|---|---|---|
| 0 | Model + export folder + CLI | `../sample` loads into `omp-export/` and reads back byte-equal; receipts written | 2 h |
| 1 | Wiki adapter + sync loop | editing a `.md` in VS Code updates the export folder within 300 ms; a rename keeps the identifier; no echo loop | 4 h |
| 2 | Search system | FTS over bodies and titles; updates from the export folder; facets by `path`, `tags`, provenance kind | 2 h |
| 3 | Graph system | force graph with typed edges, wikilinks as edges, people/agents as nodes, dangling ghosts dashed | 4 h |
| 4 | Writes back from graph and search | drawing an edge writes `links:` into front matter; editing a body in search writes the `.md` | 3 h |
| 5 | Lifecycle | forget → tombstone → anti-resurrection; `valid_until` graying; conflict badge | 3 h |
| 6 | Demo script + rehearsal | `demo/script.md` runs end to end twice without a restart | 1 h |

About 19 hours. Milestones 0–3 are the demo; 4–6 are what makes it an OMP
demo rather than a file watcher demo. If time runs short, cut 4 before 5.

## Run of show (replaces or extends deck slides 5–8)

1. **Seed.** Drop `demo/wiki/` in. All three panes fill. Point at the
   `origin` id in each pane header and the receipts folder growing.
2. **Edit in the wiki.** Open `team/people/maya.md` in VS Code, add
   `[[Decision: Postgres for the ledger]]`. The graph grows an edge; search
   re-ranks. ~300 ms.
3. **Agent writes.** In Claude Code: "remember that we tag releases on
   Fridays, and sign the memory". It writes a `.md` with a `provenance`
   entry in the front matter; the watcher picks it up and the new node
   appears with a byline. Contrast with step 2's "author unknown".
4. **Edit in the graph.** Drag an edge `derived_from` between two nodes. Show
   the `links:` entry appear in the markdown file.
5. **Edit in search.** Fix a typo in a body from the search pane. The wiki
   page re-renders.
6. **Forget.** `omp-sync forget c41d7e02-flaky`. Node and row vanish, a
   tombstone file appears. Drag the old `.md` back in: rejected, receipt says
   why.
7. **Conflict.** Edit the same memory in the wiki and the graph at once. Two
   versions, incomparable, badge in all three panes. Pick one; `supersedes`
   link written.
8. **Expire.** Set `valid_until` to one minute from now on a memory; watch it
   gray out.
9. **Kill a system.** Delete `graph/store.db`. `omp-sync rebuild graph`
   restores it from the export folder. Nothing was lost because the export
   is the record.

## Open issues the demo puts on the table

- **I-5 links**: the audience watches both carriers work and sees their
  mismatch (a wikilink can't carry `rel`; a typed edge can't be read in a
  plain editor). Good vote fodder.
- **I-8 identity on import**: the demo keeps origin identifiers and shows
  the origin-to-local mapping in receipts.
- **I-7 tombstones**: step 6 is the anti-resurrection case, live.
- **I-11 change notification**: a watched folder is one implementation of
  the thing the spec declined to standardize. Worth asking whether that holds.
- **I-19 `path`**: the graph has nowhere to put it; the search pane builds a
  facet tree from it. Shows what's lost.

## Risks

- Echo loops. Mitigation above; test it first, in milestone 1.
- Editors that write temp files (Obsidian, VS Code): handle `moved`, ignore
  dotfiles and `~` suffixes.
- Minting identifiers writes front matter into the user's files. Do it once,
  announce it in the receipt, never rewrite a file that already has one.
- Three systems polling their own stores every 500 ms is fine for nine
  memories; say so if asked about scale, it's a demo.
- Wi-Fi: nothing here needs the network. Keep it that way.
- `PITCH.md` points at `prototypes/python-conversion-sdk`, which is not on
  `main`, `draft-prototypes` or PR #13. Either it's local-only or the pitch
  needs updating; `omp-sync` can take its place in the "things to have
  ready" list.

## Reuse

- `prototypes/python-loader-validator`: validation rules and the Packer
  four-rule loading contract (§10.2) for the wiki adapter's read side.
- `prototypes/acp_memory_server/index.py` + `poller.py`: FTS5 schema and the
  watermark poller for the hosted-store story.
- `prototypes/ibm-draft-memory-records` (branch `draft-prototypes`): immutable
  records, override/invalidate, export/import; a model for the lifecycle rules.
- `sample/build_sample.py`: the memories, the checksum canonicalization.
