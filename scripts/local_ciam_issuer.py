"""Local-only OIDC issuer for the authenticated API verifier."""

from __future__ import annotations

import base64
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_key_id = "local-verifier-rs256"


def _authority() -> str:
    return os.environ.get("LOCAL_CIAM_AUTHORITY", "http://local-ciam:8080").rstrip("/")


def _tenant_id() -> str:
    return os.environ.get("LOCAL_CIAM_TENANT_ID", "local-dev-tenant")


def _audience() -> str:
    return os.environ.get("LOCAL_CIAM_API_AUDIENCE", "api://local-dev-audience")


def _issuer() -> str:
    return f"{_authority()}/{_tenant_id()}/v2.0"


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _int_to_b64url(value: int) -> str:
    width = (value.bit_length() + 7) // 8
    return _b64url(value.to_bytes(width, "big"))


def _metadata_document() -> dict[str, str]:
    return {
        "issuer": _issuer(),
        "jwks_uri": f"{_authority()}/jwks",
    }


def _jwks_document() -> dict[str, list[dict[str, str]]]:
    public_numbers = _private_key.public_key().public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": _key_id,
                "n": _int_to_b64url(public_numbers.n),
                "e": _int_to_b64url(public_numbers.e),
            }
        ]
    }


def _mint_token(oid: str, email: str) -> str:
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT", "kid": _key_id}
    claims: dict[str, Any] = {
        "tid": _tenant_id(),
        "oid": oid,
        "ver": "2.0",
        "iss": _issuer(),
        "aud": _audience(),
        "nbf": now - 5,
        "exp": now + 900,
        "scp": "User.Read",
        "preferred_username": email,
    }
    encoded_header = _b64url(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    encoded_claims = _b64url(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
    signature = _private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{encoded_header}.{encoded_claims}.{_b64url(signature)}"


def _tokens() -> dict[str, str]:
    return {
        "owner": _mint_token("local-verifier-owner", "owner@local.invalid"),
        "wrong_user": _mint_token("local-verifier-wrong-user", "unassigned@local.invalid"),
        "wrong_org": _mint_token("local-verifier-wrong-org", "wrong-org@local.invalid"),
    }


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        discovery_path = f"/{_tenant_id()}/v2.0/.well-known/openid-configuration"
        if path == "/health":
            self._send_json(200, {"status": "ok"})
        elif path == discovery_path:
            self._send_json(200, _metadata_document())
        elif path == "/jwks":
            self._send_json(200, _jwks_document())
        elif path == "/tokens":
            self._send_json(200, _tokens())
        else:
            self._send_json(404, {"error": "not_found"})

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"local-ciam {self.address_string()} {format % args}")


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 8080), _Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
