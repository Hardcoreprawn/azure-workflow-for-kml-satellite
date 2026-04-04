"""Tests for the temporal acquisition catalogue (§3.2 + §3.3).

Covers:
- CatalogueEntry data model (serialisation, Cosmos round-trip)
- API contracts (camelCase mapping, from_model, query params)
- Repository functions (record_acquisition, get_entry, list_entries)
- Blueprint HTTP endpoints (auth, pagination, filters, CORS)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import patch

import azure.functions as func
import pytest
from pydantic import ValidationError

from tests.conftest import TEST_ORIGIN
from treesight.catalogue.contracts import (
    CatalogueEntryResponse,
    CatalogueListResponse,
    CatalogueQueryParams,
)
from treesight.catalogue.models import CatalogueEntry
from treesight.catalogue.repository import _make_id, _slugify

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)


def _make_entry(**overrides) -> CatalogueEntry:
    """Build a minimal CatalogueEntry with sensible defaults."""
    defaults = {
        "id": "run-1:farm-alpha",
        "user_id": "user-42",
        "run_id": "run-1",
        "aoi_name": "Farm Alpha",
        "source_file": "upload.kml",
        "provider": "planetary-computer",
        "centroid": [36.8, -1.3],
        "bbox": [36.79, -1.31, 36.81, -1.29],
        "area_ha": 12.5,
        "acquired_at": _NOW,
        "submitted_at": _NOW,
        "cloud_cover_pct": 15.2,
        "spatial_resolution_m": 10.0,
        "collection": "sentinel-2-l2a",
        "status": "completed",
        "ndvi_mean": 0.45,
        "ndvi_min": 0.1,
        "ndvi_max": 0.72,
        "change_loss_pct": 2.1,
        "change_gain_pct": 5.3,
        "change_mean_delta": 0.03,
        "imagery_blob_path": "submissions/user-42/run-1/imagery.tif",
        "metadata_blob_path": "submissions/user-42/run-1/meta.json",
        "enrichment_manifest_path": "submissions/user-42/run-1/manifest.json",
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return CatalogueEntry(**defaults)


def _make_request(
    url: str = "/api/catalogue",
    *,
    method: str = "GET",
    params: dict | None = None,
    route_params: dict | None = None,
    origin: str = TEST_ORIGIN,
    auth_header: str = "Bearer fake-token",
) -> func.HttpRequest:
    headers = {"Origin": origin}
    if auth_header:
        headers["Authorization"] = auth_header
    return func.HttpRequest(
        method=method,
        url=url,
        headers=headers,
        params=params or {},
        route_params=route_params or {},
        body=b"",
    )


# ===========================================================================
# Model tests
# ===========================================================================


class TestCatalogueEntry:
    def test_create_minimal(self):
        entry = CatalogueEntry(id="r1:aoi", user_id="u1", run_id="r1", aoi_name="aoi")
        assert entry.status == "pending"
        assert entry.centroid == []
        assert entry.ndvi_mean is None

    def test_to_cosmos(self):
        entry = _make_entry()
        doc = entry.to_cosmos()
        assert doc["id"] == "run-1:farm-alpha"
        assert doc["user_id"] == "user-42"
        assert doc["aoi_name"] == "Farm Alpha"
        assert isinstance(doc["submitted_at"], str)

    def test_from_cosmos_strips_system_props(self):
        entry = _make_entry()
        doc = entry.to_cosmos()
        doc["_rid"] = "abc123"
        doc["_self"] = "/dbs/xxx"
        doc["_etag"] = '"etag"'
        doc["_ts"] = 1234567890

        roundtripped = CatalogueEntry.from_cosmos(doc)
        assert roundtripped.id == entry.id
        assert roundtripped.user_id == entry.user_id
        assert roundtripped.aoi_name == entry.aoi_name

    def test_roundtrip_preserves_values(self):
        original = _make_entry()
        doc = original.to_cosmos()
        restored = CatalogueEntry.from_cosmos(doc)
        assert restored.ndvi_mean == original.ndvi_mean
        assert restored.area_ha == original.area_ha
        assert restored.status == original.status
        assert restored.provider == original.provider


# ===========================================================================
# Contract tests
# ===========================================================================


class TestCatalogueEntryResponse:
    def test_from_model_maps_camel_case(self):
        entry = _make_entry()
        resp = CatalogueEntryResponse.from_model(entry)
        assert resp.run_id == "run-1"
        assert resp.aoi_name == "Farm Alpha"
        assert resp.area_ha == 12.5
        assert resp.cloud_cover_pct == 15.2
        assert resp.ndvi_mean == 0.45
        assert resp.change_loss_pct == 2.1

    def test_from_model_handles_none_dates(self):
        entry = _make_entry(acquired_at=None, created_at=None, updated_at=None)
        resp = CatalogueEntryResponse.from_model(entry)
        assert resp.acquired_at is None
        assert resp.created_at is None

    def test_serialise_json(self):
        entry = _make_entry()
        resp = CatalogueEntryResponse.from_model(entry)
        raw = json.loads(resp.model_dump_json(by_alias=True))
        assert "runId" in raw
        assert "aoiName" in raw
        assert "ndviMean" in raw


class TestCatalogueListResponse:
    def test_build(self):
        entry = _make_entry()
        resp_entry = CatalogueEntryResponse.from_model(entry)
        body = CatalogueListResponse(
            entries=[resp_entry], total=1, offset=0, limit=20, has_more=False
        )
        assert len(body.entries) == 1
        assert body.total == 1
        assert body.has_more is False


class TestCatalogueQueryParams:
    def test_defaults(self):
        p = CatalogueQueryParams()
        assert p.limit == 20
        assert p.offset == 0
        assert p.sort == "desc"
        assert p.aoi_name is None

    def test_limit_bounds(self):
        with pytest.raises(ValidationError):
            CatalogueQueryParams(limit=0)
        with pytest.raises(ValidationError):
            CatalogueQueryParams(limit=200)


# ===========================================================================
# Repository helpers
# ===========================================================================


class TestSlugify:
    def test_basic(self):
        assert _slugify("Farm Alpha") == "farm-alpha"

    def test_special_chars(self):
        assert _slugify("àöü & test!") == "test"

    def test_empty(self):
        assert _slugify("") == "unnamed"
        assert _slugify("!!!") == "unnamed"


class TestMakeId:
    def test_format(self):
        assert _make_id("run-1", "Farm Alpha") == "run-1:farm-alpha"


# ===========================================================================
# Repository CRUD (mocked Cosmos)
# ===========================================================================


class TestRecordAcquisition:
    @patch("treesight.storage.cosmos.read_item", return_value=None)
    @patch("treesight.storage.cosmos.upsert_item")
    def test_creates_entry(self, mock_upsert, mock_read):
        from treesight.catalogue.repository import record_acquisition

        entry = record_acquisition(
            "user-1",
            "run-1",
            "Farm Alpha",
            provider="planetary-computer",
            status="completed",
        )
        assert entry.id == "run-1:farm-alpha"
        assert entry.user_id == "user-1"
        assert entry.run_id == "run-1"
        assert entry.aoi_name == "Farm Alpha"
        assert entry.provider == "planetary-computer"
        mock_upsert.assert_called_once()
        args = mock_upsert.call_args
        assert args[0][0] == "catalogue"

    @patch("treesight.storage.cosmos.read_item", return_value=None)
    @patch("treesight.storage.cosmos.upsert_item")
    def test_sets_timestamps(self, mock_upsert, mock_read):
        from treesight.catalogue.repository import record_acquisition

        entry = record_acquisition("u1", "r1", "AOI")
        assert entry.created_at is not None
        assert entry.updated_at is not None


class TestGetEntry:
    @patch("treesight.storage.cosmos.read_item")
    def test_returns_entry(self, mock_read):
        entry = _make_entry()
        mock_read.return_value = entry.to_cosmos()

        from treesight.catalogue.repository import get_entry

        result = get_entry("run-1:farm-alpha", "user-42")
        assert result is not None
        assert result.id == "run-1:farm-alpha"
        mock_read.assert_called_once_with("catalogue", "run-1:farm-alpha", "user-42")

    @patch("treesight.storage.cosmos.read_item")
    def test_returns_none_when_missing(self, mock_read):
        mock_read.return_value = None

        from treesight.catalogue.repository import get_entry

        assert get_entry("missing", "u1") is None


class TestListEntries:
    @patch("treesight.storage.cosmos.query_items")
    def test_basic_list(self, mock_query):
        entry = _make_entry()
        mock_query.side_effect = [
            [5],  # count query
            [entry.to_cosmos()],  # data query
        ]

        from treesight.catalogue.repository import list_entries

        entries, total = list_entries("user-42")
        assert total == 5
        assert len(entries) == 1
        assert entries[0].id == "run-1:farm-alpha"

    @patch("treesight.storage.cosmos.query_items")
    def test_filters_passed_to_query(self, mock_query):
        mock_query.side_effect = [
            [0],  # count
            [],  # data
        ]

        from treesight.catalogue.repository import list_entries

        list_entries(
            "u1",
            aoi_name="farm",
            status="completed",
            provider="planetary-computer",
        )

        # Both count and data queries should have filter params
        count_call = mock_query.call_args_list[0]
        query_str = count_call[0][1]
        assert "@aoi_name" in query_str
        assert "@status" in query_str
        assert "@provider" in query_str


class TestListEntriesForRun:
    @patch("treesight.storage.cosmos.query_items")
    def test_queries_by_run(self, mock_query):
        mock_query.return_value = []

        from treesight.catalogue.repository import list_entries_for_run

        list_entries_for_run("u1", "r1")
        args = mock_query.call_args
        assert "@rid" in args[0][1]
        assert args[1]["partition_key"] == "u1"


class TestListEntriesForAoi:
    @patch("treesight.storage.cosmos.query_items")
    def test_queries_by_aoi(self, mock_query):
        mock_query.return_value = []

        from treesight.catalogue.repository import list_entries_for_aoi

        list_entries_for_aoi("u1", "Farm Alpha")
        args = mock_query.call_args
        assert "@aoi" in args[0][1]


# ===========================================================================
# Blueprint endpoint tests
# ===========================================================================


class TestCatalogueListEndpoint:
    @patch("blueprints._helpers.validate_token", return_value={"sub": "user-42"})
    @patch("blueprints._helpers.auth_enabled", return_value=True)
    @patch("blueprints._helpers.get_user_id", return_value="user-42")
    @patch("blueprints.catalogue.list_entries")
    def test_returns_200(self, mock_list, mock_uid, mock_auth, mock_validate):
        entry = _make_entry()
        mock_list.return_value = ([entry], 1)

        from blueprints.catalogue import catalogue_list

        req = _make_request()
        resp = catalogue_list(req)
        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert body["total"] == 1
        assert len(body["entries"]) == 1
        assert body["entries"][0]["aoiName"] == "Farm Alpha"

    @patch("blueprints._helpers.validate_token", return_value={"sub": "user-42"})
    @patch("blueprints._helpers.auth_enabled", return_value=True)
    @patch("blueprints._helpers.get_user_id", return_value="user-42")
    @patch("blueprints.catalogue.list_entries")
    def test_pagination_params(self, mock_list, mock_uid, mock_auth, mock_validate):
        mock_list.return_value = ([], 0)

        from blueprints.catalogue import catalogue_list

        req = _make_request(params={"limit": "10", "offset": "5", "sort": "asc"})
        catalogue_list(req)

        call_kwargs = mock_list.call_args
        assert call_kwargs[1]["limit"] == 10
        assert call_kwargs[1]["offset"] == 5
        assert call_kwargs[1]["sort"] == "asc"

    @patch("blueprints._helpers.validate_token", return_value={"sub": "user-42"})
    @patch("blueprints._helpers.auth_enabled", return_value=True)
    @patch("blueprints._helpers.get_user_id", return_value="user-42")
    @patch("blueprints.catalogue.list_entries")
    def test_limit_clamped(self, mock_list, mock_uid, mock_auth, mock_validate):
        mock_list.return_value = ([], 0)

        from blueprints.catalogue import catalogue_list

        req = _make_request(params={"limit": "999"})
        catalogue_list(req)
        assert mock_list.call_args[1]["limit"] == 100

    def test_options_returns_204(self):
        from blueprints.catalogue import catalogue_list

        req = _make_request(method="OPTIONS")
        resp = catalogue_list(req)
        assert resp.status_code == 204

    @patch("blueprints._helpers.auth_enabled", return_value=True)
    @patch("blueprints._helpers.validate_token", side_effect=ValueError("bad token"))
    def test_401_without_valid_token(self, mock_validate, mock_auth):
        from blueprints.catalogue import catalogue_list

        req = _make_request()
        resp = catalogue_list(req)
        assert resp.status_code == 401

    @patch("blueprints._helpers.validate_token", return_value={"sub": "user-42"})
    @patch("blueprints._helpers.auth_enabled", return_value=True)
    @patch("blueprints._helpers.get_user_id", return_value="user-42")
    @patch("blueprints.catalogue.list_entries")
    def test_cors_header(self, mock_list, mock_uid, mock_auth, mock_validate):
        mock_list.return_value = ([], 0)

        from blueprints.catalogue import catalogue_list

        req = _make_request()
        resp = catalogue_list(req)
        assert resp.headers.get("Access-Control-Allow-Origin") == TEST_ORIGIN


class TestCatalogueDetailEndpoint:
    @patch("blueprints._helpers.validate_token", return_value={"sub": "user-42"})
    @patch("blueprints._helpers.auth_enabled", return_value=True)
    @patch("blueprints._helpers.get_user_id", return_value="user-42")
    @patch("blueprints.catalogue.get_entry")
    def test_returns_200(self, mock_get, mock_uid, mock_auth, mock_validate):
        mock_get.return_value = _make_entry()

        from blueprints.catalogue import catalogue_detail

        req = _make_request(
            url="/api/catalogue/run-1:farm-alpha",
            route_params={"entryId": "run-1:farm-alpha"},
        )
        resp = catalogue_detail(req)
        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert body["id"] == "run-1:farm-alpha"

    @patch("blueprints._helpers.validate_token", return_value={"sub": "user-42"})
    @patch("blueprints._helpers.auth_enabled", return_value=True)
    @patch("blueprints._helpers.get_user_id", return_value="user-42")
    @patch("blueprints.catalogue.get_entry")
    def test_returns_404(self, mock_get, mock_uid, mock_auth, mock_validate):
        mock_get.return_value = None

        from blueprints.catalogue import catalogue_detail

        req = _make_request(
            url="/api/catalogue/missing",
            route_params={"entryId": "missing"},
        )
        resp = catalogue_detail(req)
        assert resp.status_code == 404


class TestCatalogueByRunEndpoint:
    @patch("blueprints._helpers.validate_token", return_value={"sub": "user-42"})
    @patch("blueprints._helpers.auth_enabled", return_value=True)
    @patch("blueprints._helpers.get_user_id", return_value="user-42")
    @patch("blueprints.catalogue.list_entries_for_run")
    def test_returns_200(self, mock_list, mock_uid, mock_auth, mock_validate):
        mock_list.return_value = [_make_entry()]

        from blueprints.catalogue import catalogue_by_run

        req = _make_request(
            url="/api/catalogue/run/run-1",
            route_params={"runId": "run-1"},
        )
        resp = catalogue_by_run(req)
        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert body["total"] == 1


class TestCatalogueByAoiEndpoint:
    @patch("blueprints._helpers.validate_token", return_value={"sub": "user-42"})
    @patch("blueprints._helpers.auth_enabled", return_value=True)
    @patch("blueprints._helpers.get_user_id", return_value="user-42")
    @patch("blueprints.catalogue.list_entries_for_aoi")
    def test_returns_200(self, mock_list, mock_uid, mock_auth, mock_validate):
        mock_list.return_value = [_make_entry()]

        from blueprints.catalogue import catalogue_by_aoi

        req = _make_request(
            url="/api/catalogue/aoi/Farm%20Alpha",
            route_params={"aoiName": "Farm Alpha"},
        )
        resp = catalogue_by_aoi(req)
        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert body["total"] == 1
        assert body["entries"][0]["aoiName"] == "Farm Alpha"
