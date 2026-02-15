# Test KML Data

This directory contains KML files for testing the KML ingestion pipeline. Files are
split into **valid** inputs (positive tests) and **edge cases** (negative / boundary tests).

## Valid Input Files

| # | File | Geometry Type | Tests |
| --- | --- | --- | --- |
| 01 | `01_single_polygon_orchard.kml` | Single polygon | Basic parsing, ExtendedData, area/centroid computation |
| 02 | `02_multipolygon_orchard_blocks.kml` | MultiGeometry (3 polygons) | MultiGeometry handling, fan-out per polygon |
| 03 | `03_multi_feature_vineyard.kml` | 4 Placemarks (single polygons) | Multi-feature KML, mixed crop types, irregular polygon |
| 04 | `04_complex_polygon_with_hole.kml` | Polygon with inner boundary | Inner ring (hole) handling, area subtraction |
| 05 | `05_irregular_polygon_steep_terrain.kml` | Single polygon (many vertices) | High vertex count, non-rectangular boundary |
| 06 | `06_large_area_plantation.kml` | Single polygon (~500 ha) | Large AOI handling, imagery tiling |
| 07 | `07_small_area_garden.kml` | Single polygon (~0.1 ha) | Minimum AOI size, buffer dominates AOI |
| 08 | `08_no_extended_data.kml` | Single polygon | Missing metadata gracefully handled |
| 09 | `09_folder_nested_features.kml` | Nested Folders with 4 Placemarks | Recursive feature extraction from Folder hierarchy |
| 10 | `10_schema_typed_extended_data.kml` | 2 Placemarks with Schema | Schema/SchemaData typed metadata extraction |

## Edge Case Files (`edge_cases/`)

| # | File | Issue | Expected Behaviour |
| --- | --- | --- | --- |
| 11 | `11_malformed_not_xml.kml` | Not XML at all | Reject with clear parse error |
| 12 | `12_malformed_unclosed_tags.kml` | Unclosed XML tags | Reject with clear parse error |
| 13 | `13_empty_no_features.kml` | Valid KML, no Placemarks | Log warning; produce no AOI output |
| 14 | `14_point_only_no_polygons.kml` | Point geometry only | Log warning; skip non-polygon features |
| 15 | `15_degenerate_geometries.kml` | Self-intersecting, zero-area, duplicate vertices | Attempt `make_valid()`; reject unfixable |
| 16 | `16_invalid_coordinates.kml` | Coordinates outside WGS84 bounds | Reject with coordinate validation error |
| 17 | `17_unclosed_ring.kml` | First != last coordinate | Auto-close or reject with warning |

## Locations

| File(s) | Region | Country |
| --- | --- | --- |
| 01, 09 | Yakima Valley, WA | USA |
| 02 | Central Valley, CA | USA |
| 03 | Hawke's Bay | New Zealand |
| 04 | Bundaberg, QLD | Australia |
| 05 | Douro Valley | Portugal |
| 06 | Sabah | Malaysia |
| 07 | Riverside, CA | USA |
| 08 | Sacramento Valley, CA | USA |
| 10 | Yakima Valley, WA | USA |
