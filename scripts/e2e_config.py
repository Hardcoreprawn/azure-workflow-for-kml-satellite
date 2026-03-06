#!/usr/bin/env python
"""Shared configuration for local E2E utility scripts.

Keeps ad-hoc script values in one place so root scripts do not drift.
"""

from __future__ import annotations

import os

from kml_satellite.core.constants import DEFAULT_INPUT_CONTAINER, DEFAULT_OUTPUT_CONTAINER

DEFAULT_STORAGE_ACCOUNT_URL = "https://stkmlsatdevjqy5vgpmet56s.blob.core.windows.net"
STORAGE_ACCOUNT_URL_ENV = "AZURE_STORAGE_ACCOUNT_URL"

UPLOAD_TIMEOUT_SECONDS = 30.0
LIST_TIMEOUT_SECONDS = 10.0
POLL_INTERVAL_SECONDS = 5
MAX_POLL_ATTEMPTS = 60
TOTAL_TEST_TIMEOUT_SECONDS = 150.0


def get_storage_account_url() -> str:
    """Return storage account URL from env override or project default."""
    value = os.getenv(STORAGE_ACCOUNT_URL_ENV, DEFAULT_STORAGE_ACCOUNT_URL).strip()
    return value.rstrip("/")


def get_container_names() -> tuple[str, str]:
    """Return canonical input and output container names."""
    return (DEFAULT_INPUT_CONTAINER, DEFAULT_OUTPUT_CONTAINER)
