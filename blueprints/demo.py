"""Demo submission, valet tokens, artifact download (§4.6, §4.7).

NOTE: Do NOT add ``from __future__ import annotations`` to blueprint modules.
See blueprints/pipeline.py module docstring for details.
"""

import json
import mimetypes
import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

import azure.functions as func
import requests

from blueprints._helpers import CORS_HEADERS, EMAIL_RE, error_response, sanitise
from treesight.constants import (
    DEFAULT_INPUT_CONTAINER,
    DEFAULT_OUTPUT_CONTAINER,
    PIPELINE_PAYLOADS_CONTAINER,
)
from treesight.security.valet import mint_valet_token, verify_valet_token
from treesight.storage.client import BlobStorageClient

bp = func.Blueprint()


# --- POST /api/demo-submit ---

@bp.route(route="demo-submit", methods=["POST", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def demo_submit(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204)

    try:
        body = req.get_json()
    except ValueError:
        return error_response(400, "Invalid JSON body")

    if not isinstance(body, dict):
        return error_response(400, "Expected JSON object")

    email = sanitise(body.get("email", ""))
    if not email or not EMAIL_RE.match(email):
        return error_response(400, "Valid email is required")

    kml_content = body.get("kml_content", "")
    if not isinstance(kml_content, str) or not kml_content.strip():
        return error_response(400, "kml_content is required")

    submission_id = str(uuid.uuid4())
    kml_bytes = kml_content.encode("utf-8")
    kml_blob_name = f"demo/{submission_id}.kml"

    storage = BlobStorageClient()
    storage.upload_bytes(
        DEFAULT_INPUT_CONTAINER,
        kml_blob_name,
        kml_bytes,
        content_type="application/vnd.google-earth.kml+xml",
    )

    record = {
        "submission_id": submission_id,
        "email": email,
        "submitted_at": datetime.now(UTC).isoformat(),
        "kml_blob_name": kml_blob_name,
        "kml_size_bytes": len(kml_bytes),
        "status": "submitted",
    }
    storage.upload_json(
        PIPELINE_PAYLOADS_CONTAINER,
        f"demo-submissions/{submission_id}.json",
        record,
    )

    return func.HttpResponse(
        json.dumps({"status": "submitted", "submission_id": submission_id}),
        status_code=200,
        mimetype="application/json",
    )


# --- POST /api/demo-valet-tokens ---

@bp.route(route="demo-valet-tokens", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def demo_valet_tokens(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return error_response(400, "Invalid JSON body")

    submission_id = body.get("submission_id", "")
    recipient_email = body.get("recipient_email", "")

    if not submission_id or not recipient_email:
        return error_response(400, "submission_id and recipient_email are required")

    if not EMAIL_RE.match(recipient_email):
        return error_response(400, "Invalid recipient_email")

    # Look up submission to find artifacts
    storage = BlobStorageClient()
    submission_blob = f"demo-submissions/{submission_id}.json"

    try:
        submission = storage.download_json(PIPELINE_PAYLOADS_CONTAINER, submission_blob)
    except Exception:
        return error_response(404, "Submission not found")

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
        return error_response(400, "token parameter is required")

    try:
        claims = verify_valet_token(token)
    except ValueError as exc:
        return error_response(403, str(exc))

    artifact_path = claims.get("artifact_path", "")
    output_container = claims.get("output_container", DEFAULT_OUTPUT_CONTAINER)

    storage = BlobStorageClient()
    try:
        data = storage.download_bytes(output_container, artifact_path)
    except Exception:
        return error_response(404, "Artifact not found")

    content_type = mimetypes.guess_type(artifact_path)[0] or "application/octet-stream"

    return func.HttpResponse(
        body=data,
        status_code=200,
        mimetype=content_type,
    )


# --- GET /api/proxy (CORS proxy for external flood/fire APIs) ---

PROXY_ALLOWED_DOMAINS = [
    "environment.data.gov.uk",
    "waterdata.usgs.gov",
    "firms.modaps.eosdis.nasa.gov",
    "api.open-meteo.com",
]

PROXY_TIMEOUT_SECONDS = 10


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
        return func.HttpResponse(status_code=204, headers=CORS_HEADERS)

    target_url = req.params.get('url')

    if not target_url:
        return error_response(400, "Missing 'url' query parameter")

    try:
        parsed = urlparse(target_url)
        domain = parsed.netloc.lower()
        if not any(domain.endswith(allow) for allow in PROXY_ALLOWED_DOMAINS):
            return error_response(403, f"Domain not whitelisted: {domain}")
    except Exception as e:
        return error_response(400, f"Invalid URL: {str(e)}")

    try:
        resp = requests.get(target_url, timeout=PROXY_TIMEOUT_SECONDS)
        return func.HttpResponse(
            resp.content,
            status_code=resp.status_code,
            mimetype=resp.headers.get("Content-Type", "application/json"),
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "max-age=3600",
            }
        )
    except requests.Timeout:
        return error_response(504, "Request timeout")
    except requests.RequestException as e:
        return error_response(502, f"Upstream error: {str(e)}")
    except Exception as e:
        return error_response(500, f"Proxy error: {str(e)}")
