"""omp-sync: the one script.

    omp-sync demo            run the watcher, the three systems, the agent and the projector page
    omp-sync run             run only the watcher (no web pages)
    omp-sync seed FILE       load an OMP memories.json into the export folder
    omp-sync tick            one reconcile pass, then exit
    omp-sync forget ID       tombstone a memory everywhere
    omp-sync rebuild SYSTEM  wipe a system and rebuild it from the export folder
    omp-sync resolve ID --keep export|wiki|graph|search
    omp-sync receipts        print the last receipts
    omp-sync status          what each system holds

Root defaults to ./demo (override with --root). Inside it:
    wiki/  graph/  search/  omp-export/
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

from .httpkit import make_server, serve_in_thread
from .sync import Sync
from .trace import trace
from .systems.graph.adapter import GraphSystem
from .systems.search.adapter import SearchSystem
from .systems.wiki.adapter import WikiSystem

PORTS = {"index": 8700, "wiki": 8701, "graph": 8702, "search": 8703, "agent": 8704, "mcp": 8705}
INDEX_HTML = Path(__file__).with_name("index.html")
TRACE_HTML = Path(__file__).with_name("trace.html")


def build(root: Path) -> Sync:
    root = Path(root)
    return Sync(root, [WikiSystem(root / "wiki"), GraphSystem(root / "graph"), SearchSystem(root / "search")])


# ---- watcher ---------------------------------------------------------------
class Watcher:
    """watchdog on every folder; any event schedules one debounced reconcile."""

    def __init__(self, sync: Sync, debounce: float = 0.15, heartbeat: float = 2.0):
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        self.sync = sync
        self.debounce = debounce
        self.heartbeat = heartbeat
        self._timer: threading.Timer | None = None
        self._running = False
        self._worker: threading.Thread | None = None
        self._pending = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.observer = Observer()

        watcher = self

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event):
                if event.is_directory or event.event_type in ("opened", "closed_no_write"):
                    return  # reads (the UIs poll their stores); only writes matter
                p = str(event.src_path)
                if "/." in p or p.endswith("~") or p.endswith(".tmp") or p.endswith("-journal"):
                    return
                watcher.schedule()

        for folder in (sync.root / "wiki", sync.root / "graph", sync.root / "search", sync.export.path):
            folder.mkdir(parents=True, exist_ok=True)
            self.observer.schedule(Handler(), str(folder), recursive=True)

    def schedule(self) -> None:
        """Coalesce a burst of events into one pass, without starving under a steady stream."""
        with self._lock:
            if self._stop.is_set():
                return
            if self._running:
                self._pending = True
                return
            if self._timer is not None:
                return
            self._timer = threading.Timer(self.debounce, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        with self._lock:
            if self._stop.is_set():
                self._timer = None
                return
            if self._running:
                self._pending = True
                return
            self._timer = None
            self._running = True
            self._worker = threading.current_thread()
        try:
            n = self.sync.reconcile()
            if n:
                for r in self.sync.export.receipts(n):
                    logging.getLogger("omp-sync").info("%-8s %-9s %s %s", r["system"], r["outcome"],
                                                       r["identifier"][:24], r.get("reason", ""))
        finally:
            with self._lock:
                self._running = False
                self._worker = None
                pending, self._pending = self._pending, False
            if pending and not self._stop.is_set():
                self.schedule()

    def run(self) -> None:
        self.observer.start()
        self._fire()
        try:
            while not self._stop.is_set():
                if self._stop.wait(self.heartbeat):
                    break
                self._fire()  # belt and braces: catches anything the OS watcher missed
        finally:
            self._stop.set()
            with self._lock:
                timer, worker = self._timer, self._worker
                if self._timer is not None:
                    self._timer.cancel()
            self.observer.stop()
            self.observer.join()
            # A timer may still be archiving the last accepted revision. Finish it
            # before the caller closes databases or removes a temporary root.
            for thread in (timer, worker):
                if thread is not None and thread is not threading.current_thread():
                    thread.join()


# ---- the projector page -------------------------------------------------------
def index_server(sync: Sync, port: int, agent=None, service=None):
    from .memory_service import MemoryService
    service = service or MemoryService(sync)
    def receipts(q, b):
        return {"origin": sync.export.origin, "receipts": sync.export.receipts(int(q.get("n", 40))),
                "tombstones": sync.export.tombstones(), "conflicts": sync.export.conflicts(),
                "memories": len(sync.export.list_ids()), "ports": PORTS}

    def resolve(q, b):
        return {"ok": sync.resolve(b["identifier"], b.get("keep", "export"), b.get('contributor')) is not None}

    def forget(q, b):
        return {"ok": bool(sync.forget(b["identifier"], by="projector", reason=b.get("reason") or "forget requested"))}

    def activity(q, b):
        since = int(q.get("since", 0))
        # Polled every 400 ms: read a snapshot instead of waiting for the sync lock.
        events = list(sync.events)
        seq = events[-1]["seq"] if events else sync._seq  # consistent with the snapshot
        return {"seq": seq, "events": [e for e in events if e["seq"] > since],
                    "agent": {"busy": agent.busy, "tool_seq": agent.tool_seq, "last_tool": agent.last_tool} if agent else None}

    def trace_route(q, b):
        with sync._lock:
            return trace(sync, q["id"])

    def memories(q, b):
        return {"memories": [{"identifier": r["identifier"], "title": r.get("title") or r["identifier"], "path": r.get("path")} for r in sync.export.all()]}

    return make_server(port, INDEX_HTML, {
        ("GET", "/api/memory/search"): lambda q, b: service.search_memories(q.get("query", ""), int(q.get("limit", 20)), q.get("path_prefix"), q.get('include_history', '').lower() in ('true', '1')),
        ("GET", "/api/memory/get"): lambda q, b: service.get_memory(q["identifier"], int(q['version']) if 'version' in q else None, q.get('include_history', '').lower() in ('true', '1')),
        ("GET", "/api/memory/folders"): lambda q, b: service.list_folders(),
        ("POST", "/api/memory/add"): lambda q, b: service.add_memory(**b),
        ("POST", "/api/memory/update"): lambda q, b: service.update_memory(**b),
        ("POST", "/api/memory/supersede"): lambda q, b: service.supersede_memory(**b),
        ("POST", "/api/memory/move"): lambda q, b: service.move_memory(**b),
        ("GET", "/api/activity"): activity,
        ("GET", "/api/trace"): trace_route,
        ("GET", "/api/memories"): memories,
        ("GET", "/api/export"): receipts,
        ("GET", "/api/manifest"): lambda q, b: sync.export.manifest(),
        ("POST", "/api/resolve"): resolve,
        ("POST", "/api/forget"): forget,
    }, name="index", pages={"/trace": TRACE_HTML},
       # One public address: /wiki/, /graph/, /search/, /agent/ and /mcp reach the other servers.
       proxies={**{f"/{k}/": (PORTS[k], True) for k in ("wiki", "graph", "search", "agent")}, "/mcp": (PORTS["mcp"], False)})


# ---- commands ------------------------------------------------------------------
def cmd_demo(args, sync: Sync):
    from .memory_service import MemoryService
    from .mcp_server import start_http
    from .agent.agent import Agent
    from .agent.serve import server as agent_server
    from .systems.graph.serve import server as graph_server
    from .systems.search.serve import server as search_server
    from .systems.wiki.serve import server as wiki_server

    agent = Agent(sync.systems["wiki"], forget_fn=lambda ident, by, reason: sync.forget(ident, by=by, reason=reason))
    if os.environ.get("OMP_EMBEDDINGS", "on") != "off":
        from .embedding import OpenRouterEmbedder
        sync.systems["search"].start_embedding(OpenRouterEmbedder())
    service = MemoryService(sync)
    servers = [
        wiki_server(sync.systems["wiki"], PORTS["wiki"], sync=sync, service=service),
        graph_server(sync.systems["graph"], PORTS["graph"], sync=sync),
        search_server(sync.systems["search"], PORTS["search"], sync=sync, service=service),
        agent_server(agent, PORTS["agent"]),
        index_server(sync, PORTS["index"], agent, service),
    ]
    for s in servers:
        serve_in_thread(s)
    start_http(service, PORTS["mcp"])
    print(f"wiki    http://127.0.0.1:{PORTS['wiki']}\n"
          f"graph   http://127.0.0.1:{PORTS['graph']}\n"
          f"search  http://127.0.0.1:{PORTS['search']}\n"
          f"agent   http://127.0.0.1:{PORTS['agent']}   ({agent.model})\n"
          f"all     http://127.0.0.1:{PORTS['index']}   (projector page)\n"
          f"mcp     http://127.0.0.1:{PORTS['mcp']}/mcp\n"
          f"embed   {getattr(sync.systems['search'].embedder, 'model', 'off')}  (search; OMP_EMBEDDING_MODEL)\n"
          f"export  {sync.export.path}\n")
    if not args.no_browser:
        webbrowser.open(f"http://127.0.0.1:{PORTS['index']}")
    Watcher(sync).run()


def cmd_run(args, sync: Sync):
    print(f"watching {sync.root}")
    Watcher(sync).run()


def cmd_seed(args, sync: Sync):
    records = json.loads(Path(args.file).read_text())
    if isinstance(records, dict):
        records = records.get("memories", [])
    n = sync.seed(records)
    print(f"seeded {n} of {len(records)} memories; see omp-sync receipts")


def cmd_tick(args, sync: Sync):
    print(f"{sync.reconcile()} receipts")


def cmd_forget(args, sync: Sync):
    tomb = sync.forget(args.identifier, by="cli", reason=args.reason)
    print(json.dumps(tomb, indent=2))


def cmd_rebuild(args, sync: Sync):
    print(f"{args.system}: rebuilt with {sync.rebuild(args.system)} memories")


def cmd_resolve(args, sync: Sync):
    out = sync.resolve(args.identifier, args.keep, args.contributor)
    print("resolved" if out else "nothing to resolve (no such memory, or no parked revision from that system)")


def cmd_receipts(args, sync: Sync):
    for r in sync.export.receipts(args.n):
        print(f"{r['at']}  {r['system']:<9} {r['outcome']:<11} {r['identifier'][:28]:<28} {r.get('reason', '')}")


def cmd_status(args, sync: Sync):
    sync.reconcile()
    print(f"origin   {sync.export.origin}")
    print(f"export   {len(sync.export.list_ids())} memories, {len(sync.export.tombstones())} tombstones, "
          f"{len(sync.export.conflicts())} parked conflicts")
    for name, system in sync.systems.items():
        print(f"{name:<8} {len(system.export())} memories")


def cmd_mcp(args, sync=None):
    from .mcp_server import RemoteMemoryService, create_mcp
    create_mcp(RemoteMemoryService(args.site)).run(transport="stdio")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="omp-sync", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="demo", help="folder holding wiki/ graph/ search/ omp-export/")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("demo"); p.add_argument("--no-browser", action="store_true"); p.set_defaults(fn=cmd_demo)
    p = sub.add_parser("mcp", help="stdio MCP bridge to the running site")
    p.add_argument("--site", default="http://127.0.0.1:8700"); p.set_defaults(fn=cmd_mcp)
    sub.add_parser("run").set_defaults(fn=cmd_run)
    p = sub.add_parser("seed"); p.add_argument("file"); p.set_defaults(fn=cmd_seed)
    sub.add_parser("tick").set_defaults(fn=cmd_tick)
    p = sub.add_parser("forget"); p.add_argument("identifier"); p.add_argument("--reason", default="forget requested"); p.set_defaults(fn=cmd_forget)
    p = sub.add_parser("rebuild"); p.add_argument("system", choices=["wiki", "graph", "search"]); p.set_defaults(fn=cmd_rebuild)
    p = sub.add_parser("resolve"); p.add_argument("identifier"); p.add_argument("--keep", default="export"); p.add_argument('--contributor'); p.set_defaults(fn=cmd_resolve)
    p = sub.add_parser("receipts"); p.add_argument("-n", type=int, default=30); p.set_defaults(fn=cmd_receipts)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    sync = None if args.cmd == "mcp" else build(Path(args.root))
    try:
        args.fn(args, sync)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
