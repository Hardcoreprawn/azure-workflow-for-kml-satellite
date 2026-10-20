"""Tests for the canonical polygon geometry model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from treesight.models.geometry import LinearRing, PolygonGeometry, PolygonPart

OUTER = ((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0), (0.0, 0.0))
HOLE = ((1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0), (1.0, 1.0))
SECOND_HOLE = ((2.5, 2.5), (3.0, 2.5), (3.0, 3.0), (2.5, 3.0), (2.5, 2.5))


def test_polygon_keeps_multiple_holes_attached_to_their_part() -> None:
    geometry = PolygonGeometry(
        parts=(PolygonPart(outer=OUTER, inners=(HOLE, SECOND_HOLE)),),
    )

    assert geometry.geometry_type == "Polygon"
    assert geometry.parts[0].inners == (HOLE, SECOND_HOLE)
    assert geometry.to_geojson() == {
        "type": "Polygon",
        "coordinates": (OUTER, HOLE, SECOND_HOLE),
    }


def test_multipolygon_keeps_parts_and_each_parts_holes_distinct() -> None:
    other_outer = ((10.0, 0.0), (12.0, 0.0), (12.0, 2.0), (10.0, 2.0), (10.0, 0.0))
    other_hole = ((10.5, 0.5), (11.0, 0.5), (11.0, 1.0), (10.5, 1.0), (10.5, 0.5))
    geometry = PolygonGeometry(
        parts=(
            PolygonPart(outer=OUTER, inners=(HOLE, SECOND_HOLE)),
            PolygonPart(outer=other_outer, inners=(other_hole,)),
        ),
    )

    assert geometry.geometry_type == "MultiPolygon"
    assert geometry.parts[0].inners == (HOLE, SECOND_HOLE)
    assert geometry.parts[1].inners == (other_hole,)
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
            PolygonPart(outer=OUTER, inners=(HOLE,)),
            PolygonPart(outer=island),
        ),
    )

    assert geometry.geometry_type == "MultiPolygon"
    assert len(geometry.parts) == 2
    assert geometry.parts[0].inners == (HOLE,)
    assert geometry.parts[1].inners == ()


def test_geojson_round_trip_preserves_polygon_and_multipolygon() -> None:
    polygon = PolygonGeometry(parts=(PolygonPart(outer=OUTER, inners=(HOLE,)),))
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
    geometry = PolygonGeometry(parts=(PolygonPart(outer=OUTER),))

    with pytest.raises((TypeError, ValidationError)):
        geometry.parts[0].inners = (HOLE,)


@pytest.mark.parametrize(
    "part",
    [
        {"outer": ((0.0, 0.0), (2.0, 0.0), (1.0, 2.0))},
        {
            "outer": ((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0), (0.0, 0.0)),
            "inners": (((5.0, 5.0), (6.0, 5.0), (6.0, 6.0), (5.0, 6.0), (5.0, 5.0)),),
        },
        {
            "outer": ((0.0, 0.0), (4.0, 4.0), (0.0, 4.0), (4.0, 0.0), (0.0, 0.0)),
        },
    ],
)
def test_polygon_part_rejects_invalid_ring_topology(part: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PolygonPart.model_validate(part)


def test_polygon_rejects_overlapping_parts() -> None:
    overlapping = ((3.0, 1.0), (5.0, 1.0), (5.0, 3.0), (3.0, 3.0), (3.0, 1.0))

    with pytest.raises(ValidationError, match="valid MultiPolygon"):
        PolygonGeometry(parts=(PolygonPart(outer=OUTER), PolygonPart(outer=overlapping)))


def test_position_rejects_coordinates_outside_wgs84() -> None:
    invalid = ((181.0, 0.0), (182.0, 0.0), (182.0, 1.0), (181.0, 1.0), (181.0, 0.0))

    with pytest.raises(ValidationError):
        PolygonPart(outer=invalid)


@pytest.mark.parametrize(
    "other",
    [
        HOLE,
        ((1.5, 1.5), (2.5, 1.5), (2.5, 2.5), (1.5, 2.5), (1.5, 1.5)),
        ((1.2, 1.2), (1.8, 1.2), (1.8, 1.8), (1.2, 1.8), (1.2, 1.2)),
    ],
    ids=["duplicate", "overlapping", "nested"],
)
def test_inner_rings_cannot_conflict(other: LinearRing) -> None:
    with pytest.raises(ValidationError, match="valid polygon"):
        PolygonPart(outer=OUTER, inners=(HOLE, other))


def test_unknown_geometry_fields_are_rejected_instead_of_ignored() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PolygonPart.model_validate({"outer": OUTER, "inner": [HOLE]})


def test_json_round_trip_preserves_every_ring() -> None:
    geometry = PolygonGeometry(parts=(PolygonPart(outer=OUTER, inners=(HOLE, SECOND_HOLE)),))

    assert PolygonGeometry.model_validate_json(geometry.model_dump_json()) == geometry


def test_ring_direction_does_not_determine_whether_it_is_a_hole() -> None:
    part = PolygonPart(outer=OUTER[::-1], inners=(HOLE[::-1], SECOND_HOLE))

    assert part.inners == (HOLE[::-1], SECOND_HOLE)


@pytest.mark.parametrize("coordinate", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_coordinates_are_rejected(coordinate: float) -> None:
    with pytest.raises(ValidationError, match="finite coordinates"):
        PolygonPart(outer=((0, 0), (coordinate, 0), (1, 1), (0, 0)))


def test_geometry_requires_at_least_one_polygon() -> None:
    with pytest.raises(ValidationError):
        PolygonGeometry(parts=())


def test_model_does_not_retain_mutable_input_rings() -> None:
    outer = [list(position) for position in OUTER]
    part = PolygonPart.model_validate({"outer": outer})
    outer[0][0] = 99

    assert part.outer == OUTER


def test_dateline_crossing_ring_requires_explicit_split() -> None:
    ring = ((179.9, -16.5), (-179.8, -16.5), (-179.8, -16.6), (179.9, -16.6), (179.9, -16.5))
    with pytest.raises(ValidationError, match="antimeridian"):
        PolygonPart(outer=ring)


def test_parts_spanning_antimeridian_are_rejected_until_wrapped_extents_supported() -> None:
    east = PolygonPart(outer=((179.8, 0), (180, 0), (180, 1), (179.8, 1), (179.8, 0)))
    west = PolygonPart(outer=((-180, 0), (-179.8, 0), (-179.8, 1), (-180, 1), (-180, 0)))
    with pytest.raises(ValidationError, match="longitude span"):
        PolygonGeometry(parts=(east, west))
