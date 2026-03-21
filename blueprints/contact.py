"""Contact form endpoint (§4.5).

NOTE: Do NOT add ``from __future__ import annotations`` to blueprint modules.
See blueprints/pipeline.py module docstring for details.
"""

import json
import uuid
from datetime import UTC, datetime

import azure.functions as func

from blueprints._helpers import EMAIL_RE, error_response, sanitise
from treesight.constants import PIPELINE_PAYLOADS_CONTAINER
from treesight.storage.client import BlobStorageClient

bp = func.Blueprint()


@bp.route(route="contact-form", methods=["POST", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def contact_form(req: func.HttpRequest) -> func.HttpResponse:
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

    organization = sanitise(body.get("organization", ""))
    use_case = sanitise(body.get("use_case", ""))

    submission_id = str(uuid.uuid4())
    record = {
        "submission_id": submission_id,
        "email": email,
        "organization": organization,
        "use_case": use_case,
        "submitted_at": datetime.now(UTC).isoformat(),
        "source": "marketing_website",
        "ip_forwarded_for": req.headers.get("X-Forwarded-For", ""),
    }

    storage = BlobStorageClient()
    storage.upload_json(
        PIPELINE_PAYLOADS_CONTAINER,
        f"contact-submissions/{submission_id}.json",
        record,
    )

    return func.HttpResponse(
        json.dumps({"status": "received", "submission_id": submission_id}),
        status_code=200,
        mimetype="application/json",
    )
