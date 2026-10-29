"""Fail-closed HTTP role matrix (the historical command name is retained).

Checks every indexed application route/method against both running hosts.
This does not assert removal of platform /admin or /runtime/webhooks surfaces,
nor prove Azure network isolation. Use fresh image indexing as a separate gate.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import httpx

DEFAULT_COMPUTE_BASE = "http://localhost:7071"
DEFAULT_ORCH_BASE = "http://localhost:7072"
CONTRACT_PATH = Path(__file__).resolve().parents[1] / "tests/fixtures/function_role_surface.json"
WORKER_PATHS = frozenset({"/api/health", "/api/readiness"})
# Exercise internal-smoke's existing hostname guard without changing the app.
# The same Host header is used for controls and both roles; this is local proof only.
LOCAL_SMOKE_HOST = "func-kmlsat-dev-orch.local.azurecontainerapps.io"


class RouteState(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    ERROR = "error"


@dataclass(frozen=True)
class RouteCheck:
    method: str
    path: str

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"


def contract_routes() -> tuple[RouteCheck, ...]:
    contract = json.loads(CONTRACT_PATH.read_text())["orchestrator"]
    routes = []
    for bindings in contract.values():
        for binding in bindings:
            if binding["type"] != "httpTrigger":
                continue
            path = binding["route"].replace("{format}", "eudr-pdf").replace("{aoi_index}", "0")
            path = re.sub(r"\{[^}]+\}", "role-boundary-missing", path)
            routes.extend(RouteCheck(method, f"/api/{path}") for method in binding["methods"])
    return tuple(sorted(routes, key=lambda route: route.key))


ROUTES = contract_routes()
CONTROLS = tuple(
    RouteCheck(method, "/api/this-route-does-not-exist") for method in sorted({route.method for route in ROUTES})
)


def check_host(client: httpx.Client, base: str, routes: tuple[RouteCheck, ...]) -> dict[str, RouteState]:
    """Transport and ambiguous responses are errors, never evidence of absence."""
    results = {}
    for route in routes:
        mutating = route.method not in {"GET", "OPTIONS"}
        try:
            response = client.request(
                route.method,
                base.rstrip("/") + route.path,
                # Missing bearer credentials fail parsing even with REQUIRE_AUTH=false.
                # Public form/webhook handlers reject invalid JSON before domain writes.
                headers={
                    "Host": LOCAL_SMOKE_HOST,
                    "Authorization": "Bearer",
                    "X-MS-CLIENT-PRINCIPAL": "",
                    "Content-Type": "application/json",
                },
                content=b"{" if mutating else None,
                auth=None,
                timeout=10.0,
                follow_redirects=False,
            )
        except httpx.TransportError as exc:
            print(f"ERROR {base} {route.key}: {type(exc).__name__}", file=sys.stderr)
            results[route.key] = RouteState.ERROR
            continue
        if (
            route.key == "POST /api/billing/webhook"
            and response.status_code == 503
            and response.content == b"Billing not configured"
        ):
            # This exact application response proves the route without live Stripe credentials.
            state = RouteState.PRESENT
        elif (
            response.status_code == 405
            or 300 <= response.status_code < 400
            or response.status_code >= 500
            or (mutating and 200 <= response.status_code < 300)
        ):
            state = RouteState.ERROR
        elif response.status_code == 404 and not response.content:
            state = RouteState.ABSENT
        elif route.path in WORKER_PATHS and route.method == "GET" and response.status_code != 200:
            state = RouteState.ERROR
        else:
            state = RouteState.PRESENT
        results[route.key] = state
    return results


def validate_hosts(client: httpx.Client, compute_base: str, orch_base: str) -> bool:
    """Require valid negative controls and positive probes before route assertions."""
    for base in (compute_base, orch_base):
        controls = check_host(client, base, CONTROLS)
        if any(state != RouteState.ABSENT for state in controls.values()):
            print(f"FAIL invalid unknown-route controls on {base}: {controls}", file=sys.stderr)
            return False
    passed = True
    for label, base in (("compute", compute_base), ("orchestrator", orch_base)):
        results = check_host(client, base, ROUTES)
        for route in ROUTES:
            expected = RouteState.PRESENT
            if label == "compute" and route.path not in WORKER_PATHS:
                expected = RouteState.ABSENT
            actual = results[route.key]
            ok = actual == expected
            passed = passed and ok
            print(f"{'PASS' if ok else 'FAIL'} {label} {route.key}: {actual} (expected {expected})")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compute-base", default=DEFAULT_COMPUTE_BASE)
    parser.add_argument("--orch-base", default=DEFAULT_ORCH_BASE)
    args = parser.parse_args()
    with httpx.Client() as client:
        return 0 if validate_hosts(client, args.compute_base, args.orch_base) else 1


if __name__ == "__main__":
    raise SystemExit(main())
