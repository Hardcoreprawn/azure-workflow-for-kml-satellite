"""Tests for KML parsers — lxml fallback parser (§7.1).

Fiona parser requires GDAL, so we focus on lxml which is always available.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest

from treesight.parsers import maybe_unzip
from treesight.parsers.lxml_parser import parse_kml_lxml


class TestLxmlParser:
    def test_parse_two_placemarks(self, sample_kml_bytes: bytes):
        features = parse_kml_lxml(sample_kml_bytes, source_file="sample.kml")
        assert len(features) == 2

    def test_first_feature_name(self, sample_kml_bytes: bytes):
        features = parse_kml_lxml(sample_kml_bytes, source_file="sample.kml")
        assert features[0].name == "Block A - Fuji Apple"

    def test_second_feature_name(self, sample_kml_bytes: bytes):
        features = parse_kml_lxml(sample_kml_bytes, source_file="sample.kml")
        assert features[1].name == "Block B - Macadamia"

    def test_extended_data_parsed(self, sample_kml_bytes: bytes):
        features = parse_kml_lxml(sample_kml_bytes, source_file="sample.kml")
        assert features[0].metadata.get("crop") == "apple"
        assert features[0].metadata.get("variety") == "fuji"

    def test_exterior_coords_count(self, sample_kml_bytes: bytes):
        features = parse_kml_lxml(sample_kml_bytes, source_file="sample.kml")
        # 5 coords (closed ring)
        assert len(features[0].exterior_coords) == 5

    def test_coords_are_lon_lat(self, sample_kml_bytes: bytes):
        features = parse_kml_lxml(sample_kml_bytes, source_file="sample.kml")
        first = features[0].exterior_coords[0]
        assert first[0] == pytest.approx(36.8)  # lon
        assert first[1] == pytest.approx(-1.3)  # lat

    def test_polygon_closed(self, sample_kml_bytes: bytes):
        features = parse_kml_lxml(sample_kml_bytes, source_file="sample.kml")
        coords = features[0].exterior_coords
        assert coords[0] == coords[-1]

    def test_source_file_set(self, sample_kml_bytes: bytes):
        features = parse_kml_lxml(sample_kml_bytes, source_file="test.kml")
        assert all(f.source_file == "test.kml" for f in features)

    def test_feature_index_sequential(self, sample_kml_bytes: bytes):
        features = parse_kml_lxml(sample_kml_bytes, source_file="sample.kml")
        assert features[0].feature_index == 0
        assert features[1].feature_index == 1

    def test_crs_always_epsg4326(self, sample_kml_bytes: bytes):
        features = parse_kml_lxml(sample_kml_bytes, source_file="sample.kml")
        assert all(f.crs == "EPSG:4326" for f in features)

    def test_empty_kml_returns_empty(self):
        kml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2"><Document></Document></kml>"""
        assert parse_kml_lxml(kml) == []

    def test_description_parsed(self, sample_kml_bytes: bytes):
        features = parse_kml_lxml(sample_kml_bytes, source_file="sample.kml")
        assert features[0].description == "Test orchard block"

    def test_polygon_with_less_than_3_coords_skipped(self):
        """A polygon with < 3 vertices should be skipped."""
        kml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
          <Document>
            <Placemark>
              <name>Bad</name>
              <Polygon>
                <outerBoundaryIs>
                  <LinearRing>
                    <coordinates>36.8,-1.3,0 36.81,-1.3,0</coordinates>
                  </LinearRing>
                </outerBoundaryIs>
              </Polygon>
            </Placemark>
          </Document>
        </kml>"""
        features = parse_kml_lxml(kml)
        assert len(features) == 0


def _make_kmz(kml_bytes: bytes, entry_name: str = "doc.kml") -> bytes:
    """Create an in-memory KMZ (ZIP) containing *kml_bytes* at *entry_name*."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(entry_name, kml_bytes)
    return buf.getvalue()


class TestMaybeUnzip:
    """Tests for ``maybe_unzip`` — KMZ (ZIP) detection and extraction."""

    def test_plain_kml_passthrough(self, sample_kml_bytes: bytes):
        result = maybe_unzip(sample_kml_bytes)
        assert result == sample_kml_bytes

    def test_kmz_with_doc_kml(self, sample_kml_bytes: bytes):
        kmz = _make_kmz(sample_kml_bytes, "doc.kml")
        result = maybe_unzip(kmz)
        assert result == sample_kml_bytes

    def test_kmz_with_alternate_name(self, sample_kml_bytes: bytes):
        kmz = _make_kmz(sample_kml_bytes, "my_region.kml")
        result = maybe_unzip(kmz)
        assert result == sample_kml_bytes

    def test_kmz_prefers_doc_kml(self, sample_kml_bytes: bytes):
        """When both doc.kml and another .kml exist, doc.kml wins."""
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("doc.kml", sample_kml_bytes)
            zf.writestr("other.kml", b"<kml/>")
        result = maybe_unzip(buf.getvalue())
        assert result == sample_kml_bytes

    def test_kmz_no_kml_raises(self):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", b"nothing here")
        with pytest.raises(ValueError, match=r"no .kml file"):
            maybe_unzip(buf.getvalue())

    def test_kmz_round_trip_parse(self, sample_kml_bytes: bytes):
        """KMZ bytes → maybe_unzip → parse_kml_lxml produces features."""
        kmz = _make_kmz(sample_kml_bytes)
        kml = maybe_unzip(kmz)
        features = parse_kml_lxml(kml, source_file="test.kmz")
        assert len(features) == 2


# ---------------------------------------------------------------------------
# Zip-bomb / decompression-bomb protection
# ---------------------------------------------------------------------------


class TestZipBombProtection:
    """Tests for ``maybe_unzip`` rejection of malicious archives."""

    def test_rejects_zip_bomb(self):
        """Archive whose decompressed content exceeds the limit is rejected."""
        from treesight.constants import MAX_KMZ_DECOMPRESSED_BYTES

        oversized = b"A" * (MAX_KMZ_DECOMPRESSED_BYTES + 1)
        kmz = _make_kmz(oversized, "doc.kml")
        with pytest.raises(ValueError, match=r"[Dd]ecompressed size"):
            maybe_unzip(kmz)

    def test_rejects_high_compression_ratio(self):
        """Archive with suspiciously high compression ratio is rejected."""
        from treesight.constants import MAX_KMZ_COMPRESSION_RATIO

        # Long run of zeros — compresses extremely well.
        payload_size = 10_000_000  # 10 MB of zeros
        payload = b"\x00" * payload_size
        kmz = _make_kmz(payload, "doc.kml")

        compressed_size = len(kmz)
        ratio = payload_size / compressed_size
        if ratio <= MAX_KMZ_COMPRESSION_RATIO:
            pytest.skip(f"Ratio {ratio:.0f} not above {MAX_KMZ_COMPRESSION_RATIO}")

        with pytest.raises(ValueError, match=r"[Cc]ompression ratio"):
            maybe_unzip(kmz)

    def test_rejects_too_many_files(self):
        """Archive with too many entries is rejected."""
        from treesight.constants import MAX_KMZ_FILE_COUNT

        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for i in range(MAX_KMZ_FILE_COUNT + 1):
                zf.writestr(f"file_{i}.kml", b"<kml/>")
        with pytest.raises(ValueError, match=r"[Ff]ile count"):
            maybe_unzip(buf.getvalue())

    def test_rejects_nested_zip(self):
        """Archive containing another ZIP is not recursed into."""
        inner_kmz = _make_kmz(b"<kml/>", "doc.kml")
        outer = _make_kmz(inner_kmz, "doc.kml")
        # After extracting the outer ZIP, the content starts with PK magic.
        # maybe_unzip must not recurse — it returns the inner zip bytes.
        result = maybe_unzip(outer)
        assert result.startswith(b"PK")

    def test_accepts_normal_kmz(self, sample_kml_bytes: bytes):
        """A normal-sized KMZ passes all checks."""
        kmz = _make_kmz(sample_kml_bytes)
        result = maybe_unzip(kmz)
        assert result == sample_kml_bytes


# ---------------------------------------------------------------------------
# KML input validation
# ---------------------------------------------------------------------------


class TestKmlInputValidation:
    """Tests for ``validate_kml_bytes`` — structural validation before parsing."""

    def test_rejects_malformed_xml(self):
        from treesight.parsers import validate_kml_bytes

        bad_xml = b"<kml><this is not xml"
        with pytest.raises(ValueError, match=r"[Mm]alformed|[Nn]ot well-formed|XML"):
            validate_kml_bytes(bad_xml)

    def test_rejects_missing_kml_namespace(self):
        from treesight.parsers import validate_kml_bytes

        no_ns = b'<?xml version="1.0"?><root><child/></root>'
        with pytest.raises(ValueError, match=r"[Nn]amespace|KML"):
            validate_kml_bytes(no_ns)

    def test_rejects_dtd_declaration(self):
        from treesight.parsers import validate_kml_bytes

        with_dtd = b"""<?xml version="1.0"?>
        <!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
        <kml xmlns="http://www.opengis.net/kml/2.2">
          <Document><name>&xxe;</name></Document>
        </kml>"""
        with pytest.raises(ValueError, match=r"DOCTYPE|DTD|[Ee]ntit"):
            validate_kml_bytes(with_dtd)

    def test_rejects_entity_expansion(self):
        """Billion-laughs-style entity expansion is rejected."""
        from treesight.parsers import validate_kml_bytes

        billion_laughs = b"""<?xml version="1.0"?>
        <!DOCTYPE lolz [
          <!ENTITY lol "lol">
          <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
        ]>
        <kml xmlns="http://www.opengis.net/kml/2.2">
          <Document><name>&lol2;</name></Document>
        </kml>"""
        with pytest.raises(ValueError, match=r"DOCTYPE|DTD|[Ee]ntit"):
            validate_kml_bytes(billion_laughs)

    def test_accepts_valid_kml(self, sample_kml_bytes: bytes):
        from treesight.parsers import validate_kml_bytes

        # Should not raise
        validate_kml_bytes(sample_kml_bytes)

    def test_accepts_google_extensions_namespace(self):
        from treesight.parsers import validate_kml_bytes

        kml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2"
             xmlns:gx="http://www.google.com/kml/ext/2.2">
          <Document><name>Test</name></Document>
        </kml>"""
        validate_kml_bytes(kml)

    def test_accepts_kml_22_namespace(self):
        from treesight.parsers import validate_kml_bytes

        kml = b"""<?xml version="1.0"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
          <Document><name>Test</name></Document>
        </kml>"""
        validate_kml_bytes(kml)


class TestFionaParserTimeout:
    """Fiona parser timeout and fallback behavior (\u00a77.1)."""

    def test_fiona_timeout_raises_timeout_error(self, sample_kml_bytes: bytes, monkeypatch):
        """parse_kml_fiona raises TimeoutError when GDAL hangs past the deadline."""
        import time

        import treesight.parsers.fiona_parser as fp_module

        def _slow_open(tmp_path: str, source_file: str) -> list:
            time.sleep(0.5)  # longer than 0.1s deadline; shorter than 5s (keeps tests fast)
            return []

        monkeypatch.setattr(fp_module, "_fiona_open_and_collect", _slow_open)
        monkeypatch.setattr(fp_module, "_FIONA_TIMEOUT_SECONDS", 0.1)

        with pytest.raises(TimeoutError, match="timed out"):
            fp_module.parse_kml_fiona(sample_kml_bytes)

    def test_ingestion_falls_back_to_lxml_on_fiona_timeout(
        self, sample_kml_bytes: bytes, monkeypatch
    ):
        """When Fiona times out, parse_kml_from_blob falls back to lxml successfully."""
        import time
        from unittest.mock import MagicMock

        import treesight.parsers.fiona_parser as fp_module
        from treesight.models.blob_event import BlobEvent
        from treesight.pipeline.ingestion import parse_kml_from_blob

        def _slow_open(tmp_path: str, source_file: str) -> list:
            time.sleep(0.5)
            return []

        monkeypatch.setattr(fp_module, "_fiona_open_and_collect", _slow_open)
        monkeypatch.setattr(fp_module, "_FIONA_TIMEOUT_SECONDS", 0.1)

        storage = MagicMock()
        storage.download_bytes.return_value = sample_kml_bytes
        blob_event = BlobEvent(
            blob_url="https://teststorage.blob.core.windows.net/kml-input/analysis/test.kml",
            container_name="kml-input",
            blob_name="analysis/test.kml",
            content_length=len(sample_kml_bytes),
            content_type="application/vnd.google-earth.kml+xml",
            event_time="2025-01-15T10:30:00Z",
            correlation_id="test-123",
        )

        features = parse_kml_from_blob(blob_event, storage)
        assert len(features) >= 1  # lxml fallback parsed at least one feature


# ---------------------------------------------------------------------------
# Property-based tests (hypothesis)
# ---------------------------------------------------------------------------


class TestLxmlParserProperty:
    """Property-based fuzz tests for the lxml KML parser.

    Invariants checked:
    - Arbitrary byte inputs never cause unhandled/unexpected exceptions.
    - Well-formed KML with valid polygons always returns a list of Feature objects
      with consistent internal state (closed rings, correct indices, EPSG:4326 CRS).
    """

    @pytest.mark.parametrize("max_examples", [200])
    def test_arbitrary_bytes_no_unexpected_exception(self, max_examples):
        """Fuzz the parser with arbitrary bytes; only known exceptions may escape."""
        from hypothesis import given, settings
        from hypothesis import strategies as st
        from lxml.etree import XMLSyntaxError

        @given(payload=st.binary(min_size=0, max_size=4096))
        @settings(max_examples=max_examples)
        def _inner(payload: bytes) -> None:
            try:
                result = parse_kml_lxml(payload)
                assert isinstance(result, list)
                for f in result:
                    assert isinstance(f.name, str)
                    assert isinstance(f.exterior_coords, list)
            except (ValueError, XMLSyntaxError):
                pass  # expected — malformed XML or validation error

        _inner()

    @pytest.mark.parametrize("max_examples", [200])
    def test_well_formed_kml_returns_valid_features(self, max_examples):
        """Generate minimal but structurally valid KML and verify feature invariants."""
        from hypothesis import assume, given, settings
        from hypothesis import strategies as st

        # Strategies for coordinate components in WGS-84 range
        lon_st = st.floats(min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False)
        lat_st = st.floats(min_value=-90.0, max_value=90.0, allow_nan=False, allow_infinity=False)

        coord_st = st.tuples(lon_st, lat_st)

        # Build a 4-vertex polygon (will be auto-closed to 5 points)
        polygon_st = st.lists(coord_st, min_size=4, max_size=20)

        name_st = st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs")),
            min_size=1,
            max_size=80,
        )

        @given(name=name_st, coords=polygon_st)
        @settings(max_examples=max_examples)
        def _inner(name: str, coords: list[tuple[float, float]]) -> None:
            # Require all coordinate components to be finite
            assume(all(abs(lon) <= 180 and abs(lat) <= 90 for lon, lat in coords))

            coord_str = " ".join(f"{lon},{lat},0" for lon, lat in coords)
            kml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<kml xmlns="http://www.opengis.net/kml/2.2">'
                "<Document>"
                f"<Placemark><name>{name}</name>"
                "<Polygon><outerBoundaryIs><LinearRing>"
                f"<coordinates>{coord_str}</coordinates>"
                "</LinearRing></outerBoundaryIs></Polygon>"
                "</Placemark>"
                "</Document>"
                "</kml>"
            )
            features = parse_kml_lxml(kml.encode())
            # Must return a list (possibly empty if polygon is degenerate)
            assert isinstance(features, list)
            for f in features:
                # CRS must always be EPSG:4326
                assert f.crs == "EPSG:4326"
                # Exterior ring must be closed (first == last coord)
                ext = f.exterior_coords
                assert len(ext) >= 3
                assert ext[0] == ext[-1], "Exterior ring must be closed"
                # feature_index must be a non-negative integer
                assert isinstance(f.feature_index, int)
                assert f.feature_index >= 0

        _inner()
