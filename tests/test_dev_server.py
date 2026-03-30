import http.server
import socketserver

from scripts import dev_server


def test_threading_dev_server_uses_threading_mixin():
    assert issubclass(dev_server.ThreadingDevServer, socketserver.ThreadingMixIn)
    assert issubclass(dev_server.ThreadingDevServer, http.server.HTTPServer)
    assert dev_server.ThreadingDevServer.daemon_threads is True
    assert dev_server.ThreadingDevServer.allow_reuse_address is True
