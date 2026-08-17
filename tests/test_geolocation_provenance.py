"""Tests for EUDR geolocation provenance (issue #1343).

Verifies that the source geolocation (point or polygon supplied by an actor)
is preserved separately from derived analysis geometry after a buffered
footprint is generated and the result is serialised / round-tripped.
"""

from __future__ import annotations

import pytest

from treesight.models.geolocation import (
    GeolocationProvenance,
    GeometryType,
    LegalUseClassification,
)
from treesight.pipeline.eudr import build_geolocation_provenance

# ---------------------------------------------------------------------------
# §1 — Point round-trip: source geometry survives buffer generation
# ---------------------------------------------------------------------------


class TestPointGeolocationProvenance:
    """Source point coordinates must remain unchanged after buffer derivation."""

    def test_point_source_geometry_is_preserved(self):
        """Round-trip: source [lon, lat] equals supplied values after buffering."""
        lon, lat = 2.3522, 48.8566
        prov = build_geolocation_provenance({"name": "Paris plot", "lon": lon, "lat": lat})

        assert prov.source_geometry_type == GeometryType.POINT
        assert prov.source_geometry == [lon, lat], "Source geometry must be the original point, not a derived buffer"

    def test_derived_geometry_is_a_polygon_ring(self):
        """Derived geometry must be a non-empty closed polygon ring."""
        prov = build_geolocation_provenance({"name": "P", "lon": 36.8, "lat": -1.3})

        assert prov.derived_geometry is not None
        assert len(prov.derived_geometry) > 3
        # Ring must be closed
        assert prov.derived_geometry[0] == prov.derived_geometry[-1]

    def test_source_geometry_is_not_the_derived_polygon(self):
        """Source geometry must differ from the derived buffer polygon."""
        prov = build_geolocation_provenance({"name": "P", "lon": 0.0, "lat": 0.0})

        # The source is a two-element [lon, lat] list, never the polygon ring
        assert len(prov.source_geometry) == 2
        assert prov.derived_geometry is not None
        assert prov.source_geometry != prov.derived_geometry

    def test_derivation_method_label_present(self):
        prov = build_geolocation_provenance({"name": "P", "lon": 0.0, "lat": 0.0})
        assert prov.derivation_method == "point_buffer_circle"

    def test_derivation_params_capture_radius_and_segments(self):
        prov = build_geolocation_provenance(
            {"name": "P", "lon": 0.0, "lat": 0.0, "radius_m": 200.0},
            segments=16,
        )
        assert prov.derivation_params["radius_m"] == 200.0
        assert prov.derivation_params["segments"] == 16

    def test_custom_radius_forwarded_from_plot(self):
        prov = build_geolocation_provenance({"name": "P", "lon": 1.0, "lat": 1.0, "radius_m": 50.0})
        assert prov.derivation_params["radius_m"] == 50.0

    def test_provenance_model_is_frozen(self):
        """GeolocationProvenance must be immutable."""
        prov = build_geolocation_provenance({"name": "P", "lon": 0.0, "lat": 0.0})
        with pytest.raises(ValueError):
            prov.source_geometry = [99.0, 99.0]  # type: ignore[misc]

    def test_round_trip_json_preserves_source_point(self):
        """Serialise to JSON and back; source point coordinates are unchanged."""
        lon, lat = 103.8198, 1.3521  # Singapore
        prov = build_geolocation_provenance({"name": "SG", "lon": lon, "lat": lat})

        data = prov.model_dump()
        prov2 = GeolocationProvenance(**data)

        assert prov2.source_geometry_type == GeometryType.POINT
        assert prov2.source_geometry == [lon, lat]
        assert prov2.derived_geometry is not None
        assert prov2.source_geometry != prov2.derived_geometry


# ---------------------------------------------------------------------------
# §2 — Legal-use classification (EUDR Article 2(28))
# ---------------------------------------------------------------------------


class TestLegalUseClassification:
    """EUDR 4 ha threshold drives polygon_required and classification."""

    def test_point_under_4ha_is_dds_eligible(self):
        prov = build_geolocation_provenance({"name": "P", "lon": 0.0, "lat": 0.0, "plot_area_ha": 3.9})
        assert not prov.polygon_required
        assert prov.legal_use_classification == LegalUseClassification.DDS_ELIGIBLE

    def test_point_over_4ha_is_incomplete(self):
        prov = build_geolocation_provenance({"name": "P", "lon": 0.0, "lat": 0.0, "plot_area_ha": 4.1})
        assert prov.polygon_required
        assert prov.legal_use_classification == LegalUseClassification.INCOMPLETE

    def test_point_exactly_4ha_is_dds_eligible(self):
        """Boundary: exactly 4 ha does not require a polygon."""
        prov = build_geolocation_provenance({"name": "P", "lon": 0.0, "lat": 0.0, "plot_area_ha": 4.0})
        assert not prov.polygon_required
        assert prov.legal_use_classification == LegalUseClassification.DDS_ELIGIBLE

    def test_point_without_area_is_dds_eligible(self):
        """No area declared — no polygon requirement triggered."""
        prov = build_geolocation_provenance({"name": "P", "lon": 0.0, "lat": 0.0})
        assert not prov.polygon_required
        assert prov.legal_use_classification == LegalUseClassification.DDS_ELIGIBLE

    def test_polygon_source_is_dds_eligible(self):
        prov = build_geolocation_provenance(
            {
                "name": "F",
                "coordinates": [[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.3]],
            }
        )
        assert prov.legal_use_classification == LegalUseClassification.DDS_ELIGIBLE
        assert not prov.polygon_required


# ---------------------------------------------------------------------------
# §3 — Polygon source: no derivation, source geometry preserved as-is
# ---------------------------------------------------------------------------


class TestPolygonGeolocationProvenance:
    def test_polygon_source_geometry_preserved(self):
        coords = [[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.3]]
        prov = build_geolocation_provenance({"name": "Field", "coordinates": coords})

        assert prov.source_geometry_type == GeometryType.POLYGON
        assert prov.source_geometry == coords

    def test_polygon_has_no_derived_geometry(self):
        coords = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]
        prov = build_geolocation_provenance({"name": "F", "coordinates": coords})

        assert prov.derived_geometry is None
        assert prov.derivation_method == ""
        assert prov.derivation_params == {}


# ---------------------------------------------------------------------------
# §4 — Optional provenance metadata fields
# ---------------------------------------------------------------------------


class TestProvenanceMetadataFields:
    def test_optional_actor_and_document_stored(self):
        prov = build_geolocation_provenance(
            {
                "name": "P",
                "lon": 0.0,
                "lat": 0.0,
                "source_actor": "Acme Farms",
                "source_document": "DDS-2024-001",
            }
        )
        assert prov.source_actor == "Acme Farms"
        assert prov.source_document == "DDS-2024-001"

    def test_capture_date_parsed_from_iso_string(self):
        from datetime import date

        prov = build_geolocation_provenance({"name": "P", "lon": 0.0, "lat": 0.0, "capture_date": "2024-06-15"})
        assert prov.capture_date == date(2024, 6, 15)

    def test_positional_accuracy_stored(self):
        prov = build_geolocation_provenance(
            {
                "name": "P",
                "lon": 0.0,
                "lat": 0.0,
                "positional_accuracy_m": 5.0,
                "positional_verifier": "GPS unit SN-123",
            }
        )
        assert prov.positional_accuracy_m == 5.0
        assert prov.positional_verifier == "GPS unit SN-123"


# ---------------------------------------------------------------------------
# §5 — Invalid input
# ---------------------------------------------------------------------------


class TestBuildGeolocationProvenanceErrors:
    def test_missing_geometry_raises_value_error(self):
        with pytest.raises(ValueError, match=r"coordinates.*lon.*lat"):
            build_geolocation_provenance({"name": "No geometry"})


# ---------------------------------------------------------------------------
# §6 — KML wiring: coords_to_kml embeds source_geometry_type via provenance
# ---------------------------------------------------------------------------


class TestCoordsToKmlProvenanceWiring:
    """coords_to_kml calls build_geolocation_provenance and embeds source_geometry_type."""

    def test_point_kml_contains_source_geometry_type_extended_data(self):
        from treesight.pipeline.eudr import coords_to_kml

        kml = coords_to_kml([{"name": "P", "lon": 2.35, "lat": 48.86}])
        assert "<Data name=" in kml
        assert "source_geometry_type" in kml
        assert "<value>Point</value>" in kml

    def test_polygon_kml_contains_source_geometry_type_extended_data(self):
        from treesight.pipeline.eudr import coords_to_kml

        coords = [[2.34, 48.85], [2.36, 48.85], [2.36, 48.87], [2.34, 48.87]]
        kml = coords_to_kml([{"name": "F", "coordinates": coords}])
        assert "source_geometry_type" in kml
        assert "<value>Polygon</value>" in kml

    def test_point_kml_does_not_contain_polygon_type(self):
        from treesight.pipeline.eudr import coords_to_kml

        kml = coords_to_kml([{"name": "P", "lon": 2.35, "lat": 48.86}])
        assert "<value>Polygon</value>" not in kml

    def test_polygon_kml_does_not_contain_point_type(self):
        from treesight.pipeline.eudr import coords_to_kml

        coords = [[2.34, 48.85], [2.36, 48.85], [2.36, 48.87], [2.34, 48.87]]
        kml = coords_to_kml([{"name": "F", "coordinates": coords}])
        assert "<value>Point</value>" not in kml

    def test_point_kml_contains_source_lon_lat(self):
        from treesight.pipeline.eudr import coords_to_kml

        kml = coords_to_kml([{"name": "P", "lon": 2.35, "lat": 48.86}])
        assert "source_lon" in kml
        assert "source_lat" in kml

    def test_lxml_parser_reads_source_geometry_type_from_kml(self):
        """ExtendedData set by coords_to_kml is parsed into Feature.metadata by lxml parser."""
        from treesight.parsers.lxml_parser import parse_kml_lxml
        from treesight.pipeline.eudr import coords_to_kml

        kml_bytes = coords_to_kml([{"name": "P", "lon": 2.35, "lat": 48.86}]).encode()
        features = parse_kml_lxml(kml_bytes, source_file="test.kml")
        assert len(features) == 1
        assert features[0].metadata.get("source_geometry_type") == "Point"

    def test_lxml_parser_reads_polygon_source_geometry_type(self):
        from treesight.parsers.lxml_parser import parse_kml_lxml
        from treesight.pipeline.eudr import coords_to_kml

        coords = [[2.34, 48.85], [2.36, 48.85], [2.36, 48.87], [2.34, 48.87]]
        kml_bytes = coords_to_kml([{"name": "F", "coordinates": coords}]).encode()
        features = parse_kml_lxml(kml_bytes, source_file="test.kml")
        assert len(features) == 1
        assert features[0].metadata.get("source_geometry_type") == "Polygon"
