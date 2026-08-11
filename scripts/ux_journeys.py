"""UX smoke test: verifies key user journeys across every app surface.

Covers the marketing/host site, the EUDR app, the conservation app, the
account/settings app, the auth boundary on protected API routes, and each
persona's golden-path "empty state to ready-to-submit" journey (see
docs/USER_JOURNEYS.md). Signed-out journeys only — there's no way to
complete a real CIAM login against a local dev stack. Auth-gated pages
are checked for a clean signed-out state, which locally is the app's
auth bypass notice on every app (see AUTH_GATE_MARKERS) — a real
deployment with CIAM configured would show a genuine sign-in gate
instead. Local dev's auth bypass also fully renders the dashboard, which
is what makes the persona golden-path checks below possible without a
real sign-in.

Prerequisite: the stack must already be running (``make dev-all``).

Usage:
    uv run python scripts/ux_journeys.py
    uv run python scripts/ux_journeys.py --headed   # watch it run

Requires the "ux" extra: ``uv sync --extra ux && uv run playwright install chromium``.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

import httpx
from playwright.sync_api import ConsoleMessage, Page, Request, sync_playwright

DEFAULT_WEB_BASE = "http://localhost:4280"
DEFAULT_FUNC_BASE = "http://localhost:7071"
NAV_TIMEOUT_MS = 15_000


@dataclass(frozen=True)
class PageJourney:
    """A single page visit and what a working page should show."""

    name: str
    path: str
    expect_title_contains: str
    expect_visible_text: tuple[str, ...] = ()
    auth_gated: bool = False


@dataclass
class PageResult:
    journey: PageJourney
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass(frozen=True)
class ApiCheck:
    """A direct API call and the status code a healthy backend returns."""

    name: str
    method: str
    path: str
    expect_status: int
    base: str = "func"  # "func" or "web"


@dataclass
class ApiResult:
    check: ApiCheck
    detail: str
    ok: bool


@dataclass(frozen=True)
class PersonaJourney:
    """A persona's golden path from a fresh empty state to a ready-to-submit form.

    Doesn't drive a full pipeline run (that needs real network access to
    imagery providers and takes minutes — see scripts/e2e_local.py for the
    stubbed-provider version of that). This checks the part of the journey
    where cognitive load and clarity matter most: can the user get from
    "I just arrived" to "I'm ready to submit" in one click, with one clear
    primary action and immediate feedback? See docs/USER_JOURNEYS.md.
    """

    persona: str
    entry_path: str
    first_run_cta_id: str
    submission_anchor: str
    usage_widget_labels: tuple[str, ...]


@dataclass
class PersonaJourneyResult:
    journey: PersonaJourney
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


PERSONA_JOURNEYS: tuple[PersonaJourney, ...] = (
    # Conservation analyst and agricultural advisor share the general
    # /app/ workspace today (see docs/PERSONA_DEEP_DIVE.md § fit analysis
    # — batch/portfolio tooling that would give agriculture its own tuned
    # flow is tracked separately, not a nav/UX gap).
    PersonaJourney(
        "Conservation analyst",
        "/app/",
        "app-first-run-cta",
        "#app-analysis-card",
        ("PLAN", "RUNS LEFT"),
    ),
    PersonaJourney(
        "Agricultural advisor",
        "/app/",
        "app-first-run-cta",
        "#app-analysis-card",
        ("PLAN", "RUNS LEFT"),
    ),
    PersonaJourney(
        "ESG / EUDR compliance officer",
        "/eudr/",
        "app-first-run-cta",
        "#app-analysis-card",
        ("PLAN", "PARCELS"),
    ),
)


PAGE_JOURNEYS: tuple[PageJourney, ...] = (
    PageJourney("Marketing home", "/", "Canopex", ("Due Diligence", "Pricing")),
    PageJourney("Docs hub", "/docs/", "Documentation"),
    PageJourney("EUDR methodology", "/docs/eudr-methodology.html", "EUDR"),
    PageJourney("Terms of service", "/terms.html", "Terms"),
    PageJourney("Privacy policy", "/privacy.html", "Privacy"),
    PageJourney("EUDR app, signed out", "/eudr/", "EUDR", auth_gated=True),
    PageJourney("Conservation app, signed out", "/app/", "Dashboard", auth_gated=True),
    PageJourney("Account settings, signed out", "/account/", "Account", auth_gated=True),
)

# Verified against a real local run: /eudr/, /app/, and /account/ all
# auto-bypass to a local-dev notice when no CIAM client id is configured
# (see website/js/app-msal.js renderLocalDevUI and the account page's own
# updateAuthUI — fixed to match in #1256). A real deployment with CIAM
# configured would instead show a genuine sign-in gate — accept either.
AUTH_GATE_MARKERS: tuple[str, ...] = (
    "Sign In",
    "Sign in",
    "Local dev",  # covers both "Local dev" (nav badge) and "Local developer" (account name)
    "Auth is disabled",
)

API_CHECKS: tuple[ApiCheck, ...] = (
    ApiCheck("Functions health", "GET", "/api/health", 200),
    ApiCheck("Functions readiness", "GET", "/api/readiness", 200),
    ApiCheck("API config served", "GET", "/api-config.json", 200, base="web"),
    # REQUIRE_AUTH is unset in docker-compose.yml's func environment (local
    # dev convenience, mirrors the frontend's auth bypass) so check_auth()
    # doesn't reject anonymous callers here — the request reaches JSON body
    # parsing and fails there instead. In a real environment (REQUIRE_AUTH=1
    # or real CIAM) the same anonymous call gets 401 before this point.
    ApiCheck("analysis/submit validates request shape", "POST", "/api/analysis/submit", 400),
    ApiCheck("admin/functions rejects anonymous", "GET", "/admin/functions", 401),
)


def _is_noise(message: ConsoleMessage) -> bool:
    """Return True for console output that isn't a real UX regression.

    Local dev has no CIAM client id configured, so MSAL logs a benign
    warning on every auth-gated page and any endpoint call it attempts
    fails with 401.
    """
    if message.type != "error":
        return True
    text = message.text
    return "clientId" in text or "401" in text


def run_page_journey(page: Page, base_url: str, journey: PageJourney) -> PageResult:
    """Visit one page and check title, expected content, and console health."""
    console_errors: list[str] = []
    failed_requests: list[str] = []

    def record_console(message: ConsoleMessage) -> None:
        if not _is_noise(message):
            console_errors.append(message.text)

    def record_failed_request(request: Request) -> None:
        # Third-party tile/CDN hosts can be flaky or blocked in some
        # environments; only same-origin failures indicate an app bug.
        if request.url.startswith(base_url):
            failed_requests.append(f"{request.method} {request.url}")

    page.on("console", record_console)
    page.on("requestfailed", record_failed_request)

    problems: list[str] = []
    try:
        response = page.goto(f"{base_url}{journey.path}", wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
    except Exception as exc:  # surfaced as a journey failure, not a script crash
        return PageResult(journey=journey, problems=[f"navigation error: {exc}"])

    if response is None or not response.ok:
        problems.append(f"navigation failed: status={response.status if response else 'none'}")

    title = page.title()
    if journey.expect_title_contains not in title:
        problems.append(f"title {title!r} missing {journey.expect_title_contains!r}")

    body_text = page.locator("body").inner_text()
    for expected in journey.expect_visible_text:
        if expected not in body_text:
            problems.append(f"expected visible text not found: {expected!r}")

    if journey.auth_gated and not any(marker in body_text for marker in AUTH_GATE_MARKERS):
        problems.append("signed-out state not shown (no sign-in prompt or local-dev notice)")

    problems.extend(f"console error: {error}" for error in console_errors)
    problems.extend(f"failed request (same-origin): {request}" for request in failed_requests)
    return PageResult(journey=journey, problems=problems)


def run_persona_journey(page: Page, base_url: str, journey: PersonaJourney) -> PersonaJourneyResult:
    """Drive one persona's golden path: empty state -> one click -> ready to submit."""
    problems: list[str] = []
    try:
        page.goto(f"{base_url}{journey.entry_path}", wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
    except Exception as exc:
        return PersonaJourneyResult(journey=journey, problems=[f"navigation error: {exc}"])

    cta = page.locator(f"#{journey.first_run_cta_id}")
    if cta.count() == 0:
        problems.append("no single primary CTA in the first-run empty state")
        return PersonaJourneyResult(journey=journey, problems=problems)

    cta.click()
    page.wait_for_timeout(300)  # let the anchor scroll/reveal settle
    if journey.submission_anchor.lstrip("#") not in page.url:
        problems.append(f"first-run CTA didn't reach {journey.submission_anchor}")

    body_text = page.locator("body").inner_text()
    if "Upload KML" not in body_text:
        problems.append("submission form doesn't default to the simplest option (Upload KML)")
    if "Paste Coordinates" not in body_text:
        problems.append("no secondary paste-coordinates option for suppliers without KML")
    if page.locator('input[type="file"]').count() == 0:
        problems.append("no visible file input in the submission form")

    for label in journey.usage_widget_labels:
        if label not in body_text:
            problems.append(f"hero usage widget {label!r} not shown")

    # Usage widgets fetch async on load; give them a moment then check none
    # are still stuck on a generic placeholder (a real regression class,
    # see #1260 for the currently-known EUDR PARCELS instance of this).
    page.wait_for_timeout(2000)
    body_text = page.locator("body").inner_text()
    if "Loading usage" in body_text:
        problems.append("a usage widget is still stuck on 'Loading usage...' (see #1260)")

    return PersonaJourneyResult(journey=journey, problems=problems)


def run_api_check(client: httpx.Client, func_base: str, web_base: str, check: ApiCheck) -> ApiResult:
    """Call one API endpoint directly and compare against the expected status."""
    base = web_base if check.base == "web" else func_base
    url = f"{base}{check.path}"
    try:
        response = client.request(check.method, url, timeout=10.0)
    except httpx.HTTPError as exc:
        return ApiResult(check=check, detail=f"request error: {exc}", ok=False)
    ok = response.status_code == check.expect_status
    return ApiResult(check=check, detail=f"{response.status_code} (expected {check.expect_status})", ok=ok)


def print_report(
    page_results: list[PageResult],
    persona_results: list[PersonaJourneyResult],
    api_results: list[ApiResult],
) -> bool:
    """Print a pass/fail summary and return True if every check passed."""
    print("\n=== Page journeys ===")
    for result in page_results:
        status = "PASS" if result.ok else "FAIL"
        print(f"[{status}] {result.journey.name} ({result.journey.path})")
        for problem in result.problems:
            print(f"         - {problem}")

    print("\n=== Persona golden-path journeys (see docs/USER_JOURNEYS.md) ===")
    for result in persona_results:
        status = "PASS" if result.ok else "FAIL"
        print(f"[{status}] {result.journey.persona} ({result.journey.entry_path})")
        for problem in result.problems:
            print(f"         - {problem}")

    print("\n=== API checks ===")
    for result in api_results:
        status = "PASS" if result.ok else "FAIL"
        print(f"[{status}] {result.check.name}: {result.detail}")

    all_ok = all(r.ok for r in page_results) and all(r.ok for r in persona_results) and all(r.ok for r in api_results)
    print("\n" + ("ALL CHECKS PASSED" if all_ok else "SOME CHECKS FAILED"))
    return all_ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-base", default=DEFAULT_WEB_BASE, help="Website dev server base URL")
    parser.add_argument("--func-base", default=DEFAULT_FUNC_BASE, help="Functions host base URL")
    parser.add_argument("--headed", action="store_true", help="Show the browser while it runs")
    args = parser.parse_args()

    with httpx.Client() as client:
        api_results = [run_api_check(client, args.func_base, args.web_base, check) for check in API_CHECKS]

    page_results: list[PageResult] = []
    persona_results: list[PersonaJourneyResult] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed)
        try:
            page = browser.new_page()
            for journey in PAGE_JOURNEYS:
                page_results.append(run_page_journey(page, args.web_base, journey))
            for persona_journey in PERSONA_JOURNEYS:
                persona_results.append(run_persona_journey(page, args.web_base, persona_journey))
        finally:
            browser.close()

    passed = print_report(page_results, persona_results, api_results)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
