"""Targeted tests for treesight.ai.client coverage hardening."""

from __future__ import annotations

import pytest

import treesight.ai.client as ai_client


class _FakeResponse:
    def __init__(self, payload: dict, *, raise_error: Exception | None = None):
        self._payload = payload
        self._raise_error = raise_error

    def raise_for_status(self) -> None:
        if self._raise_error:
            raise self._raise_error

    def json(self) -> dict:
        return self._payload


class _FakeHttpClient:
    def __init__(self, response: _FakeResponse):
        self.response = response
        self.posts: list[tuple[str, dict | None, dict | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(
        self, url: str, json: dict | None = None, headers: dict | None = None
    ) -> _FakeResponse:
        self.posts.append((url, json, headers))
        return self.response


class TestCacheHelpers:
    def test_try_cache_read_disabled_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ai_client, "AI_CACHE_ENABLED", False)
        assert ai_client._try_cache_read("abc") is None

    def test_try_cache_read_hit_sets_cached_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Storage:
            def blob_exists(self, _container: str, _path: str) -> bool:
                return True

            def download_json(self, _container: str, _path: str) -> dict:
                return {"ok": True}

        monkeypatch.setattr(ai_client, "AI_CACHE_ENABLED", True)
        monkeypatch.setattr("treesight.storage.client.BlobStorageClient", _Storage)

        result = ai_client._try_cache_read("abc")
        assert result == {"ok": True, "_cached": True}

    def test_try_cache_read_errors_are_non_fatal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Storage:
            def __init__(self) -> None:
                raise RuntimeError("boom")

        monkeypatch.setattr(ai_client, "AI_CACHE_ENABLED", True)
        monkeypatch.setattr("treesight.storage.client.BlobStorageClient", _Storage)

        assert ai_client._try_cache_read("abc") is None

    def test_cache_write_uploads_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        uploaded: list[tuple[str, str, dict]] = []

        class _Storage:
            def upload_json(self, container: str, path: str, data: dict) -> None:
                uploaded.append((container, path, data))

        monkeypatch.setattr(ai_client, "AI_CACHE_ENABLED", True)
        monkeypatch.setattr("treesight.storage.client.BlobStorageClient", _Storage)

        ai_client._cache_write("k1", {"v": 1})

        assert uploaded == [
            (ai_client.AI_CACHE_CONTAINER, f"{ai_client.AI_CACHE_PREFIX}k1.json", {"v": 1})
        ]


class TestProviderCalls:
    def test_call_azure_ai_returns_none_when_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(ai_client, "AZURE_AI_ENDPOINT", "")
        monkeypatch.setattr(ai_client, "AZURE_AI_API_KEY", "")
        assert ai_client._call_azure_ai("prompt") is None

    def test_call_azure_ai_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        response = _FakeResponse({"choices": [{"message": {"content": '{"ok": true}'}}]})
        fake_client = _FakeHttpClient(response)

        monkeypatch.setattr(ai_client, "AZURE_AI_ENDPOINT", "https://example.openai.azure.com")
        monkeypatch.setattr(ai_client, "AZURE_AI_API_KEY", "key")
        monkeypatch.setattr(ai_client._azure_circuit, "allow_request", lambda: True)
        monkeypatch.setattr(ai_client.httpx, "Client", lambda **_kwargs: fake_client)

        text = ai_client._call_azure_ai("prompt")

        assert text == '{"ok": true}'
        assert fake_client.posts
        assert "/chat/completions" in fake_client.posts[0][0]

    def test_call_azure_ai_failure_records_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        response = _FakeResponse({}, raise_error=RuntimeError("http fail"))
        fake_client = _FakeHttpClient(response)

        monkeypatch.setattr(ai_client, "AZURE_AI_ENDPOINT", "https://example.openai.azure.com")
        monkeypatch.setattr(ai_client, "AZURE_AI_API_KEY", "key")
        monkeypatch.setattr(ai_client._azure_circuit, "allow_request", lambda: True)
        monkeypatch.setattr(ai_client.httpx, "Client", lambda **_kwargs: fake_client)

        assert ai_client._call_azure_ai("prompt") is None

    def test_call_ollama_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        response = _FakeResponse({"response": '{"ok": true}'})
        fake_client = _FakeHttpClient(response)

        monkeypatch.setattr(ai_client._ollama_circuit, "allow_request", lambda: True)
        monkeypatch.setattr(ai_client.httpx, "Client", lambda **_kwargs: fake_client)

        assert ai_client._call_ollama("prompt") == '{"ok": true}'
        assert fake_client.posts[0][0].endswith("/api/generate")

    def test_call_ollama_failure_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        response = _FakeResponse({}, raise_error=RuntimeError("fail"))
        fake_client = _FakeHttpClient(response)

        monkeypatch.setattr(ai_client._ollama_circuit, "allow_request", lambda: True)
        monkeypatch.setattr(ai_client.httpx, "Client", lambda **_kwargs: fake_client)

        assert ai_client._call_ollama("prompt") is None


class TestParsingAndGenerateAnalysis:
    def test_parse_json_response_extracts_embedded_json(self) -> None:
        parsed = ai_client._parse_json_response('prefix {"a": 1} suffix')
        assert parsed == {"a": 1}

    def test_parse_json_response_invalid_returns_none(self) -> None:
        assert ai_client._parse_json_response("{not-json}") is None
        assert ai_client._parse_json_response("no object here") is None

    def test_generate_analysis_uses_cache_hit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ai_client, "_try_cache_read", lambda _key: {"cached": True})
        assert ai_client.generate_analysis("p") == {"cached": True}

    def test_generate_analysis_uses_azure_then_cache_write(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        writes: list[tuple[str, dict]] = []

        monkeypatch.setattr(ai_client, "_try_cache_read", lambda _key: None)
        monkeypatch.setattr(ai_client, "_call_azure_ai", lambda _prompt: '{"x": 1}')
        monkeypatch.setattr(ai_client, "_call_ollama", lambda _prompt: None)
        monkeypatch.setattr(
            ai_client, "_cache_write", lambda key, result: writes.append((key, result))
        )

        result = ai_client.generate_analysis("prompt")

        assert result == {"x": 1}
        assert writes and writes[0][1] == {"x": 1}

    def test_generate_analysis_falls_back_to_ollama(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ai_client, "_try_cache_read", lambda _key: None)
        monkeypatch.setattr(ai_client, "_call_azure_ai", lambda _prompt: None)
        monkeypatch.setattr(ai_client, "_call_ollama", lambda _prompt: '{"y": 2}')
        monkeypatch.setattr(ai_client, "_cache_write", lambda *_args: None)

        assert ai_client.generate_analysis("prompt") == {"y": 2}

    def test_generate_analysis_returns_none_when_all_fail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(ai_client, "_try_cache_read", lambda _key: None)
        monkeypatch.setattr(ai_client, "_call_azure_ai", lambda _prompt: None)
        monkeypatch.setattr(ai_client, "_call_ollama", lambda _prompt: "not json")

        assert ai_client.generate_analysis("prompt", use_cache=False) is None
