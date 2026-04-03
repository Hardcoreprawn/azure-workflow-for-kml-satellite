"""Contact form endpoint (§4.5).

NOTE: Do NOT add ``from __future__ import annotations`` to blueprint modules.
See blueprints/pipeline.py module docstring for details.
"""

import azure.functions as func

from blueprints._helpers import cors_preflight, error_response, sanitise, submit_contact

bp = func.Blueprint()


@bp.route(route="contact-form", methods=["POST", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def contact_form(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return cors_preflight(req)

    try:
        body = req.get_json()
    except ValueError:
        return error_response(400, "Invalid JSON body", req=req)

    extra = {
        "use_case": sanitise(body.get("use_case", "")) if isinstance(body, dict) else "",
        "ip_forwarded_for": req.headers.get("X-Forwarded-For", ""),
    }

    return submit_contact(req, body, source="marketing_website", extra_fields=extra)
