"""Shared Microsoft Graph API helper for CIAM scripts."""

import json
import os
import urllib.error
import urllib.request

TOKEN = os.environ.get("CIAM_TOKEN")

APP_ID = "6e2abd0a-61a4-41a5-bdb5-7e1c91471fc6"
TENANT_ID = "92001438-8b42-4bd7-950f-0ed1775f87b7"
TENANT_NAME = "treesightauth"
SP_ID = "1d43a846-7f56-46b3-b72b-6309c40a3bd7"
APP_OBJECT_ID = "7ce73a2a-b80a-4b6f-afb7-eccf74bfaf47"


def graph(method, path, body=None, beta=False):
    """Call Microsoft Graph API.

    Combines capabilities from all CIAM scripts: beta/v1.0 toggle,
    timeout, 204 handling, and both HTTPError and URLError handling.

    Returns parsed JSON dict, ``{"_status": 204}`` for no-content,
    or *None* on error.
    """
    base = "https://graph.microsoft.com/beta" if beta else "https://graph.microsoft.com/v1.0"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        f"{base}{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status == 204:
                return {"_status": 204}
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        print(f"ERROR {e.code} on {method} {path}:")
        try:
            print(json.dumps(json.loads(body_text), indent=2))
        except Exception:
            print(body_text)
        return None
    except urllib.error.URLError as e:
        print(f"Network error on {method} {path}: {e}")
        return None
