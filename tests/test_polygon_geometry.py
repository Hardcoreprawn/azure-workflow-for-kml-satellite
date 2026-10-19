"""Tests for the canonical polygon geometry model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from treesight.models.geometry import PolygonGeometry, PolygonPart

OUTER = ((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0), (0.0, 0.0))
HOLE = ((1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0), (1.0, 1.0))
SECOND_HOLE = ((2.5, 2.5), (3.0, 2.5), (3.0, 3.0), (2.5, 3.0), (2.5, 2.5))


def test_polygon_keeps_multiple_holes_attached_to_their_part() -> None:
    geometry = PolygonGeometry(
        parts=(PolygonPart(exterior=OUTER, holes=(HOLE, SECOND_HOLE)),),
    )

    assert geometry.geometry_type == "Polygon"
    assert geometry.parts[0].holes == (HOLE, SECOND_HOLE)
    assert geometry.to_geojson() == {
        "type": "Polygon",
        "coordinates": (OUTER, HOLE, SECOND_HOLE),
    }


def test_multipolygon_keeps_parts_and_each_parts_holes_distinct() -> None:
    other_outer = ((10.0, 0.0), (12.0, 0.0), (12.0, 2.0), (10.0, 2.0), (10.0, 0.0))
    other_hole = ((10.5, 0.5), (11.0, 0.5), (11.0, 1.0), (10.5, 1.0), (10.5, 0.5))
    geometry = PolygonGeometry(
        parts=(
            PolygonPart(exterior=OUTER, holes=(HOLE, SECOND_HOLE)),
            PolygonPart(exterior=other_outer, holes=(other_hole,)),
        ),
    )

    assert geometry.geometry_type == "MultiPolygon"
    assert geometry.parts[0].holes == (HOLE, SECOND_HOLE)
    assert geometry.parts[1].holes == (other_hole,)
    assert geometry.to_geojson() == {
        "type": "MultiPolygon",
        "coordinates": (
            (OUTER, HOLE, SECOND_HOLE),
            (other_outer, other_hole),
        ),
    }


def test_island_inside_hole_is_a_separate_part() -> None:
    island = ((1.2, 1.2), (1.8, 1.2), (1.8, 1.8), (1.2, 1.8), (1.2, 1.2))
    geometry = PolygonGeometry(
        parts=(
            PolygonPart(exterior=OUTER, holes=(HOLE,)),
            PolygonPart(exterior=island),
        ),
    )

    assert geometry.geometry_type == "MultiPolygon"
    assert len(geometry.parts) == 2
    assert geometry.parts[0].holes == (HOLE,)
    assert geometry.parts[1].holes == ()


def test_geojson_round_trip_preserves_polygon_and_multipolygon() -> None:
    polygon = PolygonGeometry(parts=(PolygonPart(exterior=OUTER, holes=(HOLE,)),))
    multipolygon = PolygonGeometry.from_geojson(
        {
            "type": "MultiPolygon",
            "coordinates": (
                (OUTER, HOLE),
                (((10.0, 0.0), (12.0, 0.0), (12.0, 2.0), (10.0, 2.0), (10.0, 0.0)),),
            ),
        }
    )

    assert PolygonGeometry.from_geojson(polygon.to_geojson()) == polygon
    assert PolygonGeometry.from_geojson(multipolygon.to_geojson()) == multipolygon


def test_polygon_geometry_is_immutable() -> None:
    geometry = PolygonGeometry(parts=(PolygonPart(exterior=OUTER),))

    with pytest.raises((TypeError, ValidationError)):
        geometry.parts[0].holes = (HOLE,)


@pytest.mark.parametrize(
    "part",
    [
        {"exterior": ((0.0, 0.0), (2.0, 0.0), (1.0, 2.0))},
        {
            "exterior": ((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0), (0.0, 0.0)),
            "holes": (((5.0, 5.0), (6.0, 5.0), (6.0, 6.0), (5.0, 6.0), (5.0, 5.0)),),
        },
        {
            "exterior": ((0.0, 0.0), (4.0, 4.0), (0.0, 4.0), (4.0, 0.0), (0.0, 0.0)),
        },
    ],
)
def test_polygon_part_rejects_invalid_ring_topology(part: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PolygonPart.model_validate(part)


def test_polygon_rejects_overlapping_parts() -> None:
    overlapping = ((3.0, 1.0), (5.0, 1.0), (5.0, 3.0), (3.0, 3.0), (3.0, 1.0))

    with pytest.raises(ValidationError, match="valid MultiPolygon"):
        PolygonGeometry(parts=(PolygonPart(exterior=OUTER), PolygonPart(exterior=overlapping)))


def test_position_rejects_coordinates_outside_wgs84() -> None:
    invalid = ((181.0, 0.0), (182.0, 0.0), (182.0, 1.0), (181.0, 1.0), (181.0, 0.0))

    with pytest.raises(ValidationError):
        PolygonPart(exterior=invalid)
