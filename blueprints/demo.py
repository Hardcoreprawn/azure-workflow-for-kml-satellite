"""Demo valet tokens, artifact download, CORS proxy (§4.6, §4.7).

NOTE: Do NOT add ``from __future__ import annotations`` to blueprint modules.
See blueprints/pipeline.py module docstring for details.
"""

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


def _is_domain_allowed(domain: str) -> bool:
    """Exact match or subdomain match against the allowlist."""
    from treesight.security.url import host_in_allowlist

    if not domain or "@" in domain:
        return False
    return host_in_allowlist(domain, PROXY_ALLOWED_DOMAINS)


@bp.route(route="proxy", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def cors_proxy(req: func.HttpRequest) -> func.HttpResponse:
    """CORS proxy for flood and fire event APIs.

    Allows browser to fetch from APIs that don't have CORS enabled.
    Usage: GET /api/proxy?url=<url-encoded-target-url>

    Supported APIs:
      - https://environment.data.gov.uk/flood-monitoring/* (UK EA floods)
      - https://waterdata.usgs.gov/nwis/* (USGS water data)
      - https://firms.modaps.eosdis.nasa.gov/* (NASA fire hotspots)
    """
    if req.method == "OPTIONS":
        return cors_preflight(req)

    if not proxy_limiter.is_allowed(get_client_ip(req)):
        return error_response(429, "Rate limit exceeded — try again later", req=req)

    target_url = req.params.get("url")

    if not target_url:
        return error_response(400, "Missing 'url' query parameter", req=req)

    try:
        parsed = urlparse(target_url)
        if parsed.scheme not in ("http", "https"):
            return error_response(400, "Only http/https URLs are allowed", req=req)
        domain = (parsed.hostname or "").lower()
        if not _is_domain_allowed(domain):
            return error_response(403, "Domain not whitelisted", req=req)
    except Exception:
        logger.warning("proxy URL validation failed url=%s", target_url, exc_info=True)
        return error_response(400, "Invalid URL", req=req)

    try:
        resp = requests.get(
            target_url,
            timeout=PROXY_TIMEOUT_SECONDS,
            allow_redirects=False,
            stream=True,
        )
        body = resp.raw.read(_PROXY_MAX_RESPONSE_BYTES + 1)
        if len(body) > _PROXY_MAX_RESPONSE_BYTES:
            return error_response(502, "Upstream response too large", req=req)
        hdrs = cors_headers(req)
        hdrs["Cache-Control"] = "max-age=3600"
        return func.HttpResponse(
            body,
            status_code=resp.status_code,
            mimetype=resp.headers.get("Content-Type", "application/json"),
            headers=hdrs,
        )
    except requests.Timeout:
        return error_response(504, "Request timeout", req=req)
    except requests.RequestException:
        return error_response(502, "Upstream request failed", req=req)
