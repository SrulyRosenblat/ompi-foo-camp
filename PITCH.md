# FOO session pitch: Open Memory Protocol

## The card for the session board

> **Your agent's memory is a hostage. Let's agree on the export format.**
> Bring a MEMORY.md, AGENTS.md, or a JSON dump. We'll round-trip it live.

Other titles, if that one is taken or doesn't fit the room:

- *Can you leave your coding agent? (Not without losing what it learned about you.)*
- *One file format for agent memory: what goes in it, and six fights we haven't had*

## 30-second hallway version

Every coding agent now has memory: `CLAUDE.md`, `AGENTS.md`, `MEMORY.md`, memory
blocks, vector stores. None of them agree on what a memory is. So when you switch
tools, you lose what it learned, who told it, and what you asked it to forget.
Letta, IBM, Cognee, Context Nest, Mila and Mozilla have each written a draft. We
merged them into one working spec. It's a transfer format, not a storage format.
In the session I'll show one export opening in five different tools, then we'll
argue about the six issues that are still open. Bring your agent's memory file.

## Intro-circle version (two sentences)

I work on the Open Memory Protocol: one portable format for what AI agents
remember about you, so it can move between Claude Code, Codex, goose, and the
rest. I'm running a session where we round-trip your agent's memory live and
settle a few open questions in the spec.

## Session description (for a schedule or the wiki)

Agent memory is the new lock-in. Every harness keeps it differently, and the
exports that exist lose the parts that matter: when something was learned,
who said it, and what was deleted. In a field report from the working group, a
store reported 208 records "applied" while keeping none of them.

The Open Memory Protocol v0.2 editors' draft (PR #13) combines seven sources:
Letta, IBM, AIDP/FMP, Cognee, Context Nest, the Mila + Mozilla AMS Card and the
scoping note. It defines a minimal memory object (three required fields plus a
body), a manifest with a global identity (`origin` + `identifier`), provenance
as a list of contributors, import receipts, tombstones that stop forgotten data
from coming back, and profiles from "a folder of markdown" up to "audit".

We'll spend about 15 minutes on a live demo. One export file opens as a Markdown
folder, a knowledge graph, a search index, an agent's context window, and an
auditor. Then it goes through three importers and a forget. After that we pick
two of six open issues and settle them as a group. Builders who maintain a
harness, memory layer or vector store are especially welcome.

## Run of show (about 55 minutes)

| Time | Slides | What happens |
|---|---|---|
| 0:00 | 1 | Two show-of-hands questions: who uses more than one agent? Who has moved memory between them? |
| 0:03 | 2–4 | The problem in three slides. Same fact in five shapes, the field report numbers, and the N×M slider |
| 0:08 | 5–7 | The format. Scope, the three-field minimal memory, the manifest and global identity |
| 0:13 | **8** | **Live demo.** One export, five tools. Ask for a volunteer to AirDrop a `CLAUDE.md` or `AGENTS.md` and drop it on the deck. The auditor shows what it already conforms to and what's missing |
| 0:20 | 9–10 | Runtime projection vs interchange. Provenance without a confidence score |
| 0:24 | **11–12** | **Live demo.** Import receipts across three stores, then forget a memory and try to bring it back from an old backup |
| 0:29 | 13–15 | Dangling references and trust on import. What crosses the runtime boundary. The proof that the sample round-trips through separately written SDK code |
| 0:33 | **16** | **Vote**, then discuss the top two issues (about 10 minutes each) |
| 0:55 | 17 | The ask, plus names and emails on the index card |

If the room is small and hands-on, skip 5, 9, 13 and 14 and go straight from the
demos to the vote. The appendix slides are for questions about the v0.1 → v0.2
changes and the checksum convention.

## Choosing which issues to discuss

- **Mostly builders** (harness, memory layer or vector DB): I-8 (identity on
  import) and I-21 (thin core with semantic conventions).
- **Mostly policy or security people:** I-7 (is forgetting core?) and I-22 (trust
  on import / prompt-injection surface).
- **Mixed room:** I-20 (should accuracy travel as a number?). It splits people
  the fastest.

Write down outcomes during the session. Post them to the exchange-and-runtime
thread tagged "FOO 2026" so they can be attributed in v0.3.

## Things to have ready

- `deck.html` open in a browser, full screen. It works offline and makes no
  network calls.
- A USB stick or AirDrop target for people's memory files.
- `sample/` in a terminal, to replay the `omp_convert` round trip if asked:
  ```sh
  cd ../Open-Memory-Protocol/prototypes/python-conversion-sdk
  python3 -m omp_convert omp-to-graph ../../../foo-camp/sample /tmp/g.json
  python3 -m omp_convert graph-to-omp /tmp/g.json /tmp/back
  ```
- Index cards for follow-up contacts.

## Claims in the deck and where they come from

| Claim | Source |
|---|---|
| 204/204 chunks intact, 204/204 lost `ingested_at`, 208 "applied" / 0 stored | PR #12 Hermes field report, 2026-10-02 |
| All spec content, statuses and issue numbers | PR #13 working spec v0.2, 2026-10-14 |
| 12 harnesses | `prototypes/acp_memory_server` README |
| 7/7 fidelity checks, 0 model calls | `python-conversion-sdk/demo-output/report.json` |
| Graph round trip: 0 fields changed. Wiki round trip: 1 field (path added to `MEMORY.md`) | Run on this deck's `sample/` on 2026-10-20 |
| Checksums verify in the browser | `sample/build_sample.py` (Python) and the deck (WebCrypto) agree |

The cloud, graph and "typical store" importers in the deck are illustrations
written for the session. They are not vendor integrations. The spec is an
editors' draft, not an adopted standard, and the deck says so on slide 15.
