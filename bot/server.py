"""Servidor local del dashboard. Solo stdlib, escucha en 127.0.0.1."""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEB = os.path.join(os.path.dirname(__file__), "web")


def make_handler(orch):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):                                # noqa: N802
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                with open(os.path.join(WEB, "index.html"), "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            if path == "/api/state":
                body = json.dumps(orch.state(), default=str).encode()
                return self._send(200, body)
            if path == "/api/health":
                return self._send(200, json.dumps({"ok": True}).encode())
            return self._send(404, b'{"error":"not found"}')

        def log_message(self, *a):                       # silencio
            pass

    return Handler


def serve(orch, host, port):
    httpd = ThreadingHTTPServer((host, port), make_handler(orch))
    return httpd
