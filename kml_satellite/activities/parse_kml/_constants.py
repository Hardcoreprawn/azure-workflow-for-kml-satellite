"""Shared constants for KML parsing (Issue #60)."""

from __future__ import annotations

# KML 2.2 namespace
KML_NAMESPACE = "http://www.opengis.net/kml/2.2"

# WGS 84 coordinate bounds (PID 7.4.3)
MIN_LONGITUDE = -180.0
MAX_LONGITUDE = 180.0
MIN_LATITUDE = -90.0
MAX_LATITUDE = 90.0

# Minimum vertices for a valid polygon (3 distinct + closing = 4)
MIN_POLYGON_VERTICES = 4
