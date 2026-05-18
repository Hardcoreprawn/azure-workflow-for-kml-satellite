"""Generalised feature flag evaluator for production rollout control.

Spec: docs/PRODUCTION_ROLLOUT_SPEC.md §6 Feature Evaluation Rules.

Evaluation order (strict, fail-closed):
  1. kill_switch is true → disabled
  2. flag document missing or unreadable → disabled
  3. valid per-user override exists → return override decision
  4. status is ``off`` or ``blocked`` → disabled
  5. status is ``preview_only`` → enabled only for explicit override
  6. status is ``percentage_rollout`` → deterministic bucket check
  7. status is ``on`` → enabled

Anonymous users (``None`` or ``"anonymous"``) are blocked unless the flag
document explicitly sets ``allow_anonymous=true``.

Storage:
  - ``feature_flags`` Cosmos container — keyed by ``feature_name``
  - ``feature_flag_overrides`` Cosmos container — keyed by ``user_id``

Both containers partition on the same key used for the document id.
The evaluator fails closed whenever either read raises an exception or
returns a document with unexpected structure.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("treesight.security.rollout")

_FLAGS_CONTAINER = "feature_flags"
_OVERRIDES_CONTAINER = "feature_flag_overrides"

# Status values defined in spec §5.3
_STATUS_OFF = "off"
_STATUS_PREVIEW_ONLY = "preview_only"
_STATUS_PERCENTAGE_ROLLOUT = "percentage_rollout"
_STATUS_ON = "on"
_STATUS_BLOCKED = "blocked"


# ---------------------------------------------------------------------------
# Internal storage readers — thin wrappers that can be patched in tests
# ---------------------------------------------------------------------------


def _read_flag(feature_name: str) -> dict[str, Any] | None:
    """Return the feature flag document for *feature_name*, or ``None``."""
    from treesight.storage.cosmos import cosmos_available, read_item

    if not cosmos_available():
        return None
    return read_item(_FLAGS_CONTAINER, feature_name, feature_name)


def _read_override(user_id: str) -> dict[str, Any] | None:
    """Return the per-user override document for *user_id*, or ``None``."""
    from treesight.storage.cosmos import cosmos_available, read_item

    if not cosmos_available():
        return None
    return read_item(_OVERRIDES_CONTAINER, user_id, user_id)


# ---------------------------------------------------------------------------
# Bucketing (spec §6.3)
# ---------------------------------------------------------------------------


def _rollout_bucket(feature_name: str, user_id: str) -> int:
    """Return a deterministic bucket in [0, 100) for the feature/user pair.

    Uses ``sha256("{feature_name}:{user_id}") % 100``.
    """
    digest = hashlib.sha256(f"{feature_name}:{user_id}".encode()).hexdigest()
    return int(digest, 16) % 100


# ---------------------------------------------------------------------------
# Public evaluator
# ---------------------------------------------------------------------------


def is_feature_enabled(feature_name: str, user_id: str | None) -> bool:
    """Return ``True`` if *feature_name* is enabled for *user_id*.

    Always returns ``False`` on any unhandled exception (fail-closed).

    Args:
        feature_name: The logical name of the feature to evaluate.
        user_id: The authenticated user id, or ``None`` / ``"anonymous"``.

    Returns:
        ``True`` if the feature is enabled for this user, ``False`` otherwise.
    """
    try:
        return _evaluate(feature_name, user_id)
    except Exception:
        logger.exception(
            "feature_eval_failed feature=%s user=%s",
            feature_name,
            user_id,
            extra={"event": "feature_eval_failed", "feature": feature_name, "user": user_id},
        )
        return False


def _check_override(feature_name: str, user_id: str) -> bool | None:
    """Return override decision for *user_id*, or ``None`` if no override applies.

    Raises on storage read failure — propagates to ``is_feature_enabled`` to
    preserve fail-closed behaviour (any unreadable state → disabled).

    Returns ``None`` for absent, expired, or malformed override entries so
    the evaluator falls through to flag-level status rules.
    """
    override_doc = _read_override(user_id)

    if not override_doc:
        return None
    feature_overrides: dict = override_doc.get("features", {})
    if feature_name not in feature_overrides:
        return None

    entry: dict = feature_overrides[feature_name]

    # Honour expiry: an expired override is treated as absent.
    expires_at = entry.get("expires_at")
    if expires_at:
        try:
            expiry = datetime.fromisoformat(expires_at)
            # Normalise to UTC when the stored value is offset-aware.
            now = datetime.now(tz=UTC)
            if expiry.tzinfo is not None:
                if now >= expiry:
                    return None
            else:
                if datetime.utcnow() >= expiry:
                    return None
        except (ValueError, TypeError):
            # Malformed expires_at — treat override as absent (fail-closed).
            logger.warning(
                "malformed expires_at in override user=%s feature=%s; ignoring",
                user_id,
                feature_name,
            )
            return None

    return bool(entry.get("enabled", False))


def _evaluate(feature_name: str, user_id: str | None) -> bool:
    """Inner evaluator — may raise; callers must handle exceptions."""
    is_anonymous = not user_id or user_id == "anonymous"

    # ── Rule 2: read flag document; treat missing/unreadable as disabled ──
    try:
        flag = _read_flag(feature_name)
    except Exception:
        logger.warning(
            "feature flag read failed feature=%s; disabling",
            feature_name,
            exc_info=True,
        )
        return False

    if not flag:
        return False

    # ── Rule 1: kill_switch beats everything ──────────────────────────────
    if flag.get("kill_switch"):
        return False

    # ── Rule 4 (early): anonymous gating ─────────────────────────────────
    # Anonymous users are blocked unless the flag explicitly permits them.
    if is_anonymous and not flag.get("allow_anonymous"):
        return False

    # ── Rule 3: per-user override ─────────────────────────────────────────
    if not is_anonymous and user_id:
        override = _check_override(feature_name, user_id)
        if override is not None:
            return override

    # ── Rule 4: off / blocked ─────────────────────────────────────────────
    status = flag.get("status", _STATUS_OFF)
    if status in (_STATUS_OFF, _STATUS_BLOCKED):
        return False

    # ── Rule 5: preview_only — only explicit overrides reach here for non-anon ──
    # For anonymous users with allow_anonymous=True and a preview_only feature,
    # we have no override mechanism → disabled.
    if status == _STATUS_PREVIEW_ONLY:
        return False

    # ── Rule 6: percentage_rollout ────────────────────────────────────────
    if status == _STATUS_PERCENTAGE_ROLLOUT:
        rollout_pct = int(flag.get("rollout_pct", 0))
        if not (0 <= rollout_pct <= 100):
            logger.warning(
                "invalid rollout_pct=%d feature=%s; disabling",
                rollout_pct,
                feature_name,
            )
            return False
        bucket = _rollout_bucket(feature_name, user_id or "anonymous")
        return bucket < rollout_pct

    # ── Rule 7: on ────────────────────────────────────────────────────────
    if status == _STATUS_ON:
        return True

    # Unknown status → fail closed
    logger.warning("unknown feature status=%s feature=%s; disabling", status, feature_name)
    return False
