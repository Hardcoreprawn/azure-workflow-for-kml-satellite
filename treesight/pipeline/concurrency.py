"""Concurrency cap helpers — atomic admission slots in Cosmos (#759, #1365).

Admission state lives in a dedicated singleton document in the ``runs``
container so request admission no longer scans historical run records.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from treesight.constants import COSMOS_CONTAINER_RUNS

logger = logging.getLogger(__name__)

_ADMISSION_DOC_ID = "__admission_slots_v1__"
_ADMISSION_DOC_PARTITION_KEY = "__system__"
_ADMISSION_DOC_KIND = "admission_slots"
_MAX_ADMISSION_ETAG_RETRIES = 5


class AdmissionUnavailableError(RuntimeError):
    """Raised when admission state cannot be read or updated safely."""


@dataclass
class _AdmissionState:
    doc: dict[str, Any]
    etag: str


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _prune_stale_slots(
    slots: dict[str, str],
    *,
    now: datetime,
    window_minutes: int,
    mode: str,
) -> int:
    cutoff = now - timedelta(minutes=window_minutes)
    min_dt = datetime.min.replace(tzinfo=UTC)
    stale_ids = [instance_id for instance_id, ts in slots.items() if (_parse_ts(ts) or min_dt) < cutoff]
    for instance_id in stale_ids:
        del slots[instance_id]
    if stale_ids:
        logger.warning(
            "admission_slots_reconciled mode=%s leaked_slots=%d",
            mode,
            len(stale_ids),
        )
    return len(stale_ids)


def _admission_doc() -> dict[str, Any]:
    return {
        "id": _ADMISSION_DOC_ID,
        "user_id": _ADMISSION_DOC_PARTITION_KEY,
        "kind": _ADMISSION_DOC_KIND,
        "active_slots": {},
        "updated_at": _now().isoformat(),
    }


def _load_state(container_name: str) -> _AdmissionState | None:
    from treesight.storage.cosmos import read_item_with_etag

    loaded = read_item_with_etag(container_name, _ADMISSION_DOC_ID, _ADMISSION_DOC_PARTITION_KEY)
    if not loaded:
        return None
    doc, etag = loaded
    return _AdmissionState(doc=doc, etag=etag)


def _replace_state(container_name: str, state: _AdmissionState) -> None:
    from treesight.storage.cosmos import EtagPreconditionFailedError, replace_item_with_etag

    try:
        replace_item_with_etag(container_name, state.doc, etag=state.etag)
    except EtagPreconditionFailedError as exc:
        raise AdmissionUnavailableError("admission etag conflict") from exc


def _ensure_state_doc(container_name: str) -> None:
    from treesight.storage.cosmos import upsert_item

    upsert_item(container_name, _admission_doc())


def reserve_admission_slot(
    instance_id: str,
    *,
    container_name: str = COSMOS_CONTAINER_RUNS,
) -> bool:
    """Atomically reserve one active-run admission slot.

    Returns False when cap is reached, True when admitted.
    Raises :class:`AdmissionUnavailableError` when Cosmos is configured but
    cannot be used safely (fail-closed policy).
    """
    from treesight import config
    from treesight.storage import cosmos as _cosmos

    cap = config.MAX_CONCURRENT_JOBS
    if cap <= 0:
        return True
    if not _cosmos.cosmos_available():
        logger.warning("admission_slots_degraded mode=fail_open reason=cosmos_unavailable")
        return True

    window_minutes = max(1, int(config.MAX_JOB_DURATION_MINUTES))
    now = _now()
    last_error: Exception | None = None

    for _ in range(_MAX_ADMISSION_ETAG_RETRIES):
        try:
            loaded = _load_state(container_name)
            if loaded is None:
                _ensure_state_doc(container_name)
                continue

            slots = dict(loaded.doc.get("active_slots") or {})
            _prune_stale_slots(slots, now=now, window_minutes=window_minutes, mode="cosmos")

            if instance_id in slots:
                return True

            active = len(slots)
            if active >= cap:
                logger.info(
                    "admission_slot_denied reason=cap_reached active=%d cap=%d",
                    active,
                    cap,
                )
                if slots != loaded.doc.get("active_slots"):
                    loaded.doc["active_slots"] = slots
                    loaded.doc["updated_at"] = now.isoformat()
                    try:
                        _replace_state(container_name, loaded)
                    except AdmissionUnavailableError:
                        logger.debug("admission_slot_denied stale-save conflict; returning denial")
                return False

            slots[instance_id] = now.isoformat()
            loaded.doc["active_slots"] = slots
            loaded.doc["updated_at"] = now.isoformat()
            _replace_state(container_name, loaded)
            return True
        except AdmissionUnavailableError as exc:
            last_error = exc
            continue
        except Exception as exc:
            logger.exception("admission_slot_unavailable mode=fail_closed")
            raise AdmissionUnavailableError("admission storage unavailable") from exc

    raise AdmissionUnavailableError(f"admission etag retries exhausted (last={last_error})")


def release_admission_slot(
    instance_id: str,
    *,
    container_name: str = COSMOS_CONTAINER_RUNS,
) -> bool:
    """Release a previously reserved admission slot.

    Returns True when a slot was removed. Unknown instance IDs are treated as
    no-op releases, but storage failures can still raise
    :class:`AdmissionUnavailableError`.
    """
    from treesight import config
    from treesight.storage import cosmos as _cosmos

    if not instance_id:
        return False
    if config.MAX_CONCURRENT_JOBS <= 0:
        return False
    if not _cosmos.cosmos_available():
        return False

    window_minutes = max(1, int(config.MAX_JOB_DURATION_MINUTES))
    now = _now()
    last_error: Exception | None = None

    for _ in range(_MAX_ADMISSION_ETAG_RETRIES):
        try:
            loaded = _load_state(container_name)
            if loaded is None:
                return False

            slots = dict(loaded.doc.get("active_slots") or {})
            _prune_stale_slots(slots, now=now, window_minutes=window_minutes, mode="cosmos")
            removed = slots.pop(instance_id, None) is not None
            if not removed and slots == loaded.doc.get("active_slots"):
                return False
            loaded.doc["active_slots"] = slots
            loaded.doc["updated_at"] = now.isoformat()
            _replace_state(container_name, loaded)
            return removed
        except AdmissionUnavailableError as exc:
            last_error = exc
            continue
        except Exception as exc:
            logger.exception("admission_release_unavailable")
            raise AdmissionUnavailableError("admission release unavailable") from exc

    raise AdmissionUnavailableError(f"admission release retries exhausted (last={last_error})")


def count_active_runs(container_name: str = COSMOS_CONTAINER_RUNS) -> int:
    """Return the number of currently reserved active admission slots."""
    from treesight import config
    from treesight.storage import cosmos as _cosmos

    if not _cosmos.cosmos_available():
        return 0

    try:
        loaded = _load_state(container_name)
        if loaded is None:
            return 0
        slots = dict(loaded.doc.get("active_slots") or {})
        window_minutes = max(1, int(config.MAX_JOB_DURATION_MINUTES))
        now = _now()
        pruned = _prune_stale_slots(slots, now=now, window_minutes=window_minutes, mode="cosmos")
        if pruned:
            loaded.doc["active_slots"] = slots
            loaded.doc["updated_at"] = now.isoformat()
            try:
                _replace_state(container_name, loaded)
            except AdmissionUnavailableError:
                logger.debug("count_active_runs prune save conflict; returning live count")
        return len(slots)
    except Exception:
        logger.exception("count_active_runs failed")
        return 0


def at_concurrency_cap(container_name: str = COSMOS_CONTAINER_RUNS) -> bool:
    """Return True when active run count is at or above MAX_CONCURRENT_JOBS."""
    from treesight import config

    cap = config.MAX_CONCURRENT_JOBS
    if cap <= 0:
        return False
    return count_active_runs(container_name) >= cap
