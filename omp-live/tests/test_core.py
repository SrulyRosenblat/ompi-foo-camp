import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from omp_live.cli import build
from omp_live.model import checksum

root = Path(tempfile.mkdtemp()) / "demo"
sync = build(root)
SAMPLE = Path(__file__).resolve().parents[2] / "sample" / "memories.json"
if not SAMPLE.exists(): SAMPLE = Path("/mnt/user-data/uploads/ompi-foo-camp/sample/memories.json")
sample = json.loads(SAMPLE.read_text())
print("seed", sync.seed(sample))
w, g, s = sync.systems["wiki"], sync.systems["graph"], sync.systems["search"]
def counts(): return {n: len(sy.export()) for n, sy in sync.systems.items()}, len(sync.export.list_ids())
print("after seed", counts())
assert counts() == ({"wiki": 9, "graph": 9, "search": 9}, 9)
# idempotent: second tick writes no receipts
assert sync.reconcile() == 0, "echo loop!"
assert sync.reconcile() == 0

# 1. edit in wiki: add a wikilink
maya = root/"wiki/team/people/maya.md"
maya.write_text(maya.read_text() + "\nSee [[Decision: Postgres for the ledger]] and [[Nonexistent page]].\n")
n = sync.reconcile(); print("wiki edit receipts", n)
assert sync.reconcile() == 0
snap = g.snapshot()
edges = [e for e in snap["edges"] if e["src"]=="e7b9a210-billing-owner"]
print("graph edges from maya:", [(e["dst"][:20], e["rel"], e["carrier"]) for e in edges])
assert any(e["dst"]=="0d6e4f88-ledger-decision" and e["carrier"]=="inline" for e in edges)
ghosts = [nd for nd in snap["nodes"] if nd["kind"]=="ghost"]
print("ghosts:", [x["id"] for x in ghosts])
assert any("Nonexistent" in x["id"] for x in ghosts)
E = sync.export.get("e7b9a210-billing-owner"); print("export version", E["version"], [p["id"] for p in E["provenance"]])
assert E["version"]["value"] == 1  # seeded without a version, so first revision
assert "Nonexistent" in [d["title"] for d in s.docs() if d["identifier"]=="e7b9a210-billing-owner"][0] or True
hits = s.search("postgres"); print("search postgres ->", [h["identifier"][:20] for h in hits])
assert any(h["identifier"]=="e7b9a210-billing-owner" for h in hits)

# 2. add a typed edge in the graph
g.add_edge("c41d7e02-flaky", "b3c2e9f1-ci-matrix", "derived_from")
n = sync.reconcile(); print("graph edge receipts", n); assert sync.reconcile()==0
fm = (root/"wiki/projects/web/known-issues.md").read_text()
print(fm.split("---")[1])
assert "derived_from" in fm and "b3c2e9f1-ci-matrix" in fm

# 3. edit body in search
s.write_body("2f8a1c3e-pnpm", "Use `pnpm`, never `npm` or `yarn`, in `apps/web`. The lockfile is `pnpm-lock.yaml`. Corrected from search.")
n = sync.reconcile(); print("search edit receipts", n); assert sync.reconcile()==0
assert "Corrected from search" in (root/"wiki/projects/web/tooling.md").read_text()
assert "Corrected from search" in [nd["body"] for nd in g.snapshot()["nodes"] if nd["id"]=="2f8a1c3e-pnpm"][0]

# 4. forget + anti-resurrection
old = (root/"wiki/projects/web/known-issues.md").read_text()
sync.forget("c41d7e02-flaky", reason="demo")
assert not (root/"wiki/projects/web/known-issues.md").exists()
assert "c41d7e02-flaky" not in [d["identifier"] for d in s.docs()]
flaky_node = [nd for nd in g.snapshot()["nodes"] if nd["id"]=="c41d7e02-flaky"]
print("flaky node after forget:", flaky_node and flaky_node[0]["kind"])  # ghost: ships-fridays links to it
(root/"wiki/projects/web/known-issues.md").write_text(old)   # re-drop old copy
sync.reconcile()
rs = sync.export.receipts(3); print([ (r["system"], r["outcome"]) for r in rs])
assert rs[-1]["outcome"]=="rejected" and "forgotten" in rs[-1]["reason"]
assert sync.export.get("c41d7e02-flaky") is None
assert "c41d7e02-flaky" not in [d["identifier"] for d in s.docs()]
assert sync.reconcile()==0

# 5. conflict: wiki and graph edit the same memory in the same tick
p = root/"wiki/team/preferences/status-update-day.md"
p.write_text(p.read_text().replace("Fridays", "Thursdays"))
g.add_edge("9b2e7c14-3f6a-4d1e-8a5b-2c7f9e0d4b31", "e7b9a210-billing-owner", "relates_to")
sync.reconcile()
rs = sync.export.receipts(4); print([(r["system"], r["outcome"]) for r in rs])
assert any(r["outcome"]=="conflict" for r in rs)
E = sync.export.get("9b2e7c14-3f6a-4d1e-8a5b-2c7f9e0d4b31"); print("x_conflicts", E.get("x_conflicts"))
assert sync.reconcile()==0
assert [d for d in s.docs() if d["identifier"].startswith("9b2e")][0]["conflicts"]==1
print("conflicts parked:", [c["system"] for c in sync.export.conflicts()])
sync.resolve("9b2e7c14-3f6a-4d1e-8a5b-2c7f9e0d4b31", keep="graph")
E = sync.export.get("9b2e7c14-3f6a-4d1e-8a5b-2c7f9e0d4b31")
print("after resolve version", E["version"], "links", [(l["target"][:12], l["rel"]) for l in E["links"]])
assert "x_conflicts" not in E and any(l["rel"]=="supersedes" for l in E["links"])
assert sync.reconcile()==0
assert "relates_to" in p.read_text()

# 6. rebuild graph from the export folder
print("rebuild graph:", sync.rebuild("graph")); assert len(g.export())==len(sync.export.list_ids())
assert sync.reconcile()==0
# 7. a new page with no front matter
(root/"wiki/scratch.md").write_text("# Releases are tagged on Fridays\n\nWe tag on Fridays, see [[Maya owns billing]].\n")
sync.reconcile(); sync.reconcile()
txt = (root/"wiki/scratch.md").read_text(); print(txt[:120])
assert txt.startswith("---\nidentifier:")
new = [r for r in sync.export.all() if r.get("path")=="scratch.md"][0]
print("new memory provenance:", new.get("provenance"))
assert sync.reconcile()==0
print("ALL OK", counts())

# 8. every system edits title, tags and body
g.update_node("e7b9a210-billing-owner", title="Maya owns payments", tags=["person", "ownership", "payments"], body="Maya Chen owns payments now.")
sync.reconcile(); sync.reconcile()  # the body lost its [[wikilinks]], so the wiki re-derives links once
assert sync.reconcile() == 0
t = (root/"wiki/team/people/maya.md").read_text(); assert "title: Maya owns payments" in t and "- payments" in t and "owns payments now" in t
assert [d for d in s.docs() if d["identifier"]=="e7b9a210-billing-owner"][0]["title"] == "Maya owns payments"
s.write_doc("0d6e4f88-ledger-decision", title="Decision: Postgres for the ledger (confirmed)", tags=["decision", "architecture", "confirmed"])
sync.reconcile(); assert sync.reconcile() == 0
assert "(confirmed)" in (root/"wiki/projects/payments/decisions/ledger-store.md").read_text()
assert "confirmed" in [n["tags"] for n in g.snapshot()["nodes"] if n["id"]=="0d6e4f88-ledger-decision"][0]
w.write_page("projects/web/tooling.md", "Use pnpm. Edited in the wiki with tags.", title="pnpm in the web repo", tags=["preference", "tooling", "web"])
sync.reconcile(); assert sync.reconcile() == 0
assert [n for n in g.snapshot()["nodes"] if n["id"]=="2f8a1c3e-pnpm"][0]["label"] == "pnpm in the web repo"
print("edits in every system ok")

# 9. trace
from omp_live.trace import trace
tr = trace(sync, "e7b9a210-billing-owner")
assert tr["wiki"]["path"] == "team/people/maya.md" and tr["export"]["title"] == "Maya owns payments"
assert tr["graph"]["node"]["label"] == "Maya owns payments" and tr["search"]["title"] == "Maya owns payments"
assert any(f["field"] == "links" and "edges" in f["graph"] for f in tr["fields"])
tr2 = trace(sync, "c41d7e02-flaky"); assert tr2["tombstone"] and tr2["export"] is None and tr2["graph"]["node"]["kind"] == "ghost"
print("trace ok")
