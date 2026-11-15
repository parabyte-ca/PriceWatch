"""Tiny HTTP server for the smoke test: serves product fixtures and records notification POSTs."""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "/fixtures")
RECEIVED: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/received":
            return self._send(200, json.dumps(RECEIVED).encode(), "application/json")
        path = (ROOT / self.path.lstrip("/").split("?")[0]).resolve()
        if ROOT.resolve() in path.parents and path.is_file():
            return self._send(200, path.read_bytes())
        return self._send(404, b"not found")

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode(errors="replace")
        try:
            RECEIVED.append(json.loads(raw))
        except json.JSONDecodeError:
            RECEIVED.append({"raw": raw})
        return self._send(200, b"{}", "application/json")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
