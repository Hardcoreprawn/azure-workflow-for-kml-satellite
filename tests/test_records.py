"""Tests for Cosmos container document models (#583)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from treesight.models.enrichment_manifest import (
    ENRICHMENT_MANIFEST_V2_SCHEMA,
    EnrichmentManifestV2,
    PerAoiEnrichment,
)
from treesight.models.records import (
    EnrichmentManifest,
    FramePlanEntry,
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
        )
        assert u.billing_allowed is True

    def test_round_trip(self):
        u = UserRecord(
            user_id="u1",
            email="test@example.com",
        )
        d = u.model_dump()
        u2 = UserRecord.model_validate(d)
        assert u2.email == "test@example.com"

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

    def test_legacy_quota_field_is_accepted_as_extra(self):
        u = UserRecord.model_validate({"user_id": "u1", "quota": {"used": 3, "runs": []}})
        assert u.model_extra["quota"] == {"used": 3, "runs": []}


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


class TestEnrichmentManifestV2:
    def test_checked_in_json_schema_matches_model(self):
        schema_path = Path("docs/schemas/enrichment-manifest-v2.schema.json")
        checked_in = json.loads(schema_path.read_text())
        generated = EnrichmentManifestV2.model_json_schema()

        assert checked_in == generated

    def test_single_aoi_manifest_contract(self):
        manifest = EnrichmentManifestV2.model_validate(
            {
                "schema_version": ENRICHMENT_MANIFEST_V2_SCHEMA,
                "run": {"project_name": "test", "timestamp": "20240101", "eudr_mode": True},
                "summary": {"aoi_count": 1, "multi_region": False, "frame_plan": []},
                "per_aoi_enrichment": [
                    {
                        "aoi_index": 0,
                        "name": "Solo Farm",
                        "area_ha": 50.0,
                        "coords": [[-50.0, -10.0], [-50.0, -9.0], [-49.0, -9.0]],
                        "bbox": [[-50.0, -10.0], [-49.0, -9.0]],
                        "center": {"lat": -9.5, "lon": -49.5},
                        "frame_plan": [],
                        "ndvi_raster_paths": ["enrichment/test/20240101/ndvi/2024_spring.tif"],
                    }
                ],
            }
        )

        assert manifest.schema_version == ENRICHMENT_MANIFEST_V2_SCHEMA
        assert len(manifest.per_aoi_enrichment) == 1
        assert manifest.per_aoi_enrichment[0].aoi_index == 0
        assert manifest.per_aoi_enrichment[0].name == "Solo Farm"

    def test_schema_version_is_required_for_v2_writes(self):
        with pytest.raises(ValueError, match="schema_version"):
            EnrichmentManifestV2.model_validate(
                {
                    "run": {"project_name": "test", "timestamp": "20240101"},
                    "summary": {"aoi_count": 0},
                    "per_aoi_enrichment": [],
                }
            )

    def test_run_and_summary_are_required_for_v2_writes(self):
        with pytest.raises(ValueError, match="run"):
            EnrichmentManifestV2.model_validate(
                {"schema_version": ENRICHMENT_MANIFEST_V2_SCHEMA, "summary": {"aoi_count": 0}}
            )
        with pytest.raises(ValueError, match="summary"):
            EnrichmentManifestV2.model_validate(
                {"schema_version": ENRICHMENT_MANIFEST_V2_SCHEMA, "run": {"project_name": "test"}}
            )

    def test_per_aoi_identity_fields_are_required(self):
        with pytest.raises(ValueError, match="name"):
            PerAoiEnrichment.model_validate({"aoi_index": 0})

    def test_weather_daily_accepts_existing_dict_shape(self):
        entry = PerAoiEnrichment.model_validate(
            {
                "aoi_index": 0,
                "name": "Plot",
                "area_ha": 1.0,
                "coords": [[0.0, 0.0]],
                "bbox": [[0.0, 0.0]],
                "center": {"lat": 0.0, "lon": 0.0},
                "weather_daily": {"dates": ["2024-01-01"], "temperature_2m_mean": [20.0]},
            }
        )

        assert entry.weather_daily == {"dates": ["2024-01-01"], "temperature_2m_mean": [20.0]}

    def test_per_aoi_entry_allows_open_evidence_bags(self):
        entry = PerAoiEnrichment.model_validate(
            {
                "aoi_index": 0,
                "name": "Plot",
                "area_ha": 1.0,
                "coords": [[0.0, 0.0]],
                "bbox": [[0.0, 0.0]],
                "center": {"lat": 0.0, "lon": 0.0},
                "custom_evidence": {"provider": "test"},
            }
        )

        assert entry.model_extra["custom_evidence"] == {"provider": "test"}

    def test_per_aoi_entry_requires_canonical_identity_fields(self):
        with pytest.raises(ValueError, match=r"name|area_ha|coords|bbox|center"):
            PerAoiEnrichment.model_validate({"aoi_index": 0})

    def test_per_aoi_entry_accepts_dict_weather_daily_payload(self):
        entry = PerAoiEnrichment.model_validate(
            {
                "aoi_index": 0,
                "name": "Plot",
                "area_ha": 1.0,
                "coords": [[0.0, 0.0]],
                "bbox": [[0.0, 0.0]],
                "center": {"lat": 0.0, "lon": 0.0},
                "weather_daily": {"dates": ["2026-01-01"], "temp": [24.0]},
            }
        )

        assert entry.weather_daily == {"dates": ["2026-01-01"], "temp": [24.0]}
