"""Local dev server: serves website/ and reverse-proxies /api/* to func host.

Provides same-origin browsing so the website JavaScript can use relative
``/api/...`` paths exactly as in production.

Usage: uv run python scripts/dev_server.py [--port 4280] [--func-port 7071]
"""

from __future__ import annotations

import argparse
import http.server
import os
import posixpath
import socketserver
import urllib.error
import urllib.request
from urllib.parse import unquote, urlparse, urlunparse


class DevProxyHandler(http.server.SimpleHTTPRequestHandler):
    """Serves static files from website/ and proxies /api/* to the func host."""

    func_origin: str = "http://localhost:7071"

    def end_headers(self) -> None:
        # Disable caching in dev so file edits are picked up immediately
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        super().end_headers()

    def do_GET(self) -> None:
        if self.path.startswith("/api/"):
            self._proxy()
        else:
            super().do_GET()

    def do_POST(self) -> None:
        if self.path.startswith("/api/"):
            self._proxy()
        else:
            self.send_error(405)

    def do_OPTIONS(self) -> None:
        if self.path.startswith("/api/"):
            self._proxy()
        else:
            self.send_response(204)
            self._cors_headers()
            self.end_headers()

    # --- proxy logic ---

    def _proxy(self) -> None:
        # Validate and normalise the path to prevent host/scheme or traversal
        parsed = urlparse(self.path)
        if parsed.scheme or parsed.netloc:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self._cors_headers()
            self.end_headers()
            self.wfile.write(b'{"error":"Invalid path"}')
            return

        # Normalise the path and ensure it stays under /api/
        raw_path = parsed.path or "/"
        normalised = posixpath.normpath(unquote(raw_path))
        if not normalised.startswith("/"):
            normalised = "/" + normalised

        if not (normalised.startswith("/api/") or normalised == "/api"):
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self._cors_headers()
            self.end_headers()
            self.wfile.write(b'{"error":"Invalid API path"}')
            return

        safe_suffix = urlunparse(("", "", normalised, "", parsed.query, parsed.fragment))
        target = f"{self.func_origin}{safe_suffix}"

        # Read request body (for POST)
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else None

        request = urllib.request.Request(target, data=body, method=self.command)

        # Forward relevant headers
        for header in ("Content-Type", "Accept", "Authorization"):
            val = self.headers.get(header)
            if val:
                request.add_header(header, val)

        # Build an opener that refuses redirects — prevents a compromised
        # func host from bouncing us to internal/external endpoints.
        opener = urllib.request.build_opener()
        opener.handlers = [
            h for h in opener.handlers if not isinstance(h, urllib.request.HTTPRedirectHandler)
        ]

        try:
            # Use extended timeout for AI analysis endpoints (can take 100+ seconds)
            timeout = 180.0 if "/timelapse-analysis" in normalised else 60.0
            with opener.open(request, timeout=timeout) as resp:
                resp_body = resp.read()
                self.send_response(resp.status)
                for key, val in resp.getheaders():
                    if key.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(key, val)
                self._cors_headers()
                self.end_headers()
                self.wfile.write(resp_body)
        except urllib.error.HTTPError as e:
            resp_body = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", e.headers.get("Content-Type", "application/json"))
            self._cors_headers()
            self.end_headers()
            self.wfile.write(resp_body)
        except (urllib.error.URLError, ConnectionRefusedError):
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self._cors_headers()
            self.end_headers()
            msg = b'{"error":"Function host not reachable at '
            self.wfile.write(msg + self.func_origin.encode() + b'"}')

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def log_message(self, format: str, *args: object) -> None:
        path = args[0] if args else ""
        tag = "PROXY" if isinstance(path, str) and "/api/" in path else "STATIC"
        super().log_message(f"[{tag}] {format}", *args)


class ThreadingDevServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> None:
    parser = argparse.ArgumentParser(description="TreeSight local dev server")
    parser.add_argument("--port", type=int, default=4280, help="Dev server port (default: 4280)")
    parser.add_argument(
        "--func-port",
        type=int,
        default=7071,
        help="Func host port (default: 7071)",
    )
    parser.add_argument(
        "--func-host",
        default="localhost",
        help="Func host hostname (default: localhost)",
    )
    args = parser.parse_args()

    DevProxyHandler.func_origin = f"http://{args.func_host}:{args.func_port}"

    # Serve from website/ directory
    web_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "website")
    os.chdir(web_dir)

    server = ThreadingDevServer(("0.0.0.0", args.port), DevProxyHandler)
    print(f"TreeSight dev server on http://localhost:{args.port}")
    print(f"  Static files: {web_dir}")
    print(f"  API proxy:    /api/* -> {DevProxyHandler.func_origin}")
    print("  Press Ctrl+C to stop\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dev server.")
        server.shutdown()


if __name__ == "__main__":
    main()
