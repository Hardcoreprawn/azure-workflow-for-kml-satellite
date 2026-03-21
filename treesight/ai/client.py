"""AI inference client with Azure AI Foundry + Ollama fallback + blob caching (M1.6).

Priority:
  1. Azure AI Foundry / Azure OpenAI (if AZURE_AI_ENDPOINT is set)
  2. Local Ollama (if OLLAMA_URL is reachable)
  3. Graceful degradation (return empty analysis)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Any

import httpx

from treesight.constants import DEFAULT_HTTP_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

# Azure AI configuration
AZURE_AI_ENDPOINT = os.environ.get("AZURE_AI_ENDPOINT", "")
AZURE_AI_API_KEY = os.environ.get("AZURE_AI_API_KEY", "")
AZURE_AI_DEPLOYMENT = os.environ.get("AZURE_AI_DEPLOYMENT", "gpt-4o-mini")
AZURE_AI_API_VERSION = os.environ.get("AZURE_AI_API_VERSION", "2024-10-21")

# Ollama fallback
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "mistral")

# Cache
AI_CACHE_CONTAINER = os.environ.get("AI_CACHE_CONTAINER", "kml-output")
AI_CACHE_PREFIX = "ai-cache/"
AI_CACHE_ENABLED = os.environ.get("AI_CACHE_ENABLED", "true").lower() in ("true", "1", "yes")


def _cache_key(prompt: str) -> str:
    """Deterministic cache key from prompt content."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def _try_cache_read(cache_key: str) -> dict[str, Any] | None:
    """Attempt to read cached analysis from blob storage."""
    if not AI_CACHE_ENABLED:
        return None
    try:
        from treesight.storage.client import BlobStorageClient

        client = BlobStorageClient()
        blob_path = f"{AI_CACHE_PREFIX}{cache_key}.json"
        if client.blob_exists(AI_CACHE_CONTAINER, blob_path):
            result = client.download_json(AI_CACHE_CONTAINER, blob_path)
            logger.info("AI cache hit: %s", cache_key)
            result["_cached"] = True
            return result
    except Exception:
        logger.debug("Cache read failed for %s", cache_key, exc_info=True)
    return None


def _cache_write(cache_key: str, result: dict[str, Any]) -> None:
    """Write analysis result to blob cache."""
    if not AI_CACHE_ENABLED:
        return
    try:
        from treesight.storage.client import BlobStorageClient

        client = BlobStorageClient()
        blob_path = f"{AI_CACHE_PREFIX}{cache_key}.json"
        client.upload_json(AI_CACHE_CONTAINER, blob_path, result)
        logger.info("AI cache write: %s", cache_key)
    except Exception:
        logger.debug("Cache write failed for %s", cache_key, exc_info=True)


def _call_azure_ai(prompt: str) -> str | None:
    """Call Azure AI Foundry / Azure OpenAI endpoint."""
    if not AZURE_AI_ENDPOINT or not AZURE_AI_API_KEY:
        return None

    url = (
        f"{AZURE_AI_ENDPOINT.rstrip('/')}/openai/deployments/"
        f"{AZURE_AI_DEPLOYMENT}/chat/completions?api-version={AZURE_AI_API_VERSION}"
    )
    headers = {
        "Content-Type": "application/json",
        "api-key": AZURE_AI_API_KEY,
    }
    body = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an expert geospatial analyst. "
                    "Always respond with valid JSON only, no markdown."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 1000,
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception:
        logger.warning("Azure AI call failed", exc_info=True)
        return None


def _call_ollama(prompt: str) -> str | None:
    """Call local Ollama endpoint as fallback."""
    try:
        with httpx.Client(timeout=DEFAULT_HTTP_TIMEOUT_SECONDS) as client:
            resp = client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "temperature": 0.3,
                },
                timeout=150.0,
            )
            resp.raise_for_status()
            return resp.json().get("response", "")
    except Exception:
        logger.warning("Ollama call failed", exc_info=True)
        return None


def _parse_json_response(text: str) -> dict[str, Any] | None:
    """Extract JSON object from LLM response text."""
    try:
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except json.JSONDecodeError:
        pass
    return None


def generate_analysis(prompt: str, *, use_cache: bool = True) -> dict[str, Any] | None:
    """Generate AI analysis from prompt, with caching and provider fallback.

    Returns parsed JSON dict on success, or None if all providers fail.
    """
    key = _cache_key(prompt)

    if use_cache:
        cached = _try_cache_read(key)
        if cached is not None:
            return cached

    # 1. Try Azure AI Foundry
    text = _call_azure_ai(prompt)
    if text:
        result = _parse_json_response(text)
        if result:
            _cache_write(key, result)
            return result

    # 2. Fallback to Ollama
    text = _call_ollama(prompt)
    if text:
        result = _parse_json_response(text)
        if result:
            _cache_write(key, result)
            return result

    logger.error("All AI providers failed for prompt hash %s", key)
    return None
