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
