# AI Disclosures Project demo: run of show

The live demo uses `omp-live/aidp-memories.json`: 32 notes, including a `personal/` folder
of Ilan's agent's notes about Ilan, the rest restating public AI
Disclosures Project material, each with its source URL, plus one retained earlier
revision. The agent is called Ilan's agent and starts with an empty chat.

For a separate clean run, stop the existing server and use an empty folder:

```sh
cd omp-live
. .venv/bin/activate
omp-sync --root /tmp/aidp-demo seed aidp-memories.json
omp-sync --root /tmp/aidp-demo demo
```

Seeding adds records; it does not delete records already in a folder.

1. Open **File system → MEMORY.md**. It says where the notes come from and links
   to the project, the Open Memory Protocol, the memory record and the open issues.
2. Press **See the OMP format** (or O). Walk the four required fields, then pick
   a memory on the right to show its live record, and switch to **Manifest**.
3. Ask Ilan's agent: “Who directs the AI Disclosures Project?” It should read
   `people/directors.md` and name Tim O’Reilly and Ilan Strauss.
4. Ask: “How should you talk to me?” It should read `personal/communication.md`:
   Ilan prefers direct communication. Open the file to show its provenance
   (the agent authored it, Sruly instructed it).
5. Ask: “Remember that we're presenting OMP at the Berkeley gathering this week.”
   Watch the automatic conversion from file to OMP record, knowledge graph and
   search index.
6. Open **Knowledge graph → All memories**. Click a node to expand it.
7. Open **Search index**, query “tombstone”, and inspect a result.
8. Switch Search to **History** and open `spec/working-draft.md`. The working
   spec moved from v0.1 to the v0.2 editors' draft; the newer revision carries a
   supersedes link with the reason and the seed as contributor.
9. Drag a file onto a folder. Its location changes across all stores while its
   identifier and relationships stay the same.
10. Use the MCP endpoint shown in the dashboard to add or search a memory. MCP
   changes sync quietly, without the conversion animation.
