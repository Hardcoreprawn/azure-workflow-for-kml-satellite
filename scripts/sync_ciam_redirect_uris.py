"""Sync CIAM app registration redirect URIs with the current SWA hostname.

Ensures the CIAM app registration always has the correct redirect URIs
for the deployed Static Web App, preventing AADSTS50011 errors when the
SWA hostname changes after infrastructure recreation.

Usage:
  # In the deploy workflow (OIDC — no secrets needed):
  python scripts/sync_ciam_redirect_uris.py green-moss-0e849ac03.2.azurestaticapps.net

  # With a manual token:
  CIAM_TOKEN=<token> python scripts/sync_ciam_redirect_uris.py green-moss-...

Token resolution order:
  1. CIAM_TOKEN env var (manual / legacy)
  2. `az account get-access-token` against the CIAM tenant (OIDC in CI)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

# ── CIAM app registration constants (from _graph.py) ──
APP_OBJECT_ID = "7ce73a2a-b80a-4b6f-afb7-eccf74bfaf47"
TENANT_ID = "92001438-8b42-4bd7-950f-0ed1775f87b7"

# Redirect URIs that are always present regardless of SWA hostname
PERMANENT_REDIRECT_URIS: list[str] = [
    "http://localhost:4280",
]

# Custom domain redirect URIs (added when configured)
CUSTOM_DOMAIN_URIS: list[str] = [
    "https://canopex.hrdcrprwn.com",
]


def graph_api(method: str, path: str, body: dict | None = None, token: str = "") -> dict | None:
    """Call Microsoft Graph API v1.0."""
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        f"https://graph.microsoft.com/v1.0{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
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


def get_current_redirect_uris(token: str) -> list[str] | None:
    """Fetch the current SPA redirect URIs from the app registration."""
    result = graph_api("GET", f"/applications/{APP_OBJECT_ID}?$select=spa", token=token)
    if result is None:
        return None
    return result.get("spa", {}).get("redirectUris", [])


def build_desired_uris(swa_hostname: str, custom_domain: str = "") -> list[str]:
    """Build the desired redirect URI list from the SWA hostname."""
    uris = list(PERMANENT_REDIRECT_URIS)
    uris.append(f"https://{swa_hostname}")
    if custom_domain:
        uris.append(f"https://{custom_domain}")
    else:
        uris.extend(CUSTOM_DOMAIN_URIS)
    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for u in uris:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
    return deduped


def sync_redirect_uris(
    token: str, swa_hostname: str, custom_domain: str = "", dry_run: bool = False
) -> bool:
    """Sync CIAM redirect URIs. Returns True if update was applied or not needed."""
    current = get_current_redirect_uris(token)
    if current is None:
        print("Failed to fetch current redirect URIs")
        return False

    desired = build_desired_uris(swa_hostname, custom_domain)

    if set(current) == set(desired):
        print("Redirect URIs already up to date:")
        for u in current:
            print(f"  {u}")
        return True

    print("Current redirect URIs:")
    for u in current:
        print(f"  {u}")
    print("Desired redirect URIs:")
    for u in desired:
        marker = " (new)" if u not in current else ""
        print(f"  {u}{marker}")

    removed = set(current) - set(desired)
    if removed:
        print("Will remove:")
        for u in removed:
            print(f"  {u}")

    if dry_run:
        print("Dry run — no changes applied")
        return True

    result = graph_api(
        "PATCH",
        f"/applications/{APP_OBJECT_ID}",
        body={"spa": {"redirectUris": desired}},
        token=token,
    )
    if result is None:
        print("Failed to update redirect URIs")
        return False

    print("Redirect URIs updated successfully")
    return True


def _acquire_token() -> str:
    """Resolve a Graph API bearer token.

    Checks CIAM_TOKEN env var first, then falls back to `az account
    get-access-token` against the CIAM tenant (works with OIDC in CI).
    """
    token = os.environ.get("CIAM_TOKEN", "")
    if token:
        return token

    # Try az CLI — the workflow logs in to the CIAM tenant before calling this
    try:
        result = subprocess.run(
            [
                "az",
                "account",
                "get-access-token",
                "--tenant",
                TENANT_ID,
                "--resource",
                "https://graph.microsoft.com",
                "--query",
                "accessToken",
                "--output",
                "tsv",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            print("Acquired Graph token via az CLI (OIDC)")
            return result.stdout.strip()
    except FileNotFoundError:
        pass  # az CLI not installed
    except subprocess.TimeoutExpired:
        pass  # az CLI unresponsive — fall through to return empty

    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync CIAM redirect URIs with SWA hostname")
    parser.add_argument(
        "swa_hostname",
        nargs="?",
        help="SWA default hostname (e.g. green-moss-0e849ac03.2.azurestaticapps.net)",
    )
    parser.add_argument("--custom-domain", default="", help="Custom domain if configured")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without applying")
    args = parser.parse_args()

    token = _acquire_token()
    if not token:
        print("ERROR: No Graph API token available.")
        print(
            "  Set CIAM_TOKEN env var, or ensure `az login` has been run against the CIAM tenant."
        )
        return 1

    swa_hostname = args.swa_hostname or os.environ.get("SWA_HOSTNAME", "")
    if not swa_hostname:
        print("ERROR: Provide SWA hostname as argument or set SWA_HOSTNAME env var")
        return 1

    # Strip protocol if accidentally included
    swa_hostname = swa_hostname.removeprefix("https://").removeprefix("http://")

    ok = sync_redirect_uris(token, swa_hostname, args.custom_domain, args.dry_run)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
