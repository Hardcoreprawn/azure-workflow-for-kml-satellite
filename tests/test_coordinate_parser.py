"""Tests for coordinate-to-polygon parser (#601)."""

import pytest

from treesight.parsers.coordinate_parser import (
    MAX_COORDINATE_ROWS,
    parse_coordinate_text,
    parse_csv,
)


class TestParseCoordinateText:
    def test_single_point_creates_buffer(self):
        features = parse_coordinate_text("51.5, -0.1")
        assert len(features) == 1
        f = features[0]
        assert "51.5" in f.name
        assert f.vertex_count >= 32  # circle approximation + closure

    def test_two_points_create_two_buffers(self):
        text = "51.5, -0.1\n48.8, 2.3"
        features = parse_coordinate_text(text)
        assert len(features) == 2

    def test_three_or_more_creates_polygon(self):
        text = "51.5, -0.1\n51.6, -0.2\n51.55, -0.15"
        features = parse_coordinate_text(text)
        assert len(features) == 1
        # Should have the 3 points + closure
        assert features[0].vertex_count >= 3

    def test_polygon_coords_are_lon_lat(self):
        """Feature exterior_coords use [lon, lat] convention."""
        text = "51.5, -0.1\n51.6, -0.2\n51.55, -0.15"
        features = parse_coordinate_text(text)
        # First pair was lat=51.5, lon=-0.1 → [lon, lat] = [-0.1, 51.5]
        assert features[0].exterior_coords[0][0] == pytest.approx(-0.1, abs=0.001)
        assert features[0].exterior_coords[0][1] == pytest.approx(51.5, abs=0.001)

    def test_tab_separator(self):
        features = parse_coordinate_text("51.5\t-0.1")
        assert len(features) == 1

    def test_semicolon_separator(self):
        features = parse_coordinate_text("51.5;-0.1")
        assert len(features) == 1

    def test_comment_lines_ignored(self):
        text = "# Header\n51.5, -0.1\n# Comment\n48.8, 2.3\n51.4, -0.05"
        features = parse_coordinate_text(text)
        assert len(features) == 1  # 3 valid pairs → polygon

    def test_blank_lines_ignored(self):
        text = "\n51.5, -0.1\n\n48.8, 2.3\n\n"
        features = parse_coordinate_text(text)
        assert len(features) == 2

    def test_invalid_latitude_raises(self):
        with pytest.raises(ValueError, match="Latitude"):
            parse_coordinate_text("91.0, 0.0")

    def test_invalid_longitude_raises(self):
        with pytest.raises(ValueError, match="Longitude"):
            parse_coordinate_text("0.0, 181.0")

    def test_unparseable_line_raises(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_coordinate_text("not a coordinate")

    def test_empty_input_raises(self):
        with pytest.raises(ValueError, match="No coordinates"):
            parse_coordinate_text("")

    def test_too_many_rows_raises(self):
        lines = "\n".join(f"{i * 0.001}, {i * 0.001}" for i in range(MAX_COORDINATE_ROWS + 1))
        with pytest.raises(ValueError, match="Too many"):
            parse_coordinate_text(lines)

    def test_custom_buffer(self):
        features_small = parse_coordinate_text("51.5, -0.1", buffer_m=100)
        features_big = parse_coordinate_text("51.5, -0.1", buffer_m=1000)
        # Bigger buffer → wider spread of coordinates
        small_lons = [c[0] for c in features_small[0].exterior_coords]
        big_lons = [c[0] for c in features_big[0].exterior_coords]
        assert max(big_lons) - min(big_lons) > max(small_lons) - min(small_lons)

    def test_source_file_propagated(self):
        features = parse_coordinate_text("51.5, -0.1", source_file="my_input")
        assert features[0].source_file == "my_input"

    def test_polygon_is_closed(self):
        text = "51.5, -0.1\n51.6, -0.2\n51.55, -0.15"
        features = parse_coordinate_text(text)
        coords = features[0].exterior_coords
        assert coords[0] == coords[-1]

    def test_negative_coords(self):
        features = parse_coordinate_text("-33.87, 151.21")
        assert len(features) == 1


class TestParseCsv:
    def test_basic_csv(self):
        csv_text = "lat,lon\n51.5,-0.1\n48.8,2.3"
        features = parse_csv(csv_text)
        assert len(features) == 2

    def test_latitude_longitude_headers(self):
        csv_text = "latitude,longitude\n51.5,-0.1"
        features = parse_csv(csv_text)
        assert len(features) == 1

    def test_lng_header(self):
        csv_text = "lat,lng\n51.5,-0.1"
        features = parse_csv(csv_text)
        assert len(features) == 1

    def test_name_column(self):
        csv_text = "name,lat,lon\nTest Site,51.5,-0.1"
        features = parse_csv(csv_text)
        assert features[0].name == "Test Site"

    def test_default_name_without_column(self):
        csv_text = "lat,lon\n51.5,-0.1"
        features = parse_csv(csv_text)
        assert "51.5" in features[0].name

    def test_missing_lat_column_raises(self):
        with pytest.raises(ValueError, match="latitude"):
            parse_csv("x,y\n1,2")

    def test_no_header_raises(self):
        with pytest.raises(ValueError, match="no header"):
            parse_csv("")

    def test_empty_data_raises(self):
        with pytest.raises(ValueError, match="no data"):
            parse_csv("lat,lon\n")

    def test_invalid_values_raise(self):
        with pytest.raises(ValueError, match="Row 1"):
            parse_csv("lat,lon\nabc,def")

    def test_out_of_bounds_raises(self):
        with pytest.raises(ValueError, match="Latitude"):
            parse_csv("lat,lon\n95.0,0.0")

    def test_too_many_rows_raises(self):
        rows = ["lat,lon"] + [f"{i * 0.001},{i * 0.001}" for i in range(MAX_COORDINATE_ROWS + 1)]
        with pytest.raises(ValueError, match="Too many"):
            parse_csv("\n".join(rows))

    def test_label_column(self):
        csv_text = "label,lat,lon\nMy Farm,51.5,-0.1"
        features = parse_csv(csv_text)
        assert features[0].name == "My Farm"

    def test_feature_index_sequential(self):
        csv_text = "lat,lon\n51.5,-0.1\n48.8,2.3\n40.7,-74.0"
        features = parse_csv(csv_text)
        assert [f.feature_index for f in features] == [0, 1, 2]

    def test_source_file(self):
        csv_text = "lat,lon\n51.5,-0.1"
        features = parse_csv(csv_text, source_file="upload.csv")
        assert features[0].source_file == "upload.csv"
