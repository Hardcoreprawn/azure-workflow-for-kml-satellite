"""Tests for Cosmos container document models (#583)."""

from __future__ import annotations

from treesight.models.records import (
    EnrichmentManifest,
    FramePlanEntry,
    QuotaState,
    RunRecord,
    SubscriptionRecord,
    UserRecord,
)

# ---------------------------------------------------------------------------
# RunRecord
# ---------------------------------------------------------------------------


class TestRunRecord:
    def test_minimal_construction(self):
        r = RunRecord(
            submission_id="abc",
            instance_id="abc",
            user_id="u1",
            submitted_at="2026-04-15T00:00:00Z",
        )
        assert r.submission_id == "abc"
        assert r.status == "submitted"
        assert r.eudr_mode is False
        assert r.feature_count is None
        assert r.started_at is None

    def test_full_construction(self):
        r = RunRecord(
            submission_id="abc",
            instance_id="abc",
            user_id="u1",
            submitted_at="2026-04-15T00:00:00Z",
            kml_blob_name="analysis/abc.kml",
            kml_size_bytes=1234,
            provider_name="planetary_computer",
            status="completed",
            eudr_mode=True,
            feature_count=5,
            aoi_count=5,
            max_spread_km=12.3,
            started_at="2026-04-15T00:00:01Z",
            completed_at="2026-04-15T00:05:00Z",
            duration_seconds=299.0,
        )
        assert r.eudr_mode is True
        assert r.feature_count == 5
        assert r.duration_seconds == 299.0

    def test_extra_fields_allowed(self):
        """Existing documents may have fields not yet in the model."""
        r = RunRecord(
            submission_id="x",
            instance_id="x",
            user_id="u1",
            submitted_at="2026-04-15T00:00:00Z",
            legacy_field="hello",
        )
        assert r.model_extra["legacy_field"] == "hello"

    def test_round_trip_dict(self):
        r = RunRecord(
            submission_id="abc",
            instance_id="abc",
            user_id="u1",
            submitted_at="2026-04-15T00:00:00Z",
        )
        d = r.model_dump()
        assert d["submission_id"] == "abc"
        r2 = RunRecord.model_validate(d)
        assert r2.submission_id == r.submission_id

    def test_validates_from_inline_dict(self):
        """Should parse the same shape that submission.py currently builds."""
        inline = {
            "submission_id": "abc",
            "instance_id": "abc",
            "user_id": "u1",
            "submitted_at": "2026-04-15T00:00:00Z",
            "kml_blob_name": "analysis/abc.kml",
            "kml_size_bytes": 500,
            "submission_prefix": "analysis",
            "provider_name": "planetary_computer",
            "status": "submitted",
        }
        r = RunRecord.model_validate(inline)
        assert r.status == "submitted"


# ---------------------------------------------------------------------------
# SubscriptionRecord
# ---------------------------------------------------------------------------


class TestSubscriptionRecord:
    def test_real_subscription(self):
        s = SubscriptionRecord(
            user_id="u1",
            tier="pro",
            status="active",
            updated_at="2026-04-15T00:00:00Z",
        )
        assert s.tier == "pro"
        assert s.enabled is None

    def test_emulation_variant(self):
        s = SubscriptionRecord(
            user_id="u1",
            tier="enterprise",
            status="active",
            enabled=True,
            updated_at="2026-04-15T00:00:00Z",
        )
        assert s.enabled is True

    def test_defaults_to_free(self):
        s = SubscriptionRecord(user_id="u1")
        assert s.tier == "free"
        assert s.status == "none"

    def test_extra_fields_allowed(self):
        s = SubscriptionRecord(user_id="u1", stripe_customer_id="cus_abc")
        assert s.stripe_customer_id == "cus_abc"


# ---------------------------------------------------------------------------
# UserRecord
# ---------------------------------------------------------------------------


class TestUserRecord:
    def test_minimal_construction(self):
        u = UserRecord(user_id="u1")
        assert u.billing_allowed is False
        assert u.quota is None

    def test_full_construction(self):
        u = UserRecord(
            user_id="u1",
            email="user@example.com",
            display_name="Test User",
            identity_provider="aad",
            billing_allowed=True,
            first_seen="2026-04-15T00:00:00Z",
            last_seen="2026-04-15T12:00:00Z",
            assigned_tier="pro",
            quota=QuotaState(runs_used=3, period_start="2026-04-01"),
        )
        assert u.billing_allowed is True
        assert u.quota is not None
        assert u.quota.runs_used == 3

    def test_round_trip(self):
        u = UserRecord(
            user_id="u1",
            email="test@example.com",
            quota=QuotaState(runs_used=1),
        )
        d = u.model_dump()
        u2 = UserRecord.model_validate(d)
        assert u2.quota.runs_used == 1

    def test_extra_fields_allowed(self):
        u = UserRecord(user_id="u1", unknown_field="ok")
        assert u.model_extra["unknown_field"] == "ok"

    def test_validates_from_cosmos_shape(self):
        """Should parse the shape that users.py currently builds."""
        doc = {
            "id": "u1",
            "user_id": "u1",
            "email": "j.brewster@outlook.com",
            "display_name": "James Brewster",
            "identity_provider": "aad",
            "billing_allowed": True,
            "first_seen": "2026-04-13T18:00:00+00:00",
            "last_seen": "2026-04-13T19:30:00+00:00",
        }
        u = UserRecord.model_validate(doc)
        assert u.display_name == "James Brewster"


# ---------------------------------------------------------------------------
# EnrichmentManifest
# ---------------------------------------------------------------------------


class TestEnrichmentManifest:
    def test_minimal_manifest(self):
        m = EnrichmentManifest()
        assert m.coords == []
        assert m.bbox == []
        assert m.eudr_mode is False

    def test_full_manifest(self):
        m = EnrichmentManifest(
            coords=[[1.0, 2.0], [3.0, 4.0]],
            bbox=[1.0, 2.0, 3.0, 4.0],
            center={"lat": 3.0, "lon": 2.0},
            frame_plan=[FramePlanEntry(start="2025-01-01", end="2025-03-01", label="Q1")],
            weather_daily=[{"temp": 25.0}],
            ndvi_stats=[{"mean": 0.45}],
            change_detection={"trend": "stable"},
            per_aoi_metrics=[{"name": "Farm A", "area_ha": 100.0}],
            enriched_at="2026-04-15T00:00:00Z",
            enrichment_duration_seconds=45.2,
            eudr_mode=True,
            eudr_date_start="2021-01-01",
            manifest_path="enrichment/proj/ts/timelapse_payload.json",
        )
        assert len(m.frame_plan) == 1
        assert m.eudr_mode is True
        assert m.enrichment_duration_seconds == 45.2

    def test_round_trip(self):
        m = EnrichmentManifest(
            coords=[[1.0, 2.0]],
            bbox=[1.0, 2.0, 1.0, 2.0],
            eudr_mode=True,
        )
        d = m.model_dump()
        m2 = EnrichmentManifest.model_validate(d)
        assert m2.eudr_mode is True

    def test_extra_fields_allowed(self):
        """Runner may add new fields before model is updated."""
        m = EnrichmentManifest(
            coords=[[0, 0]],
            bbox=[0, 0, 0, 0],
            fire_incidents=[],
        )
        assert m.model_extra["fire_incidents"] == []

    def test_validates_runner_output_shape(self):
        """Should parse the dict shape that run_enrichment() returns."""
        runner_output = {
            "frame_plan": [{"start": "2025-01-01", "end": "2025-03-01"}],
            "coords": [[1.0, 2.0]],
            "bbox": [1.0, 2.0, 1.0, 2.0],
            "center": {"lat": 2.0, "lon": 1.0},
            "weather_daily": [],
            "ndvi_stats": [],
            "ndvi_raster_paths": [],
            "change_detection": {},
            "enriched_at": "2026-04-15T00:00:00Z",
            "enrichment_duration_seconds": 30.5,
            "eudr_mode": True,
            "eudr_date_start": "2021-01-01",
            "manifest_path": "enrichment/test/ts/timelapse_payload.json",
        }
        m = EnrichmentManifest.model_validate(runner_output)
        assert m.manifest_path == "enrichment/test/ts/timelapse_payload.json"
