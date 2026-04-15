"""Pure helpers for submission-time pipeline configuration."""

from __future__ import annotations

from typing import Any

from treesight.constants import EUDR_CUTOFF_DATE


def build_eudr_imagery_overrides(
    *,
    eudr_mode: bool,
    existing_filters: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return imagery filter overrides when EUDR mode is active.

    When *eudr_mode* is ``True``, ensures ``date_start`` is at least the
    EUDR cutoff date (``2020-12-31T00:00:00Z``).  Any fields already
    present in *existing_filters* are preserved.

    Returns ``None`` when *eudr_mode* is ``False`` (no overrides needed).
    """
    if not eudr_mode:
        return None

    base: dict[str, Any] = dict(existing_filters) if existing_filters else {}
    base.setdefault("date_start", f"{EUDR_CUTOFF_DATE}T00:00:00Z")
    return base
