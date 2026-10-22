"""The run of show, live: needs `omp-sync --root <root> demo --no-browser` running.

    python3 tests/test_live.py /path/to/demo-root
"""
import json
import sys
import time
import urllib.request as u
from pathlib import Path

R = Path(sys.argv[1] if len(sys.argv) > 1 else "demo")
W, G, S, X = "http://127.0.0.1:8701", "http://127.0.0.1:8702", "http://127.0.0.1:8703", "http://127.0.0.1:8700"


def get(url):
    return json.loads(u.urlopen(url, timeout=3).read())


def post(url, data, method="POST"):
    req = u.Request(url, data=json.dumps(data).encode(), method=method)
    return json.loads(u.urlopen(req, timeout=3).read())


def wait(pred, what, limit=6):
    t0 = time.time()
    while time.time() - t0 < limit:
        try:
            if pred():
                print(f"  {what}: {time.time() - t0:.2f}s")
                return True
        except Exception:
            pass
        time.sleep(0.05)
    print(f"  {what}: TIMEOUT")
    return False


print("1. wiki edit on disk -> graph + search")
p = R / "wiki/team/people/maya.md"
p.write_text(p.read_text() + "\nSee [[Decision: Postgres for the ledger]] and [[Nonexistent page]].\n")
assert wait(lambda: any(e["src"] == "e7b9a210-billing-owner" and e["dst"] == "0d6e4f88-ledger-decision" for e in get(G + "/api/graph")["edges"]), "edge in graph")
assert wait(lambda: any(h["identifier"] == "e7b9a210-billing-owner" for h in get(S + "/api/search?q=postgres")["hits"]), "hit in search")

print("2. graph UI adds a typed edge -> wiki front matter")
post(G + "/api/edge", {"src": "c41d7e02-flaky", "dst": "b3c2e9f1-ci-matrix", "rel": "derived_from"})
assert wait(lambda: "derived_from" in (R / "wiki/projects/web/known-issues.md").read_text(), "links: in wiki file")

print("3. search console edits a body -> wiki + graph")
post(S + "/api/doc", {"identifier": "2f8a1c3e-pnpm", "body": "Use `pnpm` only. Corrected in search."})
assert wait(lambda: "Corrected in search" in (R / "wiki/projects/web/tooling.md").read_text(), "wiki file")
assert wait(lambda: any("Corrected in search" in n["body"] for n in get(G + "/api/graph")["nodes"]), "graph node")

print("4. wiki UI saves a page")
post(W + "/api/page", {"path": "team/preferences/status-update-day.md", "body": "Status updates are due **Thursdays** now.\n"})
assert wait(lambda: any("Thursdays" in d["body"] for d in get(S + "/api/docs")["docs"] if d["identifier"].startswith("9b2e")), "search doc")

print("5. forget from projector -> gone everywhere; re-drop rejected")
old = (R / "wiki/projects/web/known-issues.md").read_text()
post(X + "/api/forget", {"identifier": "c41d7e02-flaky", "reason": "demo"})
assert wait(lambda: not (R / "wiki/projects/web/known-issues.md").exists(), "wiki file deleted")
assert wait(lambda: all(d["identifier"] != "c41d7e02-flaky" for d in get(S + "/api/docs")["docs"]), "search row gone")
(R / "wiki/projects/web/known-issues.md").write_text(old)
assert wait(lambda: any(r["outcome"] == "rejected" and r["identifier"] == "c41d7e02-flaky" for r in get(X + "/api/export")["receipts"]), "rejected receipt")
assert all(d["identifier"] != "c41d7e02-flaky" for d in get(S + "/api/docs")["docs"])

print("6. conflict: wiki and graph in the same instant")
p = R / "wiki/team/people/maya.md"
p.write_text(p.read_text().replace("Maya Chen", "Maya C."))
post(G + "/api/edge", {"src": "e7b9a210-billing-owner", "dst": "f19a0c77-ships-fridays", "rel": "relates_to"})
assert wait(lambda: get(X + "/api/export")["conflicts"], "parked revision")
assert wait(lambda: any(n["conflicts"] for n in get(G + "/api/graph")["nodes"]), "conflict badge in graph")
post(X + "/api/resolve", {"identifier": "e7b9a210-billing-owner", "keep": "graph"})
assert wait(lambda: not get(X + "/api/export")["conflicts"], "resolved")
assert wait(lambda: not any(n["conflicts"] for n in get(G + "/api/graph")["nodes"]), "badge cleared")

print("7. new page from the wiki UI, no front matter")
post(W + "/api/new", {"title": "Releases are tagged on Fridays", "body": "# Releases are tagged on Fridays\n\nSee [[Maya owns billing]].\n"})
assert wait(lambda: any(n["label"] == "Releases are tagged on Fridays" for n in get(G + "/api/graph")["nodes"]), "node in graph")

print("8. quiet after settling (no echo loop)")
time.sleep(2.5)
n0 = len(get(X + "/api/export?n=500")["receipts"])
time.sleep(3)
assert len(get(X + "/api/export?n=500")["receipts"]) == n0, "receipts still being written: loop!"
print("LIVE OK")
