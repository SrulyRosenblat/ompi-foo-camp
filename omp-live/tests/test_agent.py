"""The agent's tool loop and its effect on the other systems, with a scripted model."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")

from omp_live.agent.agent import Agent  # noqa: E402
from omp_live.cli import build  # noqa: E402

SAMPLE = Path(__file__).resolve().parents[2] / "sample" / "memories.json"
if not SAMPLE.exists():
    SAMPLE = Path("/mnt/user-data/uploads/ompi-foo-camp/sample/memories.json")

root = Path(tempfile.mkdtemp()) / "demo"
sync = build(root)
sync.seed(json.loads(SAMPLE.read_text()))
agent = Agent(sync.systems["wiki"], forget_fn=lambda i, by, r: sync.forget(i, by=by, reason=r))

# the loading contract: MEMORY.md in full, everything else indexed
ctx = agent.context()
assert ctx["memory_md"] and "concise" in ctx["memory_md"]
assert len(ctx["index"]) == 8 and all(set(m) == {"path", "title", "tags"} for m in ctx["index"])
assert "scope" not in agent._context_text() and "checksum" not in agent._context_text()

NEW = """---
title: Releases are tagged on Fridays
tags: [observation]
provenance:
  - {id: "user:presenter", kind: human, contribution: instructed}
  - {id: "agent:omp-live", kind: agent, name: "test-model", contribution: authored}
---
We tag releases on Fridays, after [[Status updates move to Friday]].
"""
raw = lambda: {"role": "assistant", "content": ""}
script = iter([
    {"text": "", "tool_calls": [{"id": "t1", "name": "write", "args": {"path": "agent/releases-are-tagged-on-fridays.md", "content": NEW}}], "raw": raw()},
    {"text": "Noted: releases are tagged on Fridays.", "tool_calls": [], "raw": raw()},
    {"text": "", "tool_calls": [{"id": "t2", "name": "read", "args": {"path": "projects/web/tooling.md"}}], "raw": raw()},
    {"text": "", "tool_calls": [{"id": "t3", "name": "edit", "args": {"path": "projects/web/tooling.md", "old_text": "Use `pnpm`, never `npm` or `yarn`, in `apps/web`.", "new_text": "Use pnpm. Revised by the agent."}}], "raw": raw()},
    {"text": "Updated projects/web/tooling.md.", "tool_calls": [], "raw": raw()},
    {"text": "", "tool_calls": [{"id": "t4", "name": "bash", "args": {"command": "rm projects/payments/limits.md"}}], "raw": raw()},
    {"text": "Forgotten.", "tool_calls": [], "raw": raw()},
])
agent._call_model = lambda: next(script)

def turn(text):
    agent._turn(text)
    sync.reconcile(); sync.reconcile()

turn("remember that we tag releases on fridays")
new = [r for r in sync.export.all() if r.get("title") == "Releases are tagged on Fridays"]
assert new, "the written file did not reach the export folder"
prov = new[0]["provenance"]
assert any(p["kind"] == "agent" and p["contribution"] == "authored" for p in prov) and any(p["kind"] == "human" for p in prov)
assert new[0]["identifier"] == "agent/releases-are-tagged-on-fridays.md"
assert new[0]["attributes"] == {} and "created_at" not in new[0], "unknown creation time must stay omitted"
assert any(l.get("x_carrier") == "inline" for l in new[0]["links"]), "wikilink did not become a link"
assert any(n["label"] == "Releases are tagged on Fridays" for n in sync.systems["graph"].snapshot()["nodes"])
print("write ok:", new[0]["path"], [p["id"] for p in prov])

turn("actually just say use pnpm")
rec = sync.export.get("2f8a1c3e-pnpm")
assert "Revised by the agent" in rec["body"]
assert "Revised by the agent" in [d["body"] for d in sync.systems["search"].docs() if d["identifier"] == "2f8a1c3e-pnpm"][0]
assert [t for t in agent.transcript if t["role"] == "tool"][1]["name"] == "read"
print("edit ok")

turn("forget the rate limit memory")
assert sync.export.get("5a0f93bd-rate-limit") is None and sync.export.is_tombstoned("5a0f93bd-rate-limit")
assert all(d["identifier"] != "5a0f93bd-rate-limit" for d in sync.systems["search"].docs())
assert agent.tool_seq == 3 and agent.last_tool["name"] == "bash"
print("rm ok;", [t["role"] + ":" + t.get("name", "") for t in agent.transcript])
assert sync.reconcile() == 0
try:
    agent.run_tool("read", {"path": "../omp-export/manifest.json"}); assert "outside" in agent.transcript[-1]["result"]
    print("sandbox ok")
except AssertionError: raise
print("AGENT OK")
