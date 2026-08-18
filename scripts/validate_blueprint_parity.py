"""Local blueprint-parity validator for the compute/orchestrator big/little split (#1407/#1408).

Confirms the routing surface actually works in Docker — not just that
function_registration.py's blueprint lists match in a unit test — before any
change to this contract reaches Azure. Prove it locally first; a real Azure
deploy is the expensive way to discover a routing regression.

Prerequisite: `make dev-all` running (brings up azurite, cosmos, func, orch).

Usage:
    uv run python scripts/validate_blueprint_parity.py
    uv run python scripts/validate_blueprint_parity.py --compute-base http://localhost:7071 --orch-base http://localhost:7072
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

import httpx

DEFAULT_COMPUTE_BASE = "http://localhost:7071"
DEFAULT_ORCH_BASE = "http://localhost:7072"


@dataclass(frozen=True)
class RouteCheck:
    method: str
    path: str
    # Human label for the blueprint this route belongs to.
    blueprint: str


# One representative, cheaply-reachable route per HTTP blueprint that both
# compute and orchestrator must register (#1407). Bodies are deliberately
# invalid/empty — the goal is to prove the route is *registered* (any
# response with a non-empty body, or a status other than a bare 404), not to
# exercise full business logic.
#
# Exactly one entry per distinct blueprint label — check_host() keys its
# results dict by `blueprint`, so a second entry sharing a label (e.g. an
# earlier version also checked /api/internal-health under "health") would
# silently overwrite the first result rather than adding coverage, hiding a
# real registration gap. test_covers_every_registered_http_blueprint enforces
# this stays 1:1 with function_registration._http_blueprints().
ROUTES: tuple[RouteCheck, ...] = (
    RouteCheck("GET", "/api/health", "health"),
    RouteCheck("GET", "/api/billing/status", "billing"),
    RouteCheck("POST", "/api/upload/token", "upload"),
    RouteCheck("GET", "/api/monitoring", "monitoring"),
    RouteCheck("GET", "/api/ops/dashboard", "ops"),
    RouteCheck("GET", "/api/catalogue", "catalogue"),
    RouteCheck("POST", "/api/contact-form", "contact"),
    RouteCheck("PATCH", "/api/user/profile", "account"),
    RouteCheck("GET", "/api/org", "org"),
    RouteCheck("GET", "/api/export/local-parity-check/eudr-pdf", "export"),
    RouteCheck("POST", "/api/convert-coordinates", "eudr"),
    RouteCheck("POST", "/api/eudr-assessment", "analysis"),
    # /api/orchestrator/{id} 404s with a real JSON body ({"error": "not found"})
    # for an unknown instance — a business-logic 404, not the empty-body
    # "route not registered" 404 (blueprints/pipeline/diagnostics.py).
    RouteCheck("GET", "/api/orchestrator/local-parity-check", "pipeline"),
)

# A route no blueprint defines — the baseline for "genuinely unregistered".
_CONTROL_ROUTE = RouteCheck("GET", "/api/this-route-does-not-exist", "(control)")


def _is_registered(response: httpx.Response) -> bool:
    """A registered route either isn't a 404, or is a 404 with a real body
    (application-level "not found", e.g. export's unknown instance ID) —
    Azure Functions' own unregistered-route 404 always has an empty body."""
    if response.status_code != 404:
        return True
    return bool(response.text.strip())


def check_host(client: httpx.Client, base: str, routes: tuple[RouteCheck, ...]) -> dict[str, bool]:
    """Return {blueprint: is_registered} for every route against *base*."""
    results: dict[str, bool] = {}
    for route in routes:
        try:
            resp = client.request(route.method, base + route.path, timeout=10.0)
        except httpx.TransportError as exc:
            print(f"  ERROR reaching {base}{route.path}: {exc}", file=sys.stderr)
            results[route.blueprint] = False
            continue
        results[route.blueprint] = _is_registered(resp)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compute-base", default=DEFAULT_COMPUTE_BASE)
    parser.add_argument("--orch-base", default=DEFAULT_ORCH_BASE)
    args = parser.parse_args()

    print("Blueprint parity check — compute vs orchestrator (#1407)\n")

    with httpx.Client() as client:
        control_compute = check_host(client, args.compute_base, (_CONTROL_ROUTE,))
        control_orch = check_host(client, args.orch_base, (_CONTROL_ROUTE,))
        compute_results = check_host(client, args.compute_base, ROUTES)
        orch_results = check_host(client, args.orch_base, ROUTES)

    if control_compute["(control)"] or control_orch["(control)"]:
        print(
            "WARNING: the control route (which no blueprint defines) was reported as "
            "'registered' on at least one host — the 404-body heuristic may be unreliable "
            "for this deployment; treat results below with caution.",
            file=sys.stderr,
        )

    failed = False
    print(f"{'blueprint':<12} {'compute':<10} {'orchestrator':<14} parity")
    print("-" * 50)
    for route in ROUTES:
        bp = route.blueprint
        compute_ok = compute_results[bp]
        orch_ok = orch_results[bp]
        parity = compute_ok == orch_ok
        if not (compute_ok and orch_ok and parity):
            failed = True
        status = "OK" if (compute_ok and orch_ok) else "MISMATCH"
        print(f"{bp:<12} {'yes' if compute_ok else 'NO':<10} {'yes' if orch_ok else 'NO':<14} {status}")

    print()
    if failed:
        print("FAIL — at least one blueprint is not registered on both hosts.", file=sys.stderr)
        return 1

    print("PASS — every checked blueprint is registered on both compute and orchestrator.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
