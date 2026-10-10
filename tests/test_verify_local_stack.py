"""Tests for verify_local_stack.py's pure decision logic (#1411).

Live behaviour (hitting real containers, running the real pipeline) is
exercised by running the script itself against `make dev-all` — not
something worth mocking in unit tests, matching the convention in
tests/test_corpus_runner.py / tests/test_validate_blueprint_parity.py.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from verify_local_stack import EXPORT_FORMATS, summarize


@pytest.mark.parametrize("state, expected", [("running|healthy", True), ("running|unhealthy", False)])
def test_container_health_uses_project_service_labels(
    monkeypatch: pytest.MonkeyPatch, state: str, expected: bool
) -> None:
    from verify_local_stack import check_container_running

    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "test-project")
    with patch("verify_local_stack.subprocess.run") as run:
        run.side_effect = [
            subprocess.CompletedProcess([], 0, "container-id\n"),
            subprocess.CompletedProcess([], 0, state),
        ]
        assert check_container_running("func") is expected
    selection = run.call_args_list[0].args[0]
    assert "label=com.docker.compose.project=test-project" in selection
    assert "label=com.docker.compose.service=func" in selection
    assert run.call_args_list[1].args[0][-1] == "container-id"


def test_container_health_ignores_stale_stopped_container() -> None:
    from verify_local_stack import check_container_running

    def docker_result(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[1] == "ps":
            containers = "live-id\nstale-id\n" if "--all" in command else "live-id\n"
            return subprocess.CompletedProcess(command, 0, containers)
        return subprocess.CompletedProcess(command, 0, "running|healthy")

    with patch("verify_local_stack.subprocess.run", side_effect=docker_result):
        assert check_container_running("func")


@pytest.mark.parametrize("containers", ["", "first-live\nsecond-live\n"])
def test_container_health_rejects_missing_or_ambiguous_live_service(containers: str) -> None:
    from verify_local_stack import check_container_running

    with patch("verify_local_stack.subprocess.run", return_value=subprocess.CompletedProcess([], 0, containers)):
        assert not check_container_running("func")


class TestSummarize:
    def test_all_passed(self):
        failed, passed = summarize([("a", True), ("b", True)])
        assert failed == []
        assert passed is True

    def test_some_failed(self):
        failed, passed = summarize([("a", True), ("b", False), ("c", False)])
        assert failed == ["b", "c"]
        assert passed is False

    def test_empty_results_pass(self):
        failed, passed = summarize([])
        assert failed == []
        assert passed is True


class TestExportFormats:
    def test_covers_the_three_eudr_formats(self):
        assert set(EXPORT_FORMATS) == {"eudr-pdf", "eudr-geojson", "eudr-csv"}


def test_exports_use_authenticated_owned_run() -> None:
    from verify_local_stack import check_exports

    with patch("verify_local_stack.httpx.Client") as client_factory:
        client = client_factory.return_value.__enter__.return_value
        client.get.side_effect = [
            SimpleNamespace(
                status_code=200,
                content=b"%PDF-1.7 verified export",
                headers={
                    "content-type": "application/pdf",
                    "content-disposition": 'attachment; filename="treesight_owned-run-id_eudr_report.pdf"',
                },
            ),
            SimpleNamespace(
                status_code=200,
                content=(
                    b'{"type":"FeatureCollection","features":[{"type":"Feature",'
                    b'"geometry":{"type":"Point","coordinates":[1,2]},"properties":{}}]}'
                ),
                headers={
                    "content-type": "application/geo+json",
                    "content-disposition": 'attachment; filename="treesight_owned-run-id_eudr.geojson"',
                },
            ),
            SimpleNamespace(
                status_code=200,
                content=b"parcel,area\nA,1\n",
                headers={
                    "content-type": "text/csv",
                    "content-disposition": 'attachment; filename="treesight_owned-run-id_eudr.csv"',
                },
            ),
        ]

        results = check_exports("owned-run-id", token="verified-token", api_base="http://api.test")

    assert all(ok for _, ok in results)
    assert len(client.get.call_args_list) == len(EXPORT_FORMATS)
    for call in client.get.call_args_list:
        assert call.kwargs["headers"] == {"Authorization": "Bearer verified-token"}
        assert call.args[0].startswith("http://api.test/api/export/owned-run-id/")


def test_exports_fail_closed_without_bearer_token() -> None:
    from verify_local_stack import check_exports

    with patch("verify_local_stack.httpx.Client") as client_factory:
        results = check_exports("owned-run-id", token="  ")

    assert results == [(f"export:{fmt}", False) for fmt in EXPORT_FORMATS]
    client_factory.assert_not_called()


def test_exports_fail_when_there_is_no_owned_run() -> None:
    from verify_local_stack import check_exports

    with patch("verify_local_stack.httpx.Client") as client_factory:
        results = check_exports(None, token="verified-token")

    assert results == [(f"export:{fmt}", False) for fmt in EXPORT_FORMATS]
    client_factory.assert_not_called()


@pytest.mark.parametrize(
    "fmt,content_type,content,disposition,expected",
    [
        ("eudr-pdf", "application/pdf", b"%PDF-1.7 document", 'filename="run-1.pdf"', True),
        ("eudr-pdf", "application/pdf", b"not a pdf", 'filename="run-1.pdf"', False),
        (
            "eudr-geojson",
            "application/geo+json",
            b'{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Point","coordinates":[1,2]},"properties":{}}]}',
            'filename="run-1.geojson"',
            True,
        ),
        (
            "eudr-geojson",
            "application/geo+json",
            b'{"type":"FeatureCollection","features":[]}',
            'filename="run-1.geojson"',
            False,
        ),
        ("eudr-csv", "text/csv", b"parcel,area\nA,1\n", 'filename="run-1.csv"', True),
        ("eudr-csv", "text/csv", b"parcel,area\n", 'filename="run-1.csv"', False),
        ("eudr-pdf", "application/pdf", b"%PDF-1.7 document", 'filename="other.pdf"', False),
        ("eudr-csv", "application/json", b"{}", 'filename="run-1.csv"', False),
        ("eudr-csv", "text/csv", b"\xff", 'filename="run-1.csv"', False),
        ("eudr-geojson", "application/json", b"{}", 'filename="run-1.geojson"', False),
        ("eudr-geojson", "application/geo+json", b"{", 'filename="run-1.geojson"', False),
        ("other", "application/octet-stream", b"data", 'filename="run-1.other"', False),
    ],
)
def test_export_response_requires_valid_run_artifact(
    fmt: str, content_type: str, content: bytes, disposition: str, expected: bool
) -> None:
    from verify_local_stack import _valid_export_response

    response = SimpleNamespace(
        status_code=200,
        headers={"content-type": content_type, "content-disposition": disposition},
        content=content,
    )

    assert _valid_export_response(fmt, "run-1", response) is expected


def test_history_contains_completed_owned_run() -> None:
    from verify_local_stack import _history_contains_run

    payload = {"runs": [{"instanceId": "run-1", "runtimeStatus": "Completed"}]}

    assert _history_contains_run(payload, "run-1")
    assert not _history_contains_run(payload, "other-run")


def test_get_history_requires_org_identity() -> None:
    from verify_local_stack import _get_history

    client = SimpleNamespace(
        get=MagicMock(
            return_value=SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"orgId": ""},
            )
        )
    )

    with pytest.raises(ValueError, match="missing its organisation identity"):
        _get_history(client, "http://orch.test", "verified-token")


def test_load_api_only_tokens_returns_none_when_local_issuer_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from verify_local_stack import _load_api_only_tokens

    monkeypatch.setenv("VERIFY_LOCAL_CIAM_TOKEN_URL", "")
    for name in (
        "VERIFY_BEARER_TOKEN",
        "VERIFY_WRONG_USER_BEARER_TOKEN",
        "VERIFY_WRONG_ORG_BEARER_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)

    assert _load_api_only_tokens() is None


@pytest.mark.parametrize(
    "payload,error",
    [
        ([], "invalid response"),
        ({"owner": "owner-token"}, "missing an identity token"),
    ],
)
def test_load_api_only_tokens_rejects_invalid_issuer_response(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
    error: str,
) -> None:
    from verify_local_stack import _load_api_only_tokens

    for name in (
        "VERIFY_BEARER_TOKEN",
        "VERIFY_WRONG_USER_BEARER_TOKEN",
        "VERIFY_WRONG_ORG_BEARER_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VERIFY_LOCAL_CIAM_TOKEN_URL", "http://issuer.test/tokens")
    response = SimpleNamespace(json=lambda: payload, raise_for_status=lambda: None)
    with patch("verify_local_stack.httpx.get", return_value=response):
        with pytest.raises(ValueError, match=error):
            _load_api_only_tokens()


def test_ensure_api_verifier_org_recovers_conflict_by_reading_membership() -> None:
    from verify_local_stack import _ensure_api_verifier_org

    client = SimpleNamespace(
        get=MagicMock(
            side_effect=[
                SimpleNamespace(json=lambda: {"org": None}, raise_for_status=lambda: None),
                SimpleNamespace(json=lambda: {"org": {"org_id": "raced-org"}}, raise_for_status=lambda: None),
            ]
        ),
        post=MagicMock(return_value=SimpleNamespace(status_code=409)),
    )

    assert (
        _ensure_api_verifier_org(
            client,
            api_base="http://orch.test",
            token="verified-token",
            name="Local verifier owner",
        )
        == "raced-org"
    )
    assert client.get.call_count == 2


def test_ensure_api_verifier_org_rejects_response_without_id() -> None:
    from verify_local_stack import _ensure_api_verifier_org

    client = SimpleNamespace(
        get=MagicMock(return_value=SimpleNamespace(json=lambda: {"org": {}}, raise_for_status=lambda: None)),
        post=MagicMock(),
    )

    with pytest.raises(ValueError, match="missing its id"):
        _ensure_api_verifier_org(
            client,
            api_base="http://orch.test",
            token="verified-token",
            name="Local verifier owner",
        )


def test_wrong_user_helper_requires_no_org_membership() -> None:
    from verify_local_stack import _verify_api_identity_without_org

    client = SimpleNamespace(
        get=MagicMock(return_value=SimpleNamespace(json=lambda: {"org": None}, raise_for_status=lambda: None))
    )
    _verify_api_identity_without_org(client, api_base="http://orch.test", token="verified-token")

    client.get.return_value.json = lambda: {"org": {"org_id": "unexpected-org"}}
    with pytest.raises(ValueError, match="must not belong to an organization"):
        _verify_api_identity_without_org(client, api_base="http://orch.test", token="verified-token")


def test_api_only_mode_skips_full_stack_checks() -> None:
    from verify_local_stack import main

    with (
        patch("verify_local_stack.check_api_only_journey", return_value=[("api-only:journey", True)]) as journey,
        patch("verify_local_stack.check_service_health") as full_stack_check,
        patch("verify_local_stack.check_website") as website_check,
    ):
        assert main(["--api-only"]) == 0

    journey.assert_called_once_with()
    full_stack_check.assert_not_called()
    website_check.assert_not_called()


def test_full_mode_runs_the_existing_verification_slices() -> None:
    from verify_local_stack import main

    passed = [("check", True)]
    with (
        patch("verify_local_stack.check_service_health", return_value=passed) as service_health,
        patch("verify_local_stack.check_parity", return_value=passed) as parity,
        patch("verify_local_stack.check_storage", return_value=passed) as storage,
        patch("verify_local_stack.check_cosmos", return_value=passed) as cosmos,
        patch("verify_local_stack.check_pipeline", return_value=(passed, "internal-run")) as pipeline,
        patch("verify_local_stack.check_api_only_journey", return_value=passed) as api_journey,
        patch("verify_local_stack.check_website", return_value=passed) as website,
        patch("verify_local_stack.check_event_grid_relay", return_value=passed) as relay,
        patch("verify_local_stack.check_ollama", return_value=passed) as ollama,
    ):
        assert main([]) == 0

    for check in (service_health, parity, storage, cosmos, pipeline, website, relay, ollama):
        check.assert_called_once()
    api_journey.assert_not_called()


def test_load_api_only_tokens_from_local_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    from verify_local_stack import _load_api_only_tokens

    for name in (
        "VERIFY_BEARER_TOKEN",
        "VERIFY_WRONG_USER_BEARER_TOKEN",
        "VERIFY_WRONG_ORG_BEARER_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VERIFY_LOCAL_CIAM_TOKEN_URL", "http://issuer.test/tokens")
    response = SimpleNamespace(
        json=lambda: {"owner": "owner-jwt", "wrong_user": "wrong-user-jwt", "wrong_org": "wrong-org-jwt"},
        raise_for_status=lambda: None,
    )

    with patch("verify_local_stack.httpx.get", return_value=response) as get:
        assert _load_api_only_tokens() == ("owner-jwt", "wrong-user-jwt", "wrong-org-jwt")

    get.assert_called_once_with("http://issuer.test/tokens", timeout=5.0, trust_env=False)


def test_ensure_api_verifier_org_creates_missing_org() -> None:
    from verify_local_stack import _ensure_api_verifier_org

    client = SimpleNamespace(
        get=MagicMock(
            return_value=SimpleNamespace(
                json=lambda: {"org": None},
                raise_for_status=lambda: None,
            )
        ),
        post=MagicMock(
            return_value=SimpleNamespace(
                status_code=201,
                json=lambda: {"org": {"org_id": "created-org"}},
                raise_for_status=lambda: None,
            )
        ),
    )

    assert (
        _ensure_api_verifier_org(
            client,
            api_base="http://orch.test",
            token="verified-token",
            name="Local verifier owner",
        )
        == "created-org"
    )
    client.get.assert_called_once_with(
        "http://orch.test/api/org",
        headers={"Authorization": "Bearer verified-token"},
        timeout=10.0,
    )
    client.post.assert_called_once_with(
        "http://orch.test/api/org",
        headers={"Authorization": "Bearer verified-token"},
        json={"name": "Local verifier owner"},
        timeout=10.0,
    )


def test_ensure_api_verifier_org_reuses_existing_membership() -> None:
    from verify_local_stack import _ensure_api_verifier_org

    client = SimpleNamespace(
        get=MagicMock(
            return_value=SimpleNamespace(
                json=lambda: {"org": {"id": "existing-org"}},
                raise_for_status=lambda: None,
            )
        ),
        post=MagicMock(),
    )

    assert (
        _ensure_api_verifier_org(
            client,
            api_base="http://orch.test",
            token="verified-token",
            name="Local verifier owner",
        )
        == "existing-org"
    )
    client.post.assert_not_called()


def test_api_only_journey_checks_owned_run_and_negative_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    import verify_local_stack as verifier

    monkeypatch.setenv("VERIFY_BEARER_TOKEN", "owner-token")
    monkeypatch.setenv("VERIFY_WRONG_USER_BEARER_TOKEN", "wrong-user-token")
    monkeypatch.setenv("VERIFY_WRONG_ORG_BEARER_TOKEN", "wrong-org-token")
    monkeypatch.setattr(verifier, "ORCH_BASE", "http://orch.test/")
    output = {
        "artifacts": {"manifest": "run-1/manifest.json"},
    }
    histories = [
        {"orgId": "owner-org"},
        {"orgId": "wrong-user-org"},
        {"orgId": "wrong-org"},
        {"orgId": "owner-org", "runs": [{"instanceId": "run-1", "runtimeStatus": "Completed"}]},
    ]
    with (
        patch("verify_local_stack.httpx.Client") as client_factory,
        patch("verify_local_stack._get_history", side_effect=histories),
        patch("verify_local_stack.mint_upload_token", return_value={"submissionId": "run-1", "sasUrl": "sas"}) as mint,
        patch("verify_local_stack._upload_api_kml") as upload,
        patch("verify_local_stack.poll_orchestrator", return_value={"runtimeStatus": "Completed"}) as poll,
        patch("verify_local_stack.verify_completed_output_shape", return_value=output),
        patch("verify_local_stack._collect_artifact_paths", return_value=["run-1/manifest.json"]),
        patch(
            "verify_local_stack.check_exports", return_value=[(f"export:{fmt}", True) for fmt in EXPORT_FORMATS]
        ) as exports,
    ):
        client = client_factory.return_value.__enter__.return_value
        client.get.side_effect = [
            SimpleNamespace(status_code=401),
            SimpleNamespace(status_code=404),
            SimpleNamespace(status_code=404),
        ]
        results = verifier.check_api_only_journey()

    assert all(ok for _, ok in results)
    assert ("api-only:journey", True) in results
    assert mint.call_args.kwargs["token"] == "owner-token"
    assert mint.call_args.kwargs["eudr_mode"] is True
    upload.assert_called_once()
    assert poll.call_args.kwargs["token"] == "owner-token"
    assert poll.call_args.kwargs["api_base"] == "http://orch.test"
    exports.assert_called_once_with("run-1", token="owner-token", api_base="http://orch.test")
    assert [call.kwargs["headers"] for call in client.get.call_args_list] == [
        {},
        {"Authorization": "Bearer wrong-user-token"},
        {"Authorization": "Bearer wrong-org-token"},
    ]


def test_api_only_journey_uses_local_issuer_and_distinct_membership_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import verify_local_stack as verifier

    for name in (
        "VERIFY_BEARER_TOKEN",
        "VERIFY_WRONG_USER_BEARER_TOKEN",
        "VERIFY_WRONG_ORG_BEARER_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VERIFY_LOCAL_CIAM_TOKEN_URL", "http://issuer.test/tokens")
    monkeypatch.setattr(verifier, "ORCH_BASE", "http://orch.test/")
    output = {"artifacts": {"manifest": "run-local/manifest.json"}}
    histories = [
        {"orgId": "owner-org"},
        {"orgId": "wrong-org"},
        {"orgId": "owner-org", "runs": [{"instanceId": "run-local", "runtimeStatus": "Completed"}]},
    ]
    token_response = SimpleNamespace(
        json=lambda: {"owner": "owner-token", "wrong_user": "wrong-user-token", "wrong_org": "wrong-org-token"},
        raise_for_status=lambda: None,
    )
    with (
        patch("verify_local_stack.httpx.get", return_value=token_response) as issue_tokens,
        patch("verify_local_stack.httpx.Client") as client_factory,
        patch("verify_local_stack._ensure_api_verifier_org", side_effect=["owner-org", "wrong-org"]) as ensure_org,
        patch("verify_local_stack._verify_api_identity_without_org") as verify_unassigned,
        patch("verify_local_stack._get_history", side_effect=histories) as history,
        patch("verify_local_stack.mint_upload_token", return_value={"submissionId": "run-local", "sasUrl": "sas"}),
        patch("verify_local_stack._upload_api_kml"),
        patch("verify_local_stack.poll_orchestrator", return_value={"runtimeStatus": "Completed"}),
        patch("verify_local_stack.verify_completed_output_shape", return_value=output),
        patch("verify_local_stack._collect_artifact_paths", return_value=["run-local/manifest.json"]),
        patch("verify_local_stack.check_exports", return_value=[(f"export:{fmt}", True) for fmt in EXPORT_FORMATS]),
    ):
        client = client_factory.return_value.__enter__.return_value
        client.get.side_effect = [
            SimpleNamespace(status_code=401),
            SimpleNamespace(status_code=404),
            SimpleNamespace(status_code=404),
        ]
        results = verifier.check_api_only_journey()

    assert all(ok for _, ok in results)
    issue_tokens.assert_called_once_with("http://issuer.test/tokens", timeout=5.0, trust_env=False)
    assert [call.kwargs["token"] for call in ensure_org.call_args_list] == ["owner-token", "wrong-org-token"]
    verify_unassigned.assert_called_once_with(
        client,
        api_base="http://orch.test",
        token="wrong-user-token",
    )
    assert [call.args[2] for call in history.call_args_list] == ["owner-token", "wrong-org-token", "owner-token"]


def test_api_only_journey_reports_partial_failure_without_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import httpx
    import verify_local_stack as verifier

    monkeypatch.setenv("VERIFY_BEARER_TOKEN", "private-owner-token")
    monkeypatch.setenv("VERIFY_WRONG_USER_BEARER_TOKEN", "private-wrong-user-token")
    monkeypatch.setenv("VERIFY_WRONG_ORG_BEARER_TOKEN", "private-wrong-org-token")
    with (
        patch("verify_local_stack.httpx.Client"),
        patch("verify_local_stack._get_history", side_effect=httpx.ConnectError("offline")),
    ):
        results = verifier.check_api_only_journey()

    assert results == [
        ("api-only:owner-identity-validation", False),
        ("api-only:journey", False),
    ]
    output = capsys.readouterr().out
    assert "owner identity validation" in output
    assert "ConnectError" in output
    assert "private-owner-token" not in output
    assert "private-wrong-user-token" not in output
    assert "private-wrong-org-token" not in output


def test_api_only_journey_requires_all_identity_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    from verify_local_stack import check_api_only_journey

    monkeypatch.setenv("VERIFY_LOCAL_CIAM_TOKEN_URL", "")
    for name in (
        "VERIFY_BEARER_TOKEN",
        "VERIFY_WRONG_USER_BEARER_TOKEN",
        "VERIFY_WRONG_ORG_BEARER_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)

    with patch("verify_local_stack.httpx.Client") as client_factory:
        results = check_api_only_journey()

    assert results == [("api-only:journey", False)]
    client_factory.assert_not_called()
