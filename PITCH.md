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
who said it, and what was deleted.

The Open Memory Protocol v0.2 editors' draft (PR #13) combines seven sources:
Letta, IBM, AIDP/FMP, Cognee, Context Nest, the Mila + Mozilla AMS Card and the
scoping note. It defines a minimal memory object (three required fields plus a
body), a manifest with a global identity (`origin` + `identifier`), provenance
as a list of contributors, import receipts, tombstones that stop forgotten data
from coming back, and profiles from "a folder of markdown" up to "audit".

We'll spend about 15 minutes on a live demo. A pile of markdown files becomes one
export, and that export becomes a Markdown folder, a knowledge graph, a vector
index, an agent's context and topic summaries. Then one memory moves through four systems, and we compare what
survives each move with pairwise converters and with a shared format. After that we pick
two of six open issues and settle them as a group. Builders who maintain a
harness, memory layer or vector store are especially welcome.

## Run of show (about 55 minutes)

| Time | Slides | What happens |
|---|---|---|
| 0:00 | 1 | Two show-of-hands questions: who uses more than one agent? Who has moved memory between them? |
| 0:03 | 2–3 | The problem: the same fact in countless formats, with no identity, provenance or lifecycle. Then the adapter slider: a converter for every pair of tools vs one import and one export per tool |
| 0:08 | 4 | The memory object: three required fields plus a body |
| 0:11 | **5** | **Live demo.** Files in. Ask for a volunteer to AirDrop a `CLAUDE.md`, `AGENTS.md` or a folder of notes and drop it on the deck. The files convert into one export, no model needed |
| 0:14 | **6** | **Live demo.** Out to any format. The target rotates: Markdown folder, knowledge graph, vector index, agent context, topic summaries. Point at the AI and embeddings flags |
| 0:18 | **7** | **Live demo.** One memory, four stops: Claude Code → team memory server → graph store → Codex. Plays by itself (about 13 seconds): on the converter track the labels fall off, on the shared-format track they stay and each system adds a stamp. Replay is next to the headline |
| 0:23 | **8** | **Live demo.** Two stores exchange memory in six steps that play by themselves (about 30 seconds): introductions, a copy, a move, a conflict OMP doesn't resolve, a forget, and an old copy coming back. Point at the receipts in the middle |
| 0:30 | **9** | **Vote**, then discuss the top two issues (about 11 minutes each) |
| 0:52 | 10 | The ask, plus names and emails on the index card |

If time is short, skip slide 4 and explain the fields during the demos.

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
| All spec content, statuses and issue numbers | PR #13 working spec v0.2, 2026-10-14 |
| 12 harnesses | `prototypes/acp_memory_server` README |
| Checksums verify in the browser | `sample/build_sample.py` (Python) and the deck (WebCrypto) agree |

The four systems in the trip demo, and the converters between them, are
illustrations written for the session. They are not vendor integrations. The spec is an
editors' draft, not an adopted standard, and the deck says so on slide 9.
