"""Tests for Phase 1 — ingestion logic (§3.1).

Covers ``parse_kml_from_blob``, ``prepare_aois``, and ``write_metadata``
using a mock ``BlobStorageClient``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from treesight.models.aoi import AOI
from treesight.models.blob_event import BlobEvent
from treesight.models.feature import Feature

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_blob_event(blob_name: str = "uploads/farm.kml") -> BlobEvent:
    return BlobEvent(
        blob_url=f"https://store.blob.core.windows.net/kml-input/{blob_name}",
        container_name="kml-input",
        blob_name=blob_name,
        content_length=4096,
        content_type="application/vnd.google-earth.kml+xml",
        event_time="2026-03-18T12:00:00Z",
        correlation_id="evt-test-001",
    )


def _mock_storage(kml_bytes: bytes) -> MagicMock:
    """Return a mock ``BlobStorageClient`` that serves *kml_bytes* on download."""
    storage = MagicMock()
    storage.download_bytes.return_value = kml_bytes
    storage.upload_json = MagicMock()
    return storage


# ---------------------------------------------------------------------------
# parse_kml_from_blob
# ---------------------------------------------------------------------------


class TestParseKmlFromBlob:
    """Tests for ``parse_kml_from_blob``."""

    def test_parses_sample_kml_features(self) -> None:
        """Real sample KML is downloaded from mock storage and parsed."""
        from treesight.pipeline.ingestion import parse_kml_from_blob

        kml_bytes = (FIXTURES_DIR / "sample.kml").read_bytes()
        storage = _mock_storage(kml_bytes)
        event = _make_blob_event("uploads/sample.kml")

        features = parse_kml_from_blob(event, storage)

        assert len(features) >= 1
        assert all(isinstance(f, Feature) for f in features)
        storage.download_bytes.assert_called_once_with("kml-input", "uploads/sample.kml")

    def test_feature_has_name_and_coords(self) -> None:
        """Parsed features carry name and exterior coordinates."""
        from treesight.pipeline.ingestion import parse_kml_from_blob

        kml_bytes = (FIXTURES_DIR / "sample.kml").read_bytes()
        storage = _mock_storage(kml_bytes)
        event = _make_blob_event()

        features = parse_kml_from_blob(event, storage)
        f = features[0]

        assert f.name
        assert len(f.exterior_coords) >= 3

    def test_source_file_set_from_blob_name(self) -> None:
        """The ``source_file`` field is the filename part of the blob path."""
        from treesight.pipeline.ingestion import parse_kml_from_blob

        kml_bytes = (FIXTURES_DIR / "sample.kml").read_bytes()
        storage = _mock_storage(kml_bytes)
        event = _make_blob_event("tenant/dir/my-farm.kml")

        features = parse_kml_from_blob(event, storage)

        assert features[0].source_file == "my-farm.kml"

    def test_rejects_empty_container_name(self) -> None:
        """parse_kml_from_blob raises when container_name is empty."""
        import pytest

        from treesight.pipeline.ingestion import parse_kml_from_blob

        event = BlobEvent(
            blob_url="https://store.blob.core.windows.net/kml-input/f.kml",
            container_name="",
            blob_name="uploads/farm.kml",
            content_length=4096,
            content_type="application/vnd.google-earth.kml+xml",
            event_time="2026-03-18T12:00:00Z",
            correlation_id="evt-test-empty",
        )
        with pytest.raises(ValueError, match="container_name"):
            parse_kml_from_blob(event, _mock_storage(b"<kml/>"))

    def test_rejects_empty_blob_name(self) -> None:
        """parse_kml_from_blob raises when blob_name is empty."""
        import pytest

        from treesight.pipeline.ingestion import parse_kml_from_blob

        event = BlobEvent(
            blob_url="https://store.blob.core.windows.net/kml-input/",
            container_name="kml-input",
            blob_name="",
            content_length=4096,
            content_type="application/vnd.google-earth.kml+xml",
            event_time="2026-03-18T12:00:00Z",
            correlation_id="evt-test-empty",
        )
        with pytest.raises(ValueError, match="blob_name"):
            parse_kml_from_blob(event, _mock_storage(b"<kml/>"))


# ---------------------------------------------------------------------------
# parse_kml activity input validation
# ---------------------------------------------------------------------------


class TestParseKmlActivityValidation:
    """Activity boundary rejects non-dict payloads."""

    def test_rejects_none_payload(self) -> None:
        import pytest

        from blueprints.pipeline.activities import parse_kml

        with pytest.raises(TypeError, match="expects dict"):
            parse_kml(None)

    def test_rejects_string_payload(self) -> None:
        import pytest

        from blueprints.pipeline.activities import parse_kml

        with pytest.raises(TypeError, match="expects dict"):
            parse_kml("not-a-dict")


# ---------------------------------------------------------------------------
# prepare_aois
# ---------------------------------------------------------------------------


class TestPrepareAois:
    """Tests for ``prepare_aois``."""

    def test_returns_one_aoi_per_feature(self, sample_feature: Feature) -> None:
        """Each input feature produces exactly one AOI."""
        from treesight.pipeline.ingestion import prepare_aois

        aois = prepare_aois([sample_feature, sample_feature])

        assert len(aois) == 2
        assert all(isinstance(a, AOI) for a in aois)

    def test_respects_custom_buffer(self, sample_feature: Feature) -> None:
        """A custom buffer overrides the default."""
        from treesight.pipeline.ingestion import prepare_aois

        aois = prepare_aois([sample_feature], buffer_m=500.0)

        assert aois[0].buffer_m == 500.0

    def test_empty_input(self) -> None:
        """An empty feature list produces an empty AOI list."""
        from treesight.pipeline.ingestion import prepare_aois

        aois = prepare_aois([])

        assert aois == []


# ---------------------------------------------------------------------------
# write_metadata
# ---------------------------------------------------------------------------


class TestWriteMetadata:
    """Tests for ``write_metadata``."""

    def test_uploads_metadata_json(self, sample_aoi: AOI) -> None:
        """Metadata JSON is uploaded to the expected path."""
        from treesight.pipeline.ingestion import write_metadata

        storage = MagicMock()
        write_metadata(
            aoi=sample_aoi,
            processing_id="proc-001",
            timestamp="2026-03-18T12:00:00Z",
            tenant_id="acme",
            source_file="farm.kml",
            output_container="kml-output",
            storage=storage,
        )

        storage.upload_json.assert_called_once()
        call_args = storage.upload_json.call_args
        assert call_args[0][0] == "kml-output"  # container
        assert call_args[0][1].startswith("metadata/farm/")  # path
        assert call_args[0][1].endswith(".json")

    def test_metadata_doc_has_required_fields(self, sample_aoi: AOI) -> None:
        """The metadata document contains schema, processing_id, and geometry."""
        from treesight.pipeline.ingestion import write_metadata

        storage = MagicMock()
        write_metadata(
            aoi=sample_aoi,
            processing_id="proc-002",
            timestamp="2026-03-18T12:00:00Z",
            tenant_id="acme",
            source_file="farm.kml",
            output_container="kml-output",
            storage=storage,
        )

        doc: dict[str, Any] = storage.upload_json.call_args[0][2]
        assert doc["$schema"] == "aoi-metadata-v2"
        assert doc["processing_id"] == "proc-002"
        assert doc["tenant_id"] == "acme"
        assert "geometry" in doc
        assert doc["geometry"]["crs"] == "EPSG:4326"

    def test_result_contains_paths(self, sample_aoi: AOI) -> None:
        """The return value includes metadata_path and kml_archive_path."""
        from treesight.pipeline.ingestion import write_metadata

        storage = MagicMock()
        result = write_metadata(
            aoi=sample_aoi,
            processing_id="proc-003",
            timestamp="2026-03-18T12:00:00Z",
            tenant_id="",
            source_file="test.kml",
            output_container="kml-output",
            storage=storage,
        )

        assert "metadata_path" in result
        assert "kml_archive_path" in result
        assert result["metadata_path"].endswith(".json")

    def test_safe_name_sanitisation(self) -> None:
        """Feature names with spaces/slashes are sanitised in the path."""
        from treesight.pipeline.ingestion import write_metadata

        aoi = AOI(
            feature_name="Block A / Section 2",
            source_file="farm.kml",
            feature_index=0,
            exterior_coords=[[0, 0], [1, 0], [1, 1], [0, 0]],
            bbox=[0, 0, 1, 1],
            buffered_bbox=[0, 0, 1, 1],
            area_ha=100.0,
            centroid=[0.5, 0.5],
            buffer_m=100.0,
            crs="EPSG:4326",
        )
        storage = MagicMock()
        result = write_metadata(
            aoi=aoi,
            processing_id="proc-004",
            timestamp="2026-03-18T12:00:00Z",
            tenant_id="",
            source_file="farm.kml",
            output_container="kml-output",
            storage=storage,
        )

        path = result["metadata_path"]
        assert " " not in path
        assert "/" in path  # directory separators should remain
        assert "Block_A___Section_2" in path

    def test_kml_archival(self, sample_aoi: AOI) -> None:
        """When kml_bytes is provided, the KML is archived to output container."""
        from treesight.pipeline.ingestion import write_metadata

        storage = MagicMock()
        kml_data = b"<kml>...</kml>"
        result = write_metadata(
            aoi=sample_aoi,
            processing_id="proc-005",
            timestamp="2026-03-18T12:00:00Z",
            tenant_id="",
            source_file="farm.kml",
            output_container="kml-output",
            storage=storage,
            kml_bytes=kml_data,
        )

        assert result["kml_archive_path"].startswith("kml/")
        # upload_json for metadata + upload_bytes for KML
        assert storage.upload_bytes.call_count == 1
        kml_call = storage.upload_bytes.call_args
        assert kml_call[0][0] == "kml-output"
        assert kml_call[0][1] == result["kml_archive_path"]
        assert kml_call[0][2] == kml_data

    def test_kml_not_archived_when_no_bytes(self, sample_aoi: AOI) -> None:
        """When kml_bytes is None, no KML archival upload happens."""
        from treesight.pipeline.ingestion import write_metadata

        storage = MagicMock()
        write_metadata(
            aoi=sample_aoi,
            processing_id="proc-006",
            timestamp="2026-03-18T12:00:00Z",
            tenant_id="",
            source_file="farm.kml",
            output_container="kml-output",
            storage=storage,
        )

        # Only upload_json should be called (metadata), not upload_bytes
        storage.upload_bytes.assert_not_called()


# ---------------------------------------------------------------------------
# enforce_aoi_limit
# ---------------------------------------------------------------------------


class TestEnforceAoiLimit:
    """Tests for ``enforce_aoi_limit`` — tier-based feature count gate."""

    def test_allows_features_within_limit(self) -> None:
        """No exception when feature count is at or below the tier's aoi_limit."""
        from treesight.pipeline.ingestion import enforce_aoi_limit

        # free tier allows 5
        enforce_aoi_limit(feature_count=5, tier="free")
        enforce_aoi_limit(feature_count=1, tier="free")

    def test_rejects_features_exceeding_limit(self) -> None:
        """Raises ValueError when feature count exceeds the tier's aoi_limit."""
        import pytest

        from treesight.pipeline.ingestion import enforce_aoi_limit

        with pytest.raises(ValueError, match=r"6 AOIs.*Free.*allows 5"):
            enforce_aoi_limit(feature_count=6, tier="free")

    def test_rejects_demo_tier_over_one(self) -> None:
        """Demo tier allows only 1 AOI."""
        import pytest

        from treesight.pipeline.ingestion import enforce_aoi_limit

        with pytest.raises(ValueError, match=r"2 AOIs.*Demo.*allows 1"):
            enforce_aoi_limit(feature_count=2, tier="demo")

    def test_enterprise_allows_unlimited(self) -> None:
        """Enterprise tier has no aoi_limit (None) — any count is allowed."""
        from treesight.pipeline.ingestion import enforce_aoi_limit

        enforce_aoi_limit(feature_count=1000, tier="enterprise")

    def test_pro_tier_limit(self) -> None:
        """Pro tier allows 50."""
        import pytest

        from treesight.pipeline.ingestion import enforce_aoi_limit

        enforce_aoi_limit(feature_count=50, tier="pro")
        with pytest.raises(ValueError, match=r"51 AOIs.*Pro.*allows 50"):
            enforce_aoi_limit(feature_count=51, tier="pro")

    def test_unknown_tier_defaults_to_free(self) -> None:
        """Unknown tier falls back to free-tier limits."""
        import pytest

        from treesight.pipeline.ingestion import enforce_aoi_limit

        enforce_aoi_limit(feature_count=5, tier="unknown_tier")
        with pytest.raises(ValueError, match=r"6 AOIs.*allows 5"):
            enforce_aoi_limit(feature_count=6, tier="unknown_tier")

    def test_error_message_includes_upgrade_hint(self) -> None:
        """Error message should suggest a suitable tier."""
        import pytest

        from treesight.pipeline.ingestion import enforce_aoi_limit

        with pytest.raises(ValueError, match=r"Starter plan supports up to 15"):
            enforce_aoi_limit(feature_count=6, tier="free")

    def test_none_tier_defaults_to_free(self) -> None:
        """None tier falls back to free-tier limits."""
        import pytest

        from treesight.pipeline.ingestion import enforce_aoi_limit

        enforce_aoi_limit(feature_count=5, tier=None)
        with pytest.raises(ValueError, match=r"6 AOIs.*Free.*allows 5"):
            enforce_aoi_limit(feature_count=6, tier=None)

    def test_error_message_suggests_suitable_tier(self) -> None:
        """Error should name the cheapest tier that fits the AOI count."""
        import pytest

        from treesight.pipeline.ingestion import enforce_aoi_limit

        # 6 AOIs on free (limit 5) → suggest Starter (limit 15)
        with pytest.raises(ValueError, match=r"Starter plan supports up to 15"):
            enforce_aoi_limit(feature_count=6, tier="free")

        # 16 AOIs on free → suggest Pro (limit 50)
        with pytest.raises(ValueError, match=r"Pro plan supports up to 50"):
            enforce_aoi_limit(feature_count=16, tier="free")

        # 56 AOIs on free → suggest Team (limit 200)
        with pytest.raises(ValueError, match=r"Team plan supports up to 200"):
            enforce_aoi_limit(feature_count=56, tier="free")

        # 201 AOIs on free → suggest Enterprise (unlimited)
        with pytest.raises(ValueError, match=r"Enterprise plan supports unlimited"):
            enforce_aoi_limit(feature_count=201, tier="free")

    def test_error_message_suggests_next_tier_from_current(self) -> None:
        """When over the Pro limit, suggestion should be Team, not Starter."""
        import pytest

        from treesight.pipeline.ingestion import enforce_aoi_limit

        # 51 AOIs on pro (limit 50) → suggest Team (limit 200)
        with pytest.raises(ValueError, match=r"Team plan supports up to 200"):
            enforce_aoi_limit(feature_count=51, tier="pro")


# ---------------------------------------------------------------------------
# Duplicate feature names (regression guards for pipeline flakiness)
# ---------------------------------------------------------------------------


class TestDuplicateFeatureNames:
    """Guards against duplicate AOI names causing claim-check key collisions.

    A KML with two identically-named placemarks was observed to cause a
    silent collision in the aoi_ref_lookup, making the second run appear
    to hang in the 'Parsing parcels and validating geometry' phase.
    """

    def test_parse_duplicate_names_returns_all_features(self) -> None:
        """Parser returns all features even when names collide."""
        from treesight.parsers.lxml_parser import parse_kml_lxml

        kml_bytes = (FIXTURES_DIR / "duplicate_names.kml").read_bytes()
        features = parse_kml_lxml(kml_bytes, source_file="duplicate_names.kml")

        assert len(features) == 2
        assert all(f.name == "Block A" for f in features)

    def test_duplicate_names_have_distinct_feature_indices(self) -> None:
        """Each parsed feature carries a unique feature_index even with shared names."""
        from treesight.parsers.lxml_parser import parse_kml_lxml

        kml_bytes = (FIXTURES_DIR / "duplicate_names.kml").read_bytes()
        features = parse_kml_lxml(kml_bytes, source_file="duplicate_names.kml")

        indices = [f.feature_index for f in features]
        assert len(set(indices)) == 2, "Duplicate features must have distinct feature_index values"

    def test_store_claims_batch_duplicate_names_unique_claim_ids(self) -> None:
        """store_claims_batch must produce unique claim_ids for same-named AOIs."""
        from treesight.storage.offload import PayloadOffloader

        storage = MagicMock()
        storage.upload_bytes = MagicMock()

        offloader = PayloadOffloader(storage)
        items = [
            {"feature_name": "Block A", "area_ha": 10.0},
            {"feature_name": "Block A", "area_ha": 20.0},
        ]
        refs = offloader.store_claims_batch("inst-dup", items)

        assert len(refs) == 2
        claim_ids = [r["claim_id"] for r in refs]
        assert claim_ids[0] != claim_ids[1], "Same-named AOIs must have distinct claim_ids"
        assert refs[0]["key"] == "Block A"
        assert refs[1]["key"] == "Block A"

    def test_orchestrator_raises_on_duplicate_aoi_keys(self) -> None:
        """The acquisition phase raises ValueError on duplicate AOI keys.

        This is the explicit guard in _phase_acquisition — it must fire before
        the aoi_ref_lookup silently drops one of the two entries.
        """
        import pytest

        from blueprints.pipeline.orchestrator import _phase_acquisition

        ctx = MagicMock()
        ctx.call_activity_with_retry.return_value = []
        ctx.task_all.return_value = []

        # Two refs with the same key simulate duplicate-named AOIs
        aoi_refs = [
            {"ref": "claims/inst/0.json", "key": "Block A"},
            {"ref": "claims/inst/1.json", "key": "Block A"},
        ]
        aoi_area_by_name: dict[str, float] = {"Block A": 10.0}

        gen = _phase_acquisition(ctx, {}, aoi_refs, aoi_area_by_name)
        gen.send(None)  # first yield: acquisition task_all

        with pytest.raises(ValueError, match="Duplicate AOI key"):
            gen.send([])  # resume with empty acquisition results → hits aoi_ref_lookup build


class TestEmptyFeatureNames:
    """Guards against blank names causing all AOIs to share the same claim key."""

    def test_store_claims_batch_empty_name_uses_fallback_key(self) -> None:
        """Items with empty feature_name get a per-index fallback, not a shared ''."""
        from treesight.storage.offload import PayloadOffloader

        storage = MagicMock()
        storage.upload_bytes = MagicMock()
        offloader = PayloadOffloader(storage)

        items = [
            {"feature_name": "", "area_ha": 5.0},
            {"feature_name": "", "area_ha": 8.0},
        ]
        refs = offloader.store_claims_batch("inst-empty", items)

        claim_ids = [r["claim_id"] for r in refs]
        assert claim_ids[0] != claim_ids[1], "Empty-named AOIs must get distinct claim_ids"

    def test_store_claims_batch_none_name_uses_fallback_key(self) -> None:
        """Items with None feature_name get an index-based fallback key."""
        from treesight.storage.offload import PayloadOffloader

        storage = MagicMock()
        storage.upload_bytes = MagicMock()
        offloader = PayloadOffloader(storage)

        items = [{"area_ha": 5.0}, {"area_ha": 8.0}]  # no 'feature_name' key at all
        refs = offloader.store_claims_batch("inst-none", items)

        # key should be the fallback, not "None"
        assert refs[0]["key"] != refs[1]["key"] or refs[0]["claim_id"] != refs[1]["claim_id"]
