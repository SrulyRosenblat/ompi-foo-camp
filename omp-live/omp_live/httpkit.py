"""A tiny JSON-over-HTTP helper so each system's UI can be its own server."""
from __future__ import annotations

import http.client
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class _Server(ThreadingHTTPServer):
    # The default backlog of 5 drops connections when six panes poll at once; queue them instead.
    request_queue_size = 128


HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "content-length", "host"}


def make_server(port: int, html: Path, routes: dict, name: str = "ui", pages: dict | None = None,
                proxies: dict | None = None) -> ThreadingHTTPServer:
    """routes: {("GET", "/api/x"): fn(query: dict, body: dict) -> object}; pages: {"/path": Path to html}
    proxies: {"/wiki/": (8701, True)} forwards a path prefix to a local port, stripping the prefix if True,
    so one public address can serve every system."""
    pages = pages or {}
    proxies = proxies or {}

    class Handler(BaseHTTPRequestHandler):
        server_version = f"omp-live/{name}"

        def log_message(self, *_):  # quiet
            pass

        def _send(self, status: int, payload, ctype="application/json"):
            data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            try:
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the polling browser navigated away

        def _proxy(self, method: str, port: int, path: str):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=180)
            try:
                conn.request(method, path, body=body, headers=headers)
                resp = conn.getresponse()
                data = resp.read()
            except OSError as e:
                return self._send(502, {"error": f"upstream on port {port}: {e}"})
            finally:
                conn.close()
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() not in HOP_BY_HOP:
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            try:
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _dispatch(self, method: str):
            url = urlparse(self.path)
            for prefix, (target, strip) in proxies.items():
                if prefix.endswith("/") and url.path == prefix[:-1]:
                    self.send_response(301)  # relative URLs in the page need the trailing slash
                    self.send_header("Location", prefix + (("?" + url.query) if url.query else ""))
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if url.path.startswith(prefix) or url.path == prefix:
                    rest = self.path[len(prefix) - 1:] if strip else self.path
                    return self._proxy(method, target, rest)
            if method == "GET" and url.path in ("/", "/index.html"):
                return self._send(200, html.read_bytes(), "text/html")
            if method == "GET" and url.path in pages:
                return self._send(200, pages[url.path].read_bytes(), "text/html")
            fn = routes.get((method, url.path))
            if fn is None:
                return self._send(404, {"error": "no such route"})
            query = {k: v[-1] for k, v in parse_qs(url.query).items()}
            body = {}
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError:
                    return self._send(400, {"error": "bad json"})
            try:
                return self._send(200, fn(query, body))
            except KeyError as e:
                return self._send(400, {"error": f"missing {e}"})
            except (ValueError, FileExistsError) as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"error": str(e)})

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_DELETE(self):
            self._dispatch("DELETE")

        def do_OPTIONS(self):
            self._dispatch("OPTIONS")

    # OMP_HOST=0.0.0.0 for a hosted deployment; local runs stay on loopback.
    server = _Server((os.environ.get("OMP_HOST", "127.0.0.1"), port), Handler)
    server.daemon_threads = True
    return server


def serve_in_thread(server: ThreadingHTTPServer) -> threading.Thread:
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return t
