"""Tests for the library and GDPR API endpoints (blueprints/library.py)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import azure.functions as func

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SWA_ORIGIN = "https://polite-glacier-0d6885003.4.azurestaticapps.net"


def _req(
    method: str = "GET",
    url: str = "https://func.test/api/library",
    body: dict | list | None = None,
    route_params: dict | None = None,
    headers: dict | None = None,
) -> func.HttpRequest:
    h = {"Origin": _SWA_ORIGIN}
    if headers:
        h.update(headers)
    return func.HttpRequest(
        method=method,
        url=url,
        headers=h,
        body=json.dumps(body).encode() if body is not None else b"",
        route_params=route_params or {},
    )


def _auth_disabled():
    """Patch auth_enabled to return False (anonymous passthrough)."""
    return patch("blueprints._helpers.auth_enabled", return_value=False)


def _mock_library(library_data=None):
    """Patch UserLibrary to use a controllable mock."""
    mock_cls = MagicMock()
    mock_instance = MagicMock()
    mock_cls.return_value = mock_instance

    if library_data is not None:
        mock_instance.get_library.return_value = library_data

    return patch("blueprints.library.UserLibrary", mock_cls), mock_instance


# ---------------------------------------------------------------------------
# GET /api/library
# ---------------------------------------------------------------------------


class TestGetLibrary:
    def test_returns_library_for_authenticated_user(self) -> None:
        from blueprints.library import get_library

        lib_data = {"kmls": [{"id": "k1"}], "analyses": []}
        lib_patch, _mock_lib = _mock_library(lib_data)

        with _auth_disabled(), lib_patch:
            resp = get_library(_req())

        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert len(data["kmls"]) == 1

    def test_returns_cors_headers(self) -> None:
        from blueprints.library import get_library

        lib_patch, _mock_lib = _mock_library({"kmls": [], "analyses": []})

        with _auth_disabled(), lib_patch:
            resp = get_library(_req())

        assert resp.headers.get("Access-Control-Allow-Origin") == _SWA_ORIGIN

    def test_options_returns_204(self) -> None:
        from blueprints.library import get_library

        with _auth_disabled():
            resp = get_library(_req(method="OPTIONS"))

        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# POST /api/library/kmls
# ---------------------------------------------------------------------------


class TestUploadKml:
    def test_upload_kml_returns_201(self) -> None:
        from blueprints.library import upload_kml

        lib_patch, mock_lib = _mock_library()
        mock_lib.add_kml.return_value = {
            "id": "new-kml",
            "name": "Test",
            "uploaded_at": "2026-03-23T00:00:00",
            "size_bytes": 100,
            "polygon_count": 1,
        }

        body = {"name": "Test KML", "kml_content": "<kml><Polygon/></kml>"}

        with _auth_disabled(), lib_patch:
            resp = upload_kml(_req(method="POST", body=body))

        assert resp.status_code == 201
        data = json.loads(resp.get_body())
        assert data["id"] == "new-kml"

    def test_upload_requires_kml_content(self) -> None:
        from blueprints.library import upload_kml

        with _auth_disabled():
            resp = upload_kml(_req(method="POST", body={"name": "Test"}))

        assert resp.status_code == 400

    def test_upload_rejects_oversized_kml(self) -> None:
        from blueprints.library import upload_kml

        body = {"name": "Big", "kml_content": "x" * (10 * 1024 * 1024 + 1)}

        with _auth_disabled():
            resp = upload_kml(_req(method="POST", body=body))

        assert resp.status_code == 413


# ---------------------------------------------------------------------------
# GET /api/library/kmls/{kml_id}
# ---------------------------------------------------------------------------


class TestGetKml:
    def test_download_kml_returns_bytes(self) -> None:
        from blueprints.library import get_kml

        lib_patch, mock_lib = _mock_library()
        mock_lib.get_kml.return_value = b"<kml>content</kml>"

        with _auth_disabled(), lib_patch:
            resp = get_kml(_req(route_params={"kml_id": "k1"}))

        assert resp.status_code == 200
        assert b"<kml>" in resp.get_body()

    def test_download_kml_404_when_missing(self) -> None:
        from blueprints.library import get_kml

        lib_patch, mock_lib = _mock_library()
        mock_lib.get_kml.side_effect = FileNotFoundError("not found")

        with _auth_disabled(), lib_patch:
            resp = get_kml(_req(route_params={"kml_id": "nonexistent"}))

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/library/kmls/{kml_id}
# ---------------------------------------------------------------------------


class TestDeleteKml:
    def test_delete_kml_returns_200(self) -> None:
        from blueprints.library import delete_kml

        lib_patch, mock_lib = _mock_library()
        mock_lib.delete_kml.return_value = True

        with _auth_disabled(), lib_patch:
            resp = delete_kml(_req(method="DELETE", route_params={"kml_id": "k1"}))

        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["deleted"] == "k1"

    def test_delete_kml_404_when_missing(self) -> None:
        from blueprints.library import delete_kml

        lib_patch, mock_lib = _mock_library()
        mock_lib.delete_kml.return_value = False

        with _auth_disabled(), lib_patch:
            resp = delete_kml(_req(method="DELETE", route_params={"kml_id": "gone"}))

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/library/analyses
# ---------------------------------------------------------------------------


class TestSaveAnalysis:
    def test_save_analysis_returns_201(self) -> None:
        from blueprints.library import save_analysis

        lib_patch, mock_lib = _mock_library()
        mock_lib.add_analysis.return_value = {
            "id": "a1",
            "kml_id": "k1",
            "instance_id": "inst-1",
            "status": "completed",
        }

        body = {
            "kml_id": "k1",
            "instance_id": "inst-1",
            "kml_name": "Test",
            "status": "completed",
        }

        with _auth_disabled(), lib_patch:
            resp = save_analysis(_req(method="POST", body=body))

        assert resp.status_code == 201

    def test_save_analysis_requires_fields(self) -> None:
        from blueprints.library import save_analysis

        with _auth_disabled():
            resp = save_analysis(_req(method="POST", body={"kml_id": "k1"}))

        assert resp.status_code == 400

    def test_save_analysis_rejects_invalid_status(self) -> None:
        from blueprints.library import save_analysis

        body = {"kml_id": "k1", "instance_id": "i1", "status": "evil"}

        with _auth_disabled():
            resp = save_analysis(_req(method="POST", body=body))

        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# PATCH /api/library/analyses/{analysis_id}
# ---------------------------------------------------------------------------


class TestUpdateAnalysis:
    def test_patch_with_status_updates(self) -> None:
        from blueprints.library import update_analysis

        lib_patch, mock_lib = _mock_library()
        mock_lib.update_analysis_status.return_value = True

        body = {"status": "completed", "frame_count": 24}

        with _auth_disabled(), lib_patch:
            resp = update_analysis(
                _req(method="PATCH", body=body, route_params={"analysis_id": "a1"})
            )

        assert resp.status_code == 200
        mock_lib.update_analysis_status.assert_called_once()

    def test_patch_summary_only(self) -> None:
        from blueprints.library import update_analysis

        lib_patch, mock_lib = _mock_library()
        mock_lib.update_analysis_extra.return_value = True

        body = {"summary": '{"ndvi_delta":-0.08}'}

        with _auth_disabled(), lib_patch:
            resp = update_analysis(
                _req(method="PATCH", body=body, route_params={"analysis_id": "a1"})
            )

        assert resp.status_code == 200
        mock_lib.update_analysis_extra.assert_called_once()

    def test_patch_empty_body_rejected(self) -> None:
        from blueprints.library import update_analysis

        with _auth_disabled():
            resp = update_analysis(
                _req(method="PATCH", body={}, route_params={"analysis_id": "a1"})
            )

        assert resp.status_code == 400

    def test_patch_invalid_status_rejected(self) -> None:
        from blueprints.library import update_analysis

        with _auth_disabled():
            resp = update_analysis(
                _req(method="PATCH", body={"status": "evil"}, route_params={"analysis_id": "a1"})
            )

        assert resp.status_code == 400

    def test_patch_non_dict_body_rejected(self) -> None:
        from blueprints.library import update_analysis

        with _auth_disabled():
            resp = update_analysis(
                _req(method="PATCH", body=["list"], route_params={"analysis_id": "a1"})
            )

        assert resp.status_code == 400

    def test_patch_invalid_frame_count_rejected(self) -> None:
        from blueprints.library import update_analysis

        with _auth_disabled():
            resp = update_analysis(
                _req(
                    method="PATCH",
                    body={"frame_count": "not-a-number"},
                    route_params={"analysis_id": "a1"},
                )
            )

        assert resp.status_code == 400

    def test_patch_negative_frame_count_rejected(self) -> None:
        from blueprints.library import update_analysis

        with _auth_disabled():
            resp = update_analysis(
                _req(
                    method="PATCH",
                    body={"frame_count": -5},
                    route_params={"analysis_id": "a1"},
                )
            )

        assert resp.status_code == 400

    def test_patch_summary_preserves_json_structure(self) -> None:
        from blueprints.library import update_analysis

        lib_patch, mock_lib = _mock_library()
        mock_lib.update_analysis_extra.return_value = True

        summary = json.dumps({"ndvi_delta": -0.08, "assessment": "Moderate decline"})
        body = {"summary": summary}

        with _auth_disabled(), lib_patch:
            resp = update_analysis(
                _req(method="PATCH", body=body, route_params={"analysis_id": "a1"})
            )

        assert resp.status_code == 200
        call_kwargs = mock_lib.update_analysis_extra.call_args
        saved = json.loads(call_kwargs.kwargs["summary"])
        assert saved["ndvi_delta"] == -0.08


# ---------------------------------------------------------------------------
# CORS — X-Confirm-Delete header allowed
# ---------------------------------------------------------------------------


class TestCorsCustomHeaders:
    def test_cors_allows_x_confirm_delete(self) -> None:
        from blueprints._helpers import cors_headers

        req = _req()
        headers = cors_headers(req)
        assert "X-Confirm-Delete" in headers.get("Access-Control-Allow-Headers", "")


# ---------------------------------------------------------------------------
# GDPR — GET /api/account/export (Article 20)
# ---------------------------------------------------------------------------


class TestExportUserData:
    def test_export_returns_json_attachment(self) -> None:
        from blueprints.library import export_user_data

        lib_patch, mock_lib = _mock_library()
        mock_lib.export_all_data.return_value = {
            "user_id": "user-123",
            "exported_at": "2026-03-23T00:00:00",
            "library": {"kmls": [], "analyses": []},
            "quota": None,
        }

        with _auth_disabled(), lib_patch:
            resp = export_user_data(_req())

        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("Content-Disposition", "")
        data = json.loads(resp.get_body())
        assert data["user_id"] == "user-123"

    def test_export_includes_cors(self) -> None:
        from blueprints.library import export_user_data

        lib_patch, mock_lib = _mock_library()
        mock_lib.export_all_data.return_value = {
            "user_id": "u",
            "exported_at": "",
            "library": {"kmls": [], "analyses": []},
            "quota": None,
        }

        with _auth_disabled(), lib_patch:
            resp = export_user_data(_req())

        assert resp.headers.get("Access-Control-Allow-Origin") == _SWA_ORIGIN


# ---------------------------------------------------------------------------
# GDPR — DELETE /api/account (Article 17)
# ---------------------------------------------------------------------------


class TestDeleteAccount:
    def test_delete_requires_confirmation_header(self) -> None:
        from blueprints.library import delete_account

        with _auth_disabled():
            resp = delete_account(_req(method="DELETE"))

        assert resp.status_code == 400
        assert "X-Confirm-Delete" in json.loads(resp.get_body())["error"]

    def test_delete_with_wrong_confirmation_rejected(self) -> None:
        from blueprints.library import delete_account

        with _auth_disabled():
            resp = delete_account(_req(method="DELETE", headers={"X-Confirm-Delete": "wrong"}))

        assert resp.status_code == 400

    def test_delete_with_correct_confirmation_succeeds(self) -> None:
        from blueprints.library import delete_account

        lib_patch, mock_lib = _mock_library()
        mock_lib.delete_all_data.return_value = {
            "blobs_deleted": 5,
            "user_id": "user-123",
        }

        with _auth_disabled(), lib_patch:
            resp = delete_account(
                _req(
                    method="DELETE",
                    headers={
                        "X-Confirm-Delete": "permanently-delete-all-my-data",
                    },
                )
            )

        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["status"] == "deleted"
        assert data["blobs_deleted"] == 5

    def test_delete_returns_cors_headers(self) -> None:
        from blueprints.library import delete_account

        lib_patch, mock_lib = _mock_library()
        mock_lib.delete_all_data.return_value = {
            "blobs_deleted": 0,
            "user_id": "u",
        }

        with _auth_disabled(), lib_patch:
            resp = delete_account(
                _req(
                    method="DELETE",
                    headers={
                        "X-Confirm-Delete": "permanently-delete-all-my-data",
                    },
                )
            )

        assert resp.headers.get("Access-Control-Allow-Origin") == _SWA_ORIGIN
