"""Cosmos-first, blob-fallback read/write helpers."""

from __future__ import annotations

import logging
from typing import TypeVar

from treesight.storage import cosmos as _cosmos_mod

logger = logging.getLogger(__name__)

T = TypeVar("T")


def read_with_fallback(cosmos_read, blob_read):
    """Try Cosmos first, fall back to blob storage."""
    if _cosmos_mod.cosmos_available():
        try:
            return cosmos_read()
        except Exception:
            logger.debug("Cosmos read failed, falling back to blob", exc_info=True)
    return blob_read()


def write_with_fallback(cosmos_write, blob_write):
    """Try Cosmos first, fall back to blob storage."""
    if _cosmos_mod.cosmos_available():
        try:
            cosmos_write()
            return
        except Exception:
            logger.debug("Cosmos write failed, falling back to blob", exc_info=True)
    blob_write()
