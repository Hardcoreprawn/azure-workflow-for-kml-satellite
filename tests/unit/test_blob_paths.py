"""Tests for deterministic blob path generation (PID 7.4.4, Section 10.1).

Covers:
- sanitise_slug: edge cases, special characters, unicode
- build_kml_archive_path: format, determinism
- build_metadata_path: format, determinism
- build_clipped_imagery_path: format, determinism, slug sanitisation
- Path hierarchy: {prefix}/{YYYY}/{MM}/{project-slug}/{name}.{ext}
"""

from __future__ import annotations

from datetime import UTC, datetime

from kml_satellite.utils.blob_paths import (
    IMAGERY_CLIPPED_PREFIX,
    KML_PREFIX,
    METADATA_PREFIX,
    build_clipped_imagery_path,
    build_kml_archive_path,
    build_metadata_path,
    sanitise_slug,
)

# ===========================================================================
# sanitise_slug
# ===========================================================================


class TestSanitiseSlug:
    """Test the slug sanitisation function."""

    def test_simple_lowercase(self) -> None:
        assert sanitise_slug("hello") == "hello"

    def test_uppercase_to_lowercase(self) -> None:
        assert sanitise_slug("Hello World") == "hello-world"

    def test_special_characters_removed(self) -> None:
        assert sanitise_slug("Block A (Fuji)") == "block-a-fuji"

    def test_multiple_spaces_to_single_hyphen(self) -> None:
        assert sanitise_slug("Alpha   Orchard") == "alpha-orchard"

    def test_leading_trailing_whitespace(self) -> None:
        assert sanitise_slug("  trimmed  ") == "trimmed"

    def test_empty_string_returns_unknown(self) -> None:
        assert sanitise_slug("") == "unknown"

    def test_only_special_chars_returns_unknown(self) -> None:
        assert sanitise_slug("@#$%^&*()") == "unknown"

    def test_hyphens_preserved(self) -> None:
        assert sanitise_slug("alpha-orchard") == "alpha-orchard"

    def test_underscores_removed(self) -> None:
        """Underscores are not in the allowed charset; they are stripped."""
        assert sanitise_slug("my_orchard") == "myorchard"

    def test_numbers_preserved(self) -> None:
        assert sanitise_slug("block-42") == "block-42"

    def test_consecutive_hyphens_collapsed(self) -> None:
        assert sanitise_slug("a---b") == "a-b"

    def test_leading_trailing_hyphens_stripped(self) -> None:
        assert sanitise_slug("-hello-") == "hello"


# ===========================================================================
# build_kml_archive_path
# ===========================================================================


class TestBuildKmlArchivePath:
    """Test KML archive blob path generation."""

    def test_basic_path(self) -> None:
        """Standard path follows PID Section 10.1 format."""
        ts = datetime(2026, 2, 16, tzinfo=UTC)
        path = build_kml_archive_path("orchard_alpha.kml", "Alpha Orchard", timestamp=ts)
        assert path == f"{KML_PREFIX}/2026/02/alpha-orchard/orchardalpha.kml"

    def test_deterministic(self) -> None:
        """Same inputs produce exactly the same output (PID 7.4.4)."""
        ts = datetime(2026, 1, 5, tzinfo=UTC)
        path1 = build_kml_archive_path("test.kml", "Farm", timestamp=ts)
        path2 = build_kml_archive_path("test.kml", "Farm", timestamp=ts)
        assert path1 == path2

    def test_year_month_segments(self) -> None:
        """Path includes zero-padded YYYY/MM."""
        ts = datetime(2026, 3, 1, tzinfo=UTC)
        path = build_kml_archive_path("x.kml", "y", timestamp=ts)
        assert "/2026/03/" in path

    def test_project_name_sanitised(self) -> None:
        """Project name with special chars is slugified."""
        ts = datetime(2026, 6, 15, tzinfo=UTC)
        path = build_kml_archive_path("f.kml", "O'Brien's Farm!", timestamp=ts)
        assert "obriens-farm" in path

    def test_starts_with_prefix(self) -> None:
        """Path starts with the KML prefix constant."""
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        path = build_kml_archive_path("f.kml", "o", timestamp=ts)
        assert path.startswith(f"{KML_PREFIX}/")

    def test_ends_with_kml_extension(self) -> None:
        """Path always ends with .kml."""
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        path = build_kml_archive_path("data.kml", "test", timestamp=ts)
        assert path.endswith(".kml")


# ===========================================================================
# build_metadata_path
# ===========================================================================


class TestBuildMetadataPath:
    """Test metadata JSON blob path generation."""

    def test_basic_path(self) -> None:
        """Standard path follows PID Section 10.1 format."""
        ts = datetime(2026, 2, 16, tzinfo=UTC)
        path = build_metadata_path("Block A", "Alpha Orchard", timestamp=ts)
        assert path == f"{METADATA_PREFIX}/2026/02/alpha-orchard/block-a.json"

    def test_deterministic(self) -> None:
        """Same inputs produce exactly the same output (PID 7.4.4)."""
        ts = datetime(2026, 7, 20, tzinfo=UTC)
        path1 = build_metadata_path("F1", "Farm", timestamp=ts)
        path2 = build_metadata_path("F1", "Farm", timestamp=ts)
        assert path1 == path2

    def test_starts_with_prefix(self) -> None:
        """Path starts with the metadata prefix constant."""
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        path = build_metadata_path("f", "o", timestamp=ts)
        assert path.startswith(f"{METADATA_PREFIX}/")

    def test_ends_with_json_extension(self) -> None:
        """Path always ends with .json."""
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        path = build_metadata_path("feature", "orchard", timestamp=ts)
        assert path.endswith(".json")

    def test_feature_name_sanitised(self) -> None:
        """Feature name with spaces and specials is slugified."""
        ts = datetime(2026, 5, 1, tzinfo=UTC)
        path = build_metadata_path("Block A (polygon 2)", "Orchard", timestamp=ts)
        assert "block-a-polygon-2" in path

    def test_missing_project_name(self) -> None:
        """Empty project name falls back to 'unknown'."""
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        path = build_metadata_path("F1", "", timestamp=ts)
        assert "/unknown/" in path

    def test_year_month_in_path(self) -> None:
        """Different months produce different paths."""
        ts_jan = datetime(2026, 1, 15, tzinfo=UTC)
        ts_dec = datetime(2026, 12, 25, tzinfo=UTC)
        path_jan = build_metadata_path("f", "o", timestamp=ts_jan)
        path_dec = build_metadata_path("f", "o", timestamp=ts_dec)
        assert "/01/" in path_jan
        assert "/12/" in path_dec
        assert path_jan != path_dec


# ===========================================================================
# build_clipped_imagery_path
# ===========================================================================


class TestBuildClippedImageryPath:
    """Test clipped imagery blob path generation (PID FR-4.3)."""

    def test_basic_path(self) -> None:
        """Standard path follows PID Section 10.1 format."""
        ts = datetime(2026, 3, 15, tzinfo=UTC)
        path = build_clipped_imagery_path("Block A", "Alpha Orchard", timestamp=ts)
        assert path == f"{IMAGERY_CLIPPED_PREFIX}/2026/03/alpha-orchard/block-a.tif"

    def test_deterministic(self) -> None:
        """Same inputs produce exactly the same output (PID 7.4.4)."""
        ts = datetime(2026, 7, 20, tzinfo=UTC)
        path1 = build_clipped_imagery_path("F1", "Farm", timestamp=ts)
        path2 = build_clipped_imagery_path("F1", "Farm", timestamp=ts)
        assert path1 == path2

    def test_starts_with_prefix(self) -> None:
        """Path starts with the clipped imagery prefix constant."""
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        path = build_clipped_imagery_path("f", "o", timestamp=ts)
        assert path.startswith(f"{IMAGERY_CLIPPED_PREFIX}/")

    def test_ends_with_tif_extension(self) -> None:
        """Path always ends with .tif."""
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        path = build_clipped_imagery_path("feature", "orchard", timestamp=ts)
        assert path.endswith(".tif")

    def test_feature_name_sanitised(self) -> None:
        """Feature name with spaces and specials is slugified."""
        ts = datetime(2026, 5, 1, tzinfo=UTC)
        path = build_clipped_imagery_path("Block A (polygon 2)", "Orchard", timestamp=ts)
        assert "block-a-polygon-2" in path

    def test_missing_project_name(self) -> None:
        """Empty project name falls back to 'unknown'."""
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        path = build_clipped_imagery_path("F1", "", timestamp=ts)
        assert "/unknown/" in path

    def test_year_month_in_path(self) -> None:
        """Different months produce different paths."""
        ts_jan = datetime(2026, 1, 15, tzinfo=UTC)
        ts_dec = datetime(2026, 12, 25, tzinfo=UTC)
        path_jan = build_clipped_imagery_path("f", "o", timestamp=ts_jan)
        path_dec = build_clipped_imagery_path("f", "o", timestamp=ts_dec)
        assert "/01/" in path_jan
        assert "/12/" in path_dec
        assert path_jan != path_dec
