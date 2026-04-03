"""Tests for pipeline modules — orchestrator helpers (§3)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from blueprints.pipeline._helpers import (
    _acq_payload,
    _download_payload,
    _poll_payload,
    _post_process_payload,
)
from blueprints.pipeline.history import _parse_history_limit, _parse_history_offset
from treesight.pipeline.orchestrator import (
    build_pipeline_summary,
    derive_project_context,
    get_batch_config,
)
from treesight.storage.offload import PayloadOffloader


class TestDeriveProjectContext:
    def test_extracts_stem(self):
        ctx = derive_project_context("uploads/my-farm.kml")
        assert ctx["project_name"] == "my-farm"

    def test_timestamp_format(self):
        ctx = derive_project_context("test.kml")
        assert "T" in ctx["timestamp"]
        assert ctx["timestamp"].endswith("Z")

    def test_nested_path(self):
        ctx = derive_project_context("a/b/c/orchard.kml")
        assert ctx["project_name"] == "orchard"


class TestGetBatchConfig:
    def test_defaults(self):
        cfg = get_batch_config({})
        assert cfg["poll_batch_size"] == 10
        assert cfg["download_batch_size"] == 10
        assert cfg["post_process_batch_size"] == 10

    def test_overrides(self):
        cfg = get_batch_config(
            {
                "poll_batch_size": 5,
                "download_batch_size": "20",
                "post_process_batch_size": 4.0,
            }
        )
        assert cfg["poll_batch_size"] == 5
        assert cfg["download_batch_size"] == 20
        assert cfg["post_process_batch_size"] == 4


class TestBuildPipelineSummary:
    def test_completed_summary(self):
        result = build_pipeline_summary(
            instance_id="inst-1",
            blob_name="test.kml",
            blob_url="https://storage/kml-input/test.kml",
            ingestion={
                "feature_count": 2,
                "aoi_count": 2,
                "metadata_count": 2,
                "metadata_results": [],
            },
            acquisition={"ready_count": 2, "failed_count": 0, "imagery_outcomes": []},
            fulfilment={
                "downloads_completed": 2,
                "downloads_succeeded": 2,
                "downloads_failed": 0,
                "download_results": [],
                "pp_completed": 2,
                "pp_clipped": 2,
                "pp_reprojected": 1,
                "pp_failed": 0,
                "post_process_results": [],
            },
        )
        assert result["status"] == "completed"
        assert result["feature_count"] == 2
        assert result["imagery_ready"] == 2

    def test_partial_summary(self):
        result = build_pipeline_summary(
            instance_id="inst-2",
            blob_name="test.kml",
            blob_url="",
            ingestion={
                "feature_count": 3,
                "aoi_count": 3,
                "metadata_count": 3,
                "metadata_results": [],
            },
            acquisition={"ready_count": 2, "failed_count": 1, "imagery_outcomes": []},
            fulfilment={
                "downloads_completed": 2,
                "downloads_succeeded": 2,
                "downloads_failed": 0,
                "download_results": [],
                "pp_completed": 2,
                "pp_clipped": 1,
                "pp_reprojected": 0,
                "pp_failed": 0,
                "post_process_results": [],
            },
        )
        assert result["status"] == "partial_imagery"


class TestParseHistoryLimit:
    def test_valid_limit(self):
        assert _parse_history_limit("5") == 5

    def test_empty_returns_default(self):
        assert _parse_history_limit("") == 8

    def test_clamps_to_max(self):
        assert _parse_history_limit("100") == 20

    def test_clamps_to_min(self):
        assert _parse_history_limit("0") == 1

    def test_non_numeric(self):
        assert _parse_history_limit("abc") == 8


class TestParseHistoryOffset:
    def test_valid_offset(self):
        assert _parse_history_offset("10") == 10

    def test_empty_returns_zero(self):
        assert _parse_history_offset("") == 0

    def test_negative_clamps_to_zero(self):
        assert _parse_history_offset("-5") == 0

    def test_clamps_to_max(self):
        assert _parse_history_offset("9999") == 200

    def test_non_numeric(self):
        assert _parse_history_offset("abc") == 0


# ---------------------------------------------------------------------------
# §3.1 — Claim Check Pattern
# ---------------------------------------------------------------------------


class TestPayloadOffloaderClaimCheck:
    """Tests for individual claim check operations on PayloadOffloader."""

    def _make_offloader(self):
        storage = MagicMock()
        return PayloadOffloader(storage), storage

    def test_store_claim_uploads_json(self):
        offloader, storage = self._make_offloader()
        data = {"feature_name": "farm_1", "bbox": [1.0, 2.0, 3.0, 4.0]}
        ref = offloader.store_claim("inst-1", "aoi_0", data)
        assert ref == "claims/inst-1/aoi_0.json"
        storage.upload_bytes.assert_called_once()
        call_args = storage.upload_bytes.call_args
        assert call_args[0][0] == "pipeline-payloads"
        assert call_args[0][1] == "claims/inst-1/aoi_0.json"
        payload = json.loads(call_args[0][2])
        assert payload["feature_name"] == "farm_1"

    def test_load_claim_returns_dict(self):
        offloader, storage = self._make_offloader()
        expected = {"feature_name": "farm_1", "bbox": [1.0, 2.0, 3.0, 4.0]}
        storage.download_bytes.return_value = json.dumps(expected).encode()
        result = offloader.load_claim("claims/inst-1/aoi_0.json")
        assert result == expected

    def test_store_claims_batch_returns_refs(self):
        offloader, storage = self._make_offloader()
        items = [
            {"feature_name": "aoi_a", "area_ha": 10.0},
            {"feature_name": "aoi_b", "area_ha": 20.0},
        ]
        refs = offloader.store_claims_batch("inst-2", items)
        assert len(refs) == 2
        assert refs[0]["key"] == "aoi_a"
        assert refs[1]["key"] == "aoi_b"
        assert "ref" in refs[0]
        assert "ref" in refs[1]
        assert storage.upload_bytes.call_count == 2

    def test_store_claims_batch_uses_key_field(self):
        offloader, _storage = self._make_offloader()
        items = [{"id": "x", "val": 1}]
        refs = offloader.store_claims_batch("inst-3", items, key_field="id")
        assert refs[0]["key"] == "x"
        assert "id_0_" in refs[0]["claim_id"]


class TestClaimCheckBulkRoundtrip:
    """Integration-style test verifying bulk claim store → load cycle."""

    def test_roundtrip(self):
        storage = MagicMock()
        _stored: dict[str, bytes] = {}

        def _upload(container, path, data, **kw):
            _stored[path] = data

        def _download(container, path):
            return _stored[path]

        storage.upload_bytes.side_effect = _upload
        storage.download_bytes.side_effect = _download

        offloader = PayloadOffloader(storage)
        aoi = {"feature_name": "orchard", "bbox": [10.0, 20.0, 10.1, 20.1], "area_ha": 5.0}
        ref = offloader.store_claim("inst-rt", "orchard_0", aoi)
        loaded = offloader.load_claim(ref)
        assert loaded == aoi


# ---------------------------------------------------------------------------
# §3.2 — Orchestrator Payload Builders
# ---------------------------------------------------------------------------


class TestAcqPayload:
    def test_composite_includes_temporal_count(self):
        ref = {"ref": "claims/inst/aoi_0.json", "key": "aoi_a"}
        inp = {"provider_name": "pc", "temporal_count": 4}
        p = _acq_payload(ref, inp, composite=True)
        assert p["aoi_ref"] == "claims/inst/aoi_0.json"
        assert p["temporal_count"] == 4

    def test_non_composite_omits_temporal_count(self):
        ref = {"ref": "claims/inst/aoi_0.json", "key": "aoi_a"}
        inp = {}
        p = _acq_payload(ref, inp, composite=False)
        assert "temporal_count" not in p
        assert p["provider_name"] == "planetary_computer"


class TestPollPayload:
    def test_builds_from_order(self):
        order = {"order_id": "o1", "scene_id": "s1", "aoi_feature_name": "farm"}
        inp = {"provider_name": "pc"}
        p = _poll_payload(order, inp)
        assert p["order_id"] == "o1"
        assert p["aoi_feature_name"] == "farm"
        assert p["overrides"] == inp


class TestDownloadPayload:
    def test_includes_aoi_ref(self):
        outcome = {"order_id": "o1", "aoi_feature_name": "farm"}
        inp = {}
        ctx = {"project_name": "proj", "timestamp": "20260402T000000Z"}
        asset_urls = {"o1": "https://example.com/img.tif"}
        order_meta = {"o1": {"role": "visual", "collection": "naip"}}
        aoi_ref_lookup = {"farm": "claims/inst/farm.json"}
        p = _download_payload(outcome, inp, ctx, asset_urls, order_meta, aoi_ref_lookup, "output")
        assert p["aoi_ref"] == "claims/inst/farm.json"
        assert p["asset_url"] == "https://example.com/img.tif"
        assert p["role"] == "visual"


class TestPostProcessPayload:
    def test_includes_aoi_ref_and_defaults(self):
        dl = {"aoi_feature_name": "farm"}
        inp = {}
        ctx = {"project_name": "proj", "timestamp": "20260402T000000Z"}
        aoi_ref_lookup = {"farm": "claims/inst/farm.json"}
        p = _post_process_payload(dl, inp, ctx, aoi_ref_lookup, "output")
        assert p["aoi_ref"] == "claims/inst/farm.json"
        assert p["enable_clipping"] is True
        assert p["square_frame"] is True


# ---------------------------------------------------------------------------
# §3.3 — Activity AOI Loading
# ---------------------------------------------------------------------------


class TestLoadAoi:
    def test_loads_from_claim_ref(self):
        from blueprints.pipeline.activities import _load_aoi

        aoi_data = {
            "feature_name": "farm",
            "exterior_coords": [[1.0, 2.0], [3.0, 4.0]],
            "bbox": [1.0, 2.0, 3.0, 4.0],
            "buffered_bbox": [0.9, 1.9, 3.1, 4.1],
        }
        mock_storage = MagicMock()
        mock_storage.download_bytes.return_value = json.dumps(aoi_data).encode()

        result = _load_aoi({"aoi_ref": "claims/inst/farm.json"}, mock_storage)
        assert result.feature_name == "farm"
        assert result.bbox == [1.0, 2.0, 3.0, 4.0]

    def test_loads_from_inline_aoi(self):
        from blueprints.pipeline.activities import _load_aoi

        result = _load_aoi({"aoi": {"feature_name": "inline"}})
        assert result.feature_name == "inline"


# ---------------------------------------------------------------------------
# §3.4 — Constants
# ---------------------------------------------------------------------------


class TestAcquisitionBatchConstant:
    def test_default_acquisition_batch_size(self):
        from treesight.constants import DEFAULT_ACQUISITION_BATCH_SIZE

        assert DEFAULT_ACQUISITION_BATCH_SIZE == 25


# ---------------------------------------------------------------------------
# §11 — Bulk AOI (#311)
# ---------------------------------------------------------------------------


class TestMaxFeaturesConstant:
    def test_max_features_exists(self):
        from treesight.constants import MAX_FEATURES_PER_KML

        assert MAX_FEATURES_PER_KML == 500


class TestGroupPerAoi:
    def test_groups_by_feature_name(self):
        from treesight.pipeline.orchestrator import _group_per_aoi

        acquisition = {
            "imagery_outcomes": [
                {"aoi_feature_name": "farm_a", "state": "ready"},
                {"aoi_feature_name": "farm_a", "state": "ready"},
                {"aoi_feature_name": "farm_b", "state": "failed"},
            ]
        }
        fulfilment = {
            "download_results": [
                {"aoi_feature_name": "farm_a", "state": "completed"},
                {"aoi_feature_name": "farm_b", "state": "failed"},
            ],
            "post_process_results": [
                {"aoi_feature_name": "farm_a", "clipped_blob_path": "x.tif"},
            ],
        }

        result = _group_per_aoi(acquisition, fulfilment)
        assert len(result) == 2
        a = next(r for r in result if r["feature_name"] == "farm_a")
        b = next(r for r in result if r["feature_name"] == "farm_b")
        assert a["imagery_ready"] == 2
        assert a["downloads_succeeded"] == 1
        assert a["post_process_completed"] == 1
        assert b["imagery_failed"] == 1
        assert b["downloads_failed"] == 1

    def test_empty_inputs(self):
        from treesight.pipeline.orchestrator import _group_per_aoi

        result = _group_per_aoi({}, {})
        assert result == []


class TestAoiSummaryModel:
    def test_defaults(self):
        from treesight.models.outcomes import AoiSummary

        s = AoiSummary(feature_name="test")
        assert s.feature_name == "test"
        assert s.imagery_ready == 0

    def test_roundtrip(self):
        from treesight.models.outcomes import AoiSummary

        s = AoiSummary(feature_name="field", imagery_ready=3, downloads_succeeded=2)
        d = s.model_dump()
        assert d["feature_name"] == "field"
        assert d["imagery_ready"] == 3


class TestPipelineSummaryPerAoi:
    def test_includes_per_aoi(self):
        from treesight.pipeline.orchestrator import build_pipeline_summary

        result = build_pipeline_summary(
            instance_id="inst-1",
            blob_name="test.kml",
            blob_url="https://example.com/test.kml",
            ingestion={"feature_count": 2, "aoi_count": 2},
            acquisition={
                "ready_count": 2,
                "failed_count": 0,
                "imagery_outcomes": [
                    {"aoi_feature_name": "a", "state": "ready"},
                    {"aoi_feature_name": "b", "state": "ready"},
                ],
            },
            fulfilment={
                "downloads_completed": 2,
                "downloads_succeeded": 2,
                "downloads_failed": 0,
                "download_results": [
                    {"aoi_feature_name": "a", "state": "completed"},
                    {"aoi_feature_name": "b", "state": "completed"},
                ],
                "pp_completed": 2,
                "pp_clipped": 2,
                "pp_reprojected": 2,
                "pp_failed": 0,
                "post_process_results": [
                    {"aoi_feature_name": "a", "clipped_blob_path": "x.tif"},
                    {"aoi_feature_name": "b", "clipped_blob_path": "y.tif"},
                ],
            },
        )

        assert "per_aoi_summaries" in result
        assert len(result["per_aoi_summaries"]) == 2
        names = {s["feature_name"] for s in result["per_aoi_summaries"]}
        assert names == {"a", "b"}
