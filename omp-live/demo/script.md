# Cloudberry Observatory: fictional run of show

The live demo uses `omp-live/fictional-memories.json`: 23 invented memories (7 of them personal notes about the fictional observer Juniper Hale) and
one retained earlier revision. Its people, places, equipment, and operating
rules are fictional. The agent starts with an empty chat.

For a separate clean run, stop the existing server and use an empty folder:

```sh
cd omp-live
. .venv/bin/activate
omp-sync --root /tmp/cloudberry-demo seed fictional-memories.json
omp-sync --root /tmp/cloudberry-demo demo
```

Seeding adds records; it does not delete records already in a folder.

1. Open **Wiki → MEMORY.md**. It explains the fictional setting and links to
   the aurora survey, Iris Vale, mirror calibration, and observation window.
2. Ask the agent: “Who maintains Sky Lantern?” It should read the fictional
   notes and identify Iris Vale.
3. Ask: “For the fictional observatory, remember that Pavo checks the amber
   lamps before each observation session.” Watch the automatic conversion
   from wiki to OMP, graph, and search.
4. Open **Graph → All memories**. Click a node or its + to expand its content.
   In focused view, expanding a neighbor reveals further connections.
5. Open **Search**, query “violet”, and inspect a result. Ordinary saves create
   revisions. For an explicit replacement, check **Replaces the previous
   description** and supply the reason and contributor identity.
6. Switch Search to **History** and open the observation-window revisions.
   The fictional schedule changed from 21:00 to 22:00 UTC; the newer revision
   carries a supersedes link with the reason and the fictional contributor.
7. Drag a wiki note onto a folder. Its location changes across all stores while
   its identifier and relationships remain stable.
8. Use the MCP endpoint shown in the dashboard to add or search a fictional
   item. MCP changes synchronize quietly, without presentation animations.
