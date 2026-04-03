import http.server
import io
import socketserver

from scripts import dev_server


def test_threading_dev_server_uses_threading_mixin():
    assert issubclass(dev_server.ThreadingDevServer, socketserver.ThreadingMixIn)
    assert issubclass(dev_server.ThreadingDevServer, http.server.HTTPServer)
    assert dev_server.ThreadingDevServer.daemon_threads is True
    assert dev_server.ThreadingDevServer.allow_reuse_address is True


class _FakeHandler(dev_server.DevProxyHandler):
    """Testable handler that captures responses without real sockets."""

    def __init__(self):
        self.headers = {}
        self._response_code = None
        self._response_headers = {}
        self._response_body = b""
        self.wfile = io.BytesIO()
        self.requestline = ""
        self.client_address = ("127.0.0.1", 0)
        self.command = "GET"

    def send_response(self, code, message=None):
        self._response_code = code

    def send_header(self, key, value):
        self._response_headers[key] = value

    def end_headers(self):
        pass


def test_path_normalisation_rejects_traversal():
    """Paths with .. that escape /api/ are rejected."""
    handler = _FakeHandler()
    handler.path = "/api/../../etc/passwd"
    handler._proxy()
    assert handler._response_code == 400


def test_path_normalisation_rejects_scheme():
    """Paths with scheme or netloc are rejected (SSRF prevention)."""
    handler = _FakeHandler()
    handler.path = "http://evil.com/api/test"
    handler._proxy()
    assert handler._response_code == 400


def test_cors_headers_set():
    """_cors_headers sets the required CORS headers."""
    handler = _FakeHandler()
    handler._cors_headers()
    assert handler._response_headers["Access-Control-Allow-Origin"] == "*"
    assert "GET" in handler._response_headers["Access-Control-Allow-Methods"]
    assert "Authorization" in handler._response_headers["Access-Control-Allow-Headers"]
