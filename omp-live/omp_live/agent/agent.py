"""The agent: an ordinary coding-agent harness whose working directory is the
wiki folder. Memory is files.

Tools: ls, read, write, edit, bash. Nothing memory-specific. At the start of
each turn the harness injects the markdown loading contract (§10.2, Packer):
the root MEMORY.md in full, and an index of every other file (path, title,
tags) that the agent reads on demand with `read`. Runtime view only (§7.2):
no checksums, no scope, nothing past its valid-until date.

Writes are plain files. The sync uses the relative file path as a new
identifier and leaves unknown creation dates omitted. §4.5 says nothing about the author gets invented, so the
harness is told to put provenance front matter in the files it creates.
Deleting a file is a forget: the sync tombstones it.

Model: OpenRouter (OpenAI-style chat completions with tools).
OPENROUTER_API_KEY from the environment or a .env in omp-live/ or the folder
above it (either case); OMP_AGENT_MODEL overrides the model name.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..model import is_expired, now_iso
from ..lifecycle import current_records
from ..systems.wiki.adapter import WikiSystem

API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
MAX_STEPS = 12
OUTPUT_LIMIT = 6000

TOOLS = [
    {"name": "ls", "description": "List files under a directory (relative to the working directory).",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "default: ."}}}},
    {"name": "read", "description": "Read a file.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "write", "description": "Create or overwrite a file with the given content. Creates parent directories.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit", "description": "Replace exact text in a file. Pass every change to the file at once in `edits` (title, body and provenance together); they are applied in one write.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"},
                    "edits": {"type": "array", "items": {"type": "object", "properties": {"old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["old_text", "new_text"]}},
                    "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path"]}},
    {"name": "bash", "description": "Run a shell command in the working directory (20 s timeout).",
     "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
]

SYSTEM_PROMPT = """You are Ilan's agent, a coding agent working for Ilan Strauss of the AI Disclosures Project. Your working directory is a memory folder: markdown files with YAML front matter, shared with other tools through the Open Memory Protocol. It holds notes restating public AI Disclosures Project material, including its Asimov's Addendum blog (each with a source URL in its attributes), and your own notes about Ilan under personal/ (read personal/communication.md before answering him); everything you know beyond the summary below is in these files.

How memory works here:
- MEMORY.md (below) is always in your context. Every other file is listed in the index below; read it with `read` before relying on it.
- To remember something new, write a markdown file (kebab-case name) in the folder it belongs in: things about Ilan (his preferences, work, people, habits) go in personal/; notes about a topic go in the existing folder for that topic (see the index below for folders such as blog/, omp/, ompi/, people/, research/, project/, spec/). Create a new folder only when nothing fits. Start it with front matter like this, then the body:
  ---
  title: Short title
  tags: [fact]
  provenance:
    - {id: "USER_ID", kind: human, contribution: instructed}
    - {id: "agent:omp-live", kind: agent, name: "MODEL", contribution: authored}
  ---
  Tags are one or more of: fact, preference, decision, observation, person, workaround. Do not invent creation dates. The file path is the identifier for a new note. Link to other memories with standard Markdown links, e.g. [Vegan](dietary-preference-vegan.md), using a path relative to the file you are writing.
- To correct something, `edit` the existing file; don't create a duplicate. Make every change to that file (title, heading, body, provenance) in a single `edit` call using `edits`; each separate call is a separate revision. Add yourself to its provenance list with contribution: edited.
- To forget something, delete its file (bash rm). Only when asked.
- Answer from the files, say which file you relied on, and be brief: one or two sentences unless asked for more.

About OMP and OMPI (a summary; for details, read the memory files and cite them):
- The Open Memory Protocol (OMP) is an open, royalty-free format for portable agent memory. It lets what an agent remembers, who said it, and what was forgotten move between tools such as Claude Code, Codex, goose and Letta Code. Each tool implements one import and one export instead of a converter for every pair. It is a transfer format, not a storage format.
- The Open Memory Protocol Initiative (OMPI) is the vendor-neutral, multi-stakeholder open-source ecosystem that develops OMP, hosted at the AI Disclosures Project and co-hosted with Mozilla and IBM. OMP is pre-1.0: the current working spec is the v0.2 editors' draft (PR #13), open for review, not an adopted standard.
- A record has identifier, media_type, body and attributes, plus optional title, tags, path, links, provenance (a list of contributors), version and valid_until. Forgetting leaves a tombstone so a forgotten memory never comes back; conflicting edits are kept side by side for a person to resolve; every import leaves a receipt.
- This folder is one of three systems (the file system, a knowledge graph and a search index) kept in sync through an OMP export folder; your writes travel to the others that way. The seeded notes come from public sources; don't add claims about real people that you weren't told.
- Repository: https://github.com/The-AI-Disclosures-Project/Open-Memory-Protocol · Site: https://ai-disclosures.org/ompi
"""


def load_env() -> None:
    here = Path(__file__).resolve().parents[2]
    for candidate in (Path.cwd() / ".env", here / ".env", here.parent / ".env"):
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip().upper(), v.strip().strip('"').strip("'"))


class Agent:
    def __init__(self, wiki: WikiSystem, forget_fn=None, human: str = "user:presenter"):
        load_env()
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise SystemExit("OPENROUTER_API_KEY is not set (environment, omp-live/.env or ../.env)")
        self.wiki = wiki
        self.cwd = wiki.root.resolve()
        self.human = human
        self.model = os.environ.get("OMP_AGENT_MODEL", DEFAULT_MODEL)
        # One conversation per browser page load; None is the default (tests, CLI).
        self.sessions: dict = {None: {"transcript": [], "messages": [], "busy": False, "seen": time.time()}}
        self.tool_seq = 0
        self.last_tool: dict | None = None
        self._lock = threading.Lock()
        self._turns = threading.Lock()  # turns share one folder, so they run one at a time

    def session(self, sid: str | None = None) -> dict:
        with self._lock:
            s = self.sessions.get(sid)
            if s is None:
                stale = [k for k, v in self.sessions.items() if k is not None and not v["busy"] and time.time() - v["seen"] > 3600]
                for k in stale:
                    del self.sessions[k]
                s = self.sessions[sid] = {"transcript": [], "messages": [], "busy": False, "seen": time.time()}
            s["seen"] = time.time()
            return s

    @property
    def transcript(self) -> list[dict]:
        return self.sessions[None]["transcript"]

    @property
    def messages(self) -> list[dict]:
        return self.sessions[None]["messages"]

    @property
    def busy(self) -> bool:
        return any(s["busy"] for s in list(self.sessions.values()))

    # ---- the loading contract (§10.2) ------------------------------------------
    def context(self) -> dict:
        """What is injected each turn: MEMORY.md in full, everything else as an index."""
        root = self.cwd / "MEMORY.md"
        memory_md = root.read_text(encoding="utf-8") if root.exists() else None
        index = []
        records = self.wiki.export()
        current = current_records(records)
        if any(r.get('path') == 'MEMORY.md' for r in records) and not any(r.get('path') == 'MEMORY.md' for r in current):
            memory_md = None
        for r in current:
            if r.get("path") == "MEMORY.md":
                continue
            index.append({"path": r["path"], "title": r.get("title"), "tags": r.get("tags") or []})
        return {"memory_md": memory_md, "index": index}

    def _context_text(self) -> str:
        c = self.context()
        parts = ["## MEMORY.md", c["memory_md"].strip() if c["memory_md"] else "(no MEMORY.md)", "",
                 "## Other memory files (read before relying on them)"]
        for m in c["index"]:
            parts.append(f"- {m['path']}  —  {m['title']}" + (f"  [{', '.join(m['tags'])}]" if m["tags"] else ""))
        if not c["index"]:
            parts.append("(none)")
        return "\n".join(parts)

    # ---- tools ----------------------------------------------------------------
    def _path(self, rel: str) -> Path:
        p = (self.cwd / (rel or ".")).resolve()
        if p != self.cwd and self.cwd not in p.parents:
            raise ValueError(f"{rel!r} is outside the working directory")
        return p

    def t_ls(self, a):
        base = self._path(a.get("path") or ".")
        if not base.exists():
            return f"no such path: {a.get('path')}"
        out = []
        for p in sorted(base.rglob("*") if base.is_dir() else [base]):
            if any(part.startswith(".") for part in p.relative_to(self.cwd).parts):
                continue
            out.append(str(p.relative_to(self.cwd)) + ("/" if p.is_dir() else ""))
        return "\n".join(out) or "(empty)"

    def t_read(self, a):
        p = self._path(a["path"])
        if not p.is_file():
            return f"no such file: {a['path']}"
        return p.read_text(encoding="utf-8")[:OUTPUT_LIMIT]

    def t_write(self, a):
        p = self._path(a["path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        existed = p.exists()
        p.write_text(a["content"], encoding="utf-8")
        return f"{'overwrote' if existed else 'created'} {a['path']} ({len(a['content'])} chars)"

    def t_edit(self, a):
        p = self._path(a["path"])
        if not p.is_file():
            return f"no such file: {a['path']}"
        text = p.read_text(encoding="utf-8")
        edits = a.get("edits") or ([{"old_text": a["old_text"], "new_text": a["new_text"]}] if "old_text" in a else [])
        if not edits:
            return "no edits given"
        # Apply all replacements, then write once: one revision per update, not one per replacement.
        for e in edits:
            n = text.count(e["old_text"])
            if n != 1:
                return f"old_text occurs {n} times in {a['path']}; it must occur exactly once (nothing was changed)"
            text = text.replace(e["old_text"], e["new_text"], 1)
        p.write_text(text, encoding="utf-8")
        return f"edited {a['path']} ({len(edits)} change{'s' if len(edits) != 1 else ''})"

    def t_bash(self, a):
        try:
            r = subprocess.run(a["command"], shell=True, cwd=self.cwd, capture_output=True, text=True, timeout=20)
        except subprocess.TimeoutExpired:
            return "timed out after 20 s"
        out = (r.stdout + (("\n" + r.stderr) if r.stderr else "")).strip()
        return (out or "(no output)")[:OUTPUT_LIMIT] + (f"\n[exit {r.returncode}]" if r.returncode else "")

    def run_tool(self, name: str, args: dict, turn: int = 0, session: dict | None = None) -> str:
        fn = {"ls": self.t_ls, "read": self.t_read, "write": self.t_write, "edit": self.t_edit, "bash": self.t_bash}.get(name)
        if fn is None:
            return f"unknown tool {name}"
        try:
            result = fn(args)
        except Exception as e:  # noqa: BLE001
            result = f"error: {e}"
        (session or self.sessions[None])["transcript"].append({"role": "tool", "name": name, "args": args, "result": result})
        if name in ("write", "edit", "bash"):
            self.tool_seq += 1
            self.last_tool = {"seq": self.tool_seq, "name": name, "at": now_iso(),
                              "title": args.get("path") or args.get("command"), "result": result[:200]}
        return result

    # ---- the turn ---------------------------------------------------------------
    def chat(self, text: str, sid: str | None = None) -> None:
        s = self.session(sid)
        with self._lock:
            if s["busy"]:
                return
            s["busy"] = True
        threading.Thread(target=self._turn, args=(text, s), daemon=True).start()

    def _turn(self, text: str, s: dict | None = None) -> None:
        s = s or self.sessions[None]
        transcript, messages = s["transcript"], s["messages"]
        transcript.append({"role": "user", "text": text})
        messages.append({"role": "user", "content": text})
        try:
            with self._turns:
                for _ in range(MAX_STEPS):
                    self._active = messages
                    reply = self._call_model()
                    if reply["text"]:
                        transcript.append({"role": "assistant", "text": reply["text"]})
                    messages.append(reply["raw"])
                    if not reply["tool_calls"]:
                        break
                    for tc in reply["tool_calls"]:
                        result = self.run_tool(tc["name"], tc["args"], session=s)
                        messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
        except Exception as e:  # noqa: BLE001
            transcript.append({"role": "assistant", "text": f"model error: {e}"})
            if messages and messages[-1]["role"] == "user":
                messages.pop()
        finally:
            s["busy"] = False

    def reset(self, sid: str | None = None) -> None:
        s = self.session(sid)
        s["transcript"].clear()
        s["messages"].clear()

    def _call_model(self) -> dict:
        system = (SYSTEM_PROMPT.replace("USER_ID", self.human).replace("MODEL", self.model)
                  + "\n\n" + self._context_text())
        tools = [{"type": "function", "function": t} for t in TOOLS]
        payload = {"model": self.model, "max_tokens": 1200, "tools": tools,
                   "messages": [{"role": "system", "content": system}] + (getattr(self, "_active", None) or self.messages)}
        req = urllib.request.Request(API_URL, data=json.dumps(payload).encode(), headers={
            "Content-Type": "application/json", "Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"],
            "HTTP-Referer": "https://github.com/The-AI-Disclosures-Project/Open-Memory-Protocol", "X-Title": "omp-live"})
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                out = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"OpenRouter {e.code}: {e.read().decode()[:300]}") from None
        if "choices" not in out:
            raise RuntimeError(f"OpenRouter: {json.dumps(out)[:300]}")
        msg = out["choices"][0]["message"]
        calls = []
        for tc in msg.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append({"id": tc["id"], "name": tc["function"]["name"], "args": args})
        raw = {"role": "assistant", "content": msg.get("content") or ""}
        if msg.get("tool_calls"):
            raw["tool_calls"] = msg["tool_calls"]
        return {"text": (msg.get("content") or "").strip(), "tool_calls": calls, "raw": raw}

    # ---- UI state -------------------------------------------------------------------
    def state(self, sid: str | None = None) -> dict:
        c = self.context()
        s = self.session(sid)
        return {"model": self.model, "cwd": str(self.cwd), "busy": s["busy"], "transcript": s["transcript"],
                "tool_seq": self.tool_seq, "last_tool": self.last_tool,
                "context": c, "context_text": self._context_text()}
