from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_EUDR_JS = ROOT / "website" / "js" / "app-eudr.js"
APP_PREFLIGHT_JS = ROOT / "website" / "js" / "app-analysis-preflight.js"
APP_SHELL_JS = ROOT / "website" / "js" / "app-shell.js"

_NODE = shutil.which("node")
_SKIP_NO_NODE = pytest.mark.skipif(_NODE is None, reason="node runtime required")


def _compute_eudr_cost_estimate(parcel_count: int, billing: dict | None) -> str:
    if _NODE is None:
        pytest.skip("node runtime required for frontend estimator regression tests")
    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(APP_EUDR_JS))}, 'utf8');
const context = {{
  window: {{}},
  document: {{ getElementById: () => null }},
  console,
}};
vm.createContext(context);
vm.runInContext(source, context);
const profile = {{ enableParcelCostEstimate: true }};
const billing = {json.dumps(billing)};
const result = context.window.CanopexEudr.computeCostEstimate({parcel_count}, profile, billing);
process.stdout.write(JSON.stringify(result));
"""
    proc = subprocess.run(
        [_NODE, "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout)


class TestEudrCostEstimate:
    def test_fully_included_submission(self) -> None:
        result = _compute_eudr_cost_estimate(
            parcel_count=6,
            billing={"subscribed": True, "period_parcels_used": 4, "included_parcels": 10},
        )
        assert result == "Included in your plan (0 remaining after this run)"

    def test_included_edge_exact_fills_quota(self) -> None:
        # Submitting exactly as many parcels as remain in quota → 0 remaining
        result = _compute_eudr_cost_estimate(
            parcel_count=10,
            billing={"subscribed": True, "period_parcels_used": 0, "included_parcels": 10},
        )
        assert result == "Included in your plan (0 remaining after this run)"

    def test_submission_partially_exceeds_included_quota(self) -> None:
        result = _compute_eudr_cost_estimate(
            parcel_count=8,
            billing={"subscribed": True, "period_parcels_used": 6, "included_parcels": 10},
        )
        assert result == "£12 estimated overage (4 × £3/parcel)"

    def test_submission_crosses_100_parcel_threshold(self) -> None:
        result = _compute_eudr_cost_estimate(
            parcel_count=20,
            billing={"subscribed": True, "period_parcels_used": 96, "included_parcels": 10},
        )
        assert result == "£52 estimated overage (20 × £2.60 avg/parcel)"

    def test_submission_99_to_101_crosses_first_threshold(self) -> None:
        # used=99, submit 2 → parcel 100 at £3, parcel 101 at £2.50 → £5.50
        result = _compute_eudr_cost_estimate(
            parcel_count=2,
            billing={"subscribed": True, "period_parcels_used": 99, "included_parcels": 10},
        )
        assert result == "£5.50 estimated overage (2 × £2.75 avg/parcel)"

    def test_submission_crosses_500_parcel_threshold(self) -> None:
        result = _compute_eudr_cost_estimate(
            parcel_count=20,
            billing={"subscribed": True, "period_parcels_used": 495, "included_parcels": 10},
        )
        assert result == "£39.50 estimated overage (20 × £1.98 avg/parcel)"

    def test_submission_490_to_510_crosses_second_threshold(self) -> None:
        # used=490, submit 20 → 10 at £2.50 (491-500) + 10 at £1.80 (501-510) → £25+£18=£43
        result = _compute_eudr_cost_estimate(
            parcel_count=20,
            billing={"subscribed": True, "period_parcels_used": 490, "included_parcels": 10},
        )
        assert result == "£43 estimated overage (20 × £2.15 avg/parcel)"

    def test_already_above_100_threshold(self) -> None:
        result = _compute_eudr_cost_estimate(
            parcel_count=3,
            billing={"subscribed": True, "period_parcels_used": 140, "included_parcels": 10},
        )
        assert result == "£7.50 estimated overage (3 × £2.50/parcel)"

    def test_already_above_500_threshold(self) -> None:
        result = _compute_eudr_cost_estimate(
            parcel_count=3,
            billing={"subscribed": True, "period_parcels_used": 520, "included_parcels": 10},
        )
        assert result == "£5.40 estimated overage (3 × £1.80/parcel)"

    def test_free_or_unsubscribed_state(self) -> None:
        trial_remaining = _compute_eudr_cost_estimate(
            parcel_count=1,
            billing={"subscribed": False, "trial_remaining": 1},
        )
        assert trial_remaining == "1 parcel · 1 free assessment left"

        exhausted = _compute_eudr_cost_estimate(
            parcel_count=1,
            billing={"subscribed": False, "trial_remaining": 0},
        )
        assert exhausted == "Subscribe to continue"

    def test_canceled_subscription_shows_subscribe_prompt(self) -> None:
        # A canceled subscription: subscribed=False, no trial_remaining
        result = _compute_eudr_cost_estimate(
            parcel_count=5,
            billing={"subscribed": False, "trial_remaining": 0},
        )
        assert result == "Subscribe to continue"

    def test_missing_billing_snapshot_hides_estimate(self) -> None:
        result = _compute_eudr_cost_estimate(parcel_count=4, billing=None)
        assert result == "—"


class TestPreflightEstimatorIntegration:
    def test_preflight_delegates_estimator_to_canopex_eudr_module(self) -> None:
        preflight_content = APP_PREFLIGHT_JS.read_text()
        shell_content = APP_SHELL_JS.read_text()
        assert "computeEudrCostEstimate: eudrModule.computeCostEstimate" in shell_content
        assert "period_parcels_used" not in preflight_content
        assert "included_parcels" not in preflight_content
