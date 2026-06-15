"""Demo valet tokens, artifact download, CORS proxy (§4.6, §4.7).

NOTE: Do NOT add ``from __future__ import annotations`` to blueprint modules.
See blueprints/pipeline.py module docstring for details.
"""

import ipaddress
import json
import logging
import mimetypes
from urllib.parse import urlparse

import azure.functions as func
import requests

from blueprints._helpers import (
    EMAIL_RE,
    cors_headers,
    cors_preflight,
    error_response,
)
from treesight.constants import (
    DEFAULT_OUTPUT_CONTAINER,
    PIPELINE_PAYLOADS_CONTAINER,
)
from treesight.security.rate_limit import get_client_ip, proxy_limiter
from treesight.security.valet import mint_valet_token, verify_valet_token
from treesight.storage.client import BlobStorageClient

bp = func.Blueprint()

logger = logging.getLogger(__name__)


# --- POST /api/demo-valet-tokens ---


@bp.route(route="demo-valet-tokens", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def demo_valet_tokens(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return error_response(400, "Invalid JSON body", req=req)

    submission_id = body.get("submission_id", "")
    recipient_email = body.get("recipient_email", "")

    if not submission_id or not recipient_email:
        return error_response(400, "submission_id and recipient_email are required", req=req)

    if not EMAIL_RE.match(recipient_email):
        return error_response(400, "Invalid recipient_email", req=req)

    # Look up submission to find artifacts
    storage = BlobStorageClient()
    submission_blob = f"demo-submissions/{submission_id}.json"

    try:
        submission = storage.download_json(PIPELINE_PAYLOADS_CONTAINER, submission_blob)
    except Exception:
        logger.warning("demo submission lookup failed blob=%s", submission_blob, exc_info=True)
        return error_response(404, "Submission not found", req=req)

    # Mint tokens for known artifact paths
    tokens = []
    kml_blob_name = submission.get("kml_blob_name", "")
    artifact_path = f"imagery/clipped/demo/{submission_id}/"  # Example path

    token = mint_valet_token(
        submission_id=submission_id,
        submission_blob_name=kml_blob_name,
        artifact_path=artifact_path,
        recipient_email=recipient_email,
        output_container=DEFAULT_OUTPUT_CONTAINER,
    )
    tokens.append({"artifact_path": artifact_path, "token": token})

    return func.HttpResponse(
        json.dumps({"tokens": tokens}),
        status_code=200,
        mimetype="application/json",
    )


# --- GET /api/demo-artifacts?token=... ---


@bp.route(route="demo-artifacts", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def demo_artifacts(req: func.HttpRequest) -> func.HttpResponse:
    token = req.params.get("token", "")
    if not token:
        return error_response(400, "token parameter is required", req=req)

    try:
        claims = verify_valet_token(token)
    except ValueError as exc:
        return error_response(403, str(exc), req=req)

    artifact_path = claims.get("artifact_path", "")
    output_container = claims.get("output_container", DEFAULT_OUTPUT_CONTAINER)

    storage = BlobStorageClient()
    try:
        data = storage.download_bytes(output_container, artifact_path)
    except Exception:
        logger.warning("demo artifact download failed path=%s", artifact_path, exc_info=True)
        return error_response(404, "Artifact not found", req=req)

    content_type = mimetypes.guess_type(artifact_path)[0] or "application/octet-stream"

    return func.HttpResponse(
        body=data,
        status_code=200,
        mimetype=content_type,
        headers=cors_headers(req),
    )


# --- GET /api/proxy (CORS proxy for external flood/fire APIs) ---

PROXY_ALLOWED_DOMAINS = frozenset(
    {
        "environment.data.gov.uk",
        "waterdata.usgs.gov",
        "firms.modaps.eosdis.nasa.gov",
        "api.open-meteo.com",
    }
)

PROXY_TIMEOUT_SECONDS = 10
_PROXY_MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MiB

# Upstream response content-types that may be proxied.  Any other type
# (binary blobs, HTML, XML, multipart…) is rejected to limit exfiltration
# risk if an allowlisted host is compromised or misconfigured.
_PROXY_ALLOWED_CONTENT_TYPE_PREFIXES = (
    "application/json",
    "application/geo+json",
    "application/vnd.geo+json",
    "text/plain",
    "text/csv",
    "image/",  # catalogue thumbnails
)

# Private / reserved address blocks that must never be proxied regardless
# of what the domain allowlist says (IMDS, loopback, RFC-1918, link-local).
_PRIVATE_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / Azure IMDS
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("0.0.0.0/8"),
)


def _is_private_address(host: str) -> bool:
    """Return True if *host* is a private, loopback, or link-local address.

    Only applies to literal IP addresses; hostnames are handled by the
    domain allowlist.  Returns False (not private) for non-IP strings so
    that normal domain names pass through to the allowlist check.
    """
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in _PRIVATE_NETWORKS)


def _is_domain_allowed(domain: str) -> bool:
    """Exact match or subdomain match against the allowlist."""
    from treesight.security.url import host_in_allowlist

    if not domain or "@" in domain:
        return False
    return host_in_allowlist(domain, PROXY_ALLOWED_DOMAINS)


def _content_type_allowed(content_type: str) -> bool:
    """Return True if *content_type* matches the proxy response allowlist.

    Strips charset and other parameters before comparing so that
    ``application/json; charset=utf-8`` is handled correctly.
    """
    base = content_type.split(";", 1)[0].strip().lower()
    return any(base.startswith(prefix) for prefix in _PROXY_ALLOWED_CONTENT_TYPE_PREFIXES)


def _validate_proxy_url(target_url: str) -> tuple[str | None, func.HttpResponse | None]:
    """Parse and validate *target_url* for proxy safety.

    Returns ``(validated_url, None)`` on success or ``(None, error_response)``
    when the URL must be rejected.  Raises nothing — caller catches any
    unexpected ``Exception`` from ``urlparse``.
    """
    parsed = urlparse(target_url)

    # Enforce https-only to prevent plaintext leakage over http.
    if parsed.scheme != "https":
        return None, error_response(400, "Only https URLs are allowed")

    # Reject userinfo (user:pass@host) — urlparse strips it from
    # .hostname, so it would otherwise bypass the allowlist check.
    if parsed.username is not None:
        return None, error_response(400, "Userinfo in URL is not allowed")

    hostname = (parsed.hostname or "").lower()

    # Explicit IMDS / private-address block — belt-and-suspenders so
    # that a future, more permissive allowlist cannot accidentally
    # expose internal metadata endpoints.
    if hostname in ("localhost",) or _is_private_address(hostname):
        return None, error_response(403, "Private or reserved addresses are not allowed")

    if not _is_domain_allowed(hostname):
        return None, error_response(403, "Domain not in allowlist")

    return target_url, None


def _fetch_upstream(target_url: str, req: func.HttpRequest) -> func.HttpResponse:
    """Fetch *target_url* and return a validated proxied response."""
    resp = requests.get(
        target_url,
        timeout=PROXY_TIMEOUT_SECONDS,
        allow_redirects=False,
        stream=True,
    )
    try:
        body = resp.raw.read(_PROXY_MAX_RESPONSE_BYTES + 1)
    finally:
        resp.close()

    if len(body) > _PROXY_MAX_RESPONSE_BYTES:
        return error_response(502, "Upstream response exceeds 5 MiB limit", req=req)

    upstream_ct = resp.headers.get("Content-Type", "")
    if not _content_type_allowed(upstream_ct):
        return error_response(
            502,
            "Upstream content-type not allowed (must be JSON, CSV, plain text, or image)",
            req=req,
        )

    hdrs = cors_headers(req)
    hdrs["Cache-Control"] = "max-age=3600"
    return func.HttpResponse(
        body,
        status_code=resp.status_code,
        mimetype=upstream_ct or "application/json",
        headers=hdrs,
    )


@bp.route(route="proxy", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def cors_proxy(req: func.HttpRequest) -> func.HttpResponse:
    """CORS proxy for flood and fire event APIs.

    Allows browser to fetch from APIs that don't have CORS enabled.
    Usage: GET /api/proxy?url=<url-encoded-target-url>

    Supported APIs:
      - https://environment.data.gov.uk/flood-monitoring/* (UK EA floods)
      - https://waterdata.usgs.gov/nwis/* (USGS water data)
      - https://firms.modaps.eosdis.nasa.gov/* (NASA fire hotspots)

    Security controls
    -----------------
    * https-only scheme
    * No userinfo (user@host) in URL — prevents allowlist bypass
    * Explicit block of IMDS and all private/link-local IP ranges
    * Strict domain allowlist (exact + subdomain match)
    * Upstream response content-type restricted to known-safe types
    * Upstream response body capped at 5 MiB
    * No redirects followed
    * Rate-limited per client IP
    """
    if req.method == "OPTIONS":
        return cors_preflight(req)

    if not proxy_limiter.is_allowed(get_client_ip(req)):
        return error_response(429, "Rate limit exceeded — try again later", req=req)

    target_url = req.params.get("url")
    if not target_url:
        return error_response(400, "Missing 'url' query parameter", req=req)

    try:
        _url, err = _validate_proxy_url(target_url)
    except Exception:
        logger.warning("proxy URL validation failed url=%s", target_url, exc_info=True)
        return error_response(400, "Invalid URL", req=req)
    if err is not None:
        return err

    try:
        return _fetch_upstream(target_url, req)
    except requests.Timeout:
        return error_response(504, "Request timeout", req=req)
    except requests.RequestException:
        return error_response(502, "Upstream request failed", req=req)
