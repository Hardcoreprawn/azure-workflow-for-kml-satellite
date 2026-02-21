"""Deterministic blob path generation for the KML satellite pipeline.

Generates output paths conforming to PID Section 10.1:

    kml/{YYYY}/{MM}/{project-name}/{filename}.kml
    metadata/{YYYY}/{MM}/{project-name}/{feature-name}.json

All path components are sanitised to lowercase slug form: only ``a-z``,
``0-9``, and ``-`` are allowed.  Spaces become hyphens; other characters
are stripped.

Engineering standards:
- PID 7.4.4 Idempotent: same input always produces the same path.
- PID 7.4.5 Explicit: constants for path prefixes, no inline literals.
- PID 7.4.8 Defensive: missing names fall back to ``"unknown"``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

# ---------------------------------------------------------------------------
# Path prefixes (PID 7.4.5: no magic strings)
# ---------------------------------------------------------------------------

KML_PREFIX = "kml"
METADATA_PREFIX = "metadata"
IMAGERY_RAW_PREFIX = "imagery/raw"
IMAGERY_CLIPPED_PREFIX = "imagery/clipped"

# Regex for sanitising path segments (allow only lowercase alphanumeric + hyphen)
_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def sanitise_slug(value: str) -> str:
    """Convert a string to a URL/path-safe slug.

    - Lowercase
    - Spaces → hyphens
    - Strips all characters except ``a-z``, ``0-9``, ``-``
    - Collapses consecutive hyphens
    - Falls back to ``"unknown"`` if the result is empty

    Args:
        value: Raw string to sanitise.

    Returns:
        A non-empty slug string.
    """
    slug = value.lower().strip().replace(" ", "-")
    slug = _SLUG_RE.sub("", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug if slug else "unknown"


def build_kml_archive_path(
    source_filename: str,
    project_name: str,
    *,
    timestamp: datetime | None = None,
) -> str:
    """Build the blob path for archiving the original KML file.

    Format: ``kml/{YYYY}/{MM}/{project-name}/{filename}.kml``

    Args:
        source_filename: Original KML filename (e.g. ``"orchard_alpha.kml"``).
        project_name: Project name (will be sanitised).
        timestamp: Processing timestamp. Defaults to current UTC time.

    Returns:
        Deterministic blob path string (PID 7.4.4).
    """
    ts = timestamp or datetime.now(UTC)
    year = f"{ts.year:04d}"
    month = f"{ts.month:02d}"
    project_slug = sanitise_slug(project_name)
    filename_slug = sanitise_slug(source_filename.removesuffix(".kml")) + ".kml"
    return f"{KML_PREFIX}/{year}/{month}/{project_slug}/{filename_slug}"


def build_metadata_path(
    feature_name: str,
    project_name: str,
    *,
    timestamp: datetime | None = None,
) -> str:
    """Build the blob path for a metadata JSON document.

    Format: ``metadata/{YYYY}/{MM}/{project-name}/{feature-name}.json``

    Args:
        feature_name: Feature/Placemark name (will be sanitised).
        project_name: Project name (will be sanitised).
        timestamp: Processing timestamp. Defaults to current UTC time.

    Returns:
        Deterministic blob path string (PID 7.4.4).
    """
    ts = timestamp or datetime.now(UTC)
    year = f"{ts.year:04d}"
    month = f"{ts.month:02d}"
    project_slug = sanitise_slug(project_name)
    feature_slug = sanitise_slug(feature_name) + ".json"
    return f"{METADATA_PREFIX}/{year}/{month}/{project_slug}/{feature_slug}"


def build_imagery_path(
    feature_name: str,
    project_name: str,
    *,
    timestamp: datetime | None = None,
) -> str:
    """Build the blob path for raw imagery (GeoTIFF).

    Format: ``imagery/raw/{YYYY}/{MM}/{project-name}/{feature-name}.tif``

    Args:
        feature_name: Feature/Placemark name (will be sanitised).
        project_name: Project name (will be sanitised).
        timestamp: Processing timestamp. Defaults to current UTC time.

    Returns:
        Deterministic blob path string (PID 7.4.4).

    References:
        PID FR-4.2 (store raw imagery under ``/imagery/raw/``)
        PID Section 10.1 (Container & Path Layout)
    """
    ts = timestamp or datetime.now(UTC)
    year = f"{ts.year:04d}"
    month = f"{ts.month:02d}"
    project_slug = sanitise_slug(project_name)
    feature_slug = sanitise_slug(feature_name) + ".tif"
    return f"{IMAGERY_RAW_PREFIX}/{year}/{month}/{project_slug}/{feature_slug}"


def build_clipped_imagery_path(
    feature_name: str,
    project_name: str,
    *,
    timestamp: datetime | None = None,
) -> str:
    """Build the blob path for clipped (post-processed) imagery.

    Format: ``imagery/clipped/{YYYY}/{MM}/{project-name}/{feature-name}.tif``

    Args:
        feature_name: Feature/Placemark name (will be sanitised).
        project_name: Project name (will be sanitised).
        timestamp: Processing timestamp. Defaults to current UTC time.

    Returns:
        Deterministic blob path string (PID 7.4.4).

    References:
        PID FR-4.3 (store clipped imagery under ``/imagery/clipped/``)
        PID Section 10.1 (Container & Path Layout)
    """
    ts = timestamp or datetime.now(UTC)
    year = f"{ts.year:04d}"
    month = f"{ts.month:02d}"
    project_slug = sanitise_slug(project_name)
    feature_slug = sanitise_slug(feature_name) + ".tif"
    return f"{IMAGERY_CLIPPED_PREFIX}/{year}/{month}/{project_slug}/{feature_slug}"
