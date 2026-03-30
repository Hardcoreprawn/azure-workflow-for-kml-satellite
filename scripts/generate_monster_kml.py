import argparse
import math
from xml.dom import minidom
from xml.etree.ElementTree import Element, SubElement, tostring


def generate_kml(num_polygons: int, output_file: str):
    """
    Generates a KML file with a specified number of distinct polygons.
    Places them in a grid pattern to ensure they are mathematically valid
    but distinct enough to force the pipeline to process multiple AOIs.
    """
    kml = Element("kml", xmlns="http://www.opengis.net/kml/2.2")
    document = SubElement(kml, "Document")

    name = SubElement(document, "name")
    name.text = f"Monster_KML_{num_polygons}_AOIs"

    # Starting coordinates (e.g., somewhere over a forest or landmass)
    base_lon, base_lat = -60.0, -10.0
    grid_size = math.ceil(math.sqrt(num_polygons))
    step = 0.05  # roughly 5km spacing
    poly_size = 0.02  # roughly 2x2km polygon

    count = 0
    for i in range(grid_size):
        for j in range(grid_size):
            if count >= num_polygons:
                break

            placemark = SubElement(document, "Placemark")
            pm_name = SubElement(placemark, "name")
            pm_name.text = f"AOI_{count}"

            polygon = SubElement(placemark, "Polygon")
            outer_boundary = SubElement(polygon, "outerBoundaryIs")
            linear_ring = SubElement(outer_boundary, "LinearRing")
            coordinates = SubElement(linear_ring, "coordinates")

            # Calculate corners for this polygon
            lon = base_lon + (i * step)
            lat = base_lat + (j * step)

            # 5 points to close a square (bl, tl, tr, br, bl)
            coords = [
                f"{lon},{lat},0",
                f"{lon},{lat + poly_size},0",
                f"{lon + poly_size},{lat + poly_size},0",
                f"{lon + poly_size},{lat},0",
                f"{lon},{lat},0",
            ]
            coordinates.text = " ".join(coords)

            count += 1

    # Pretty print XML
    xmlstr = minidom.parseString(tostring(kml)).toprettyxml(indent="  ")
    with open(output_file, "w") as f:
        f.write(xmlstr)

    print(f"Generated {output_file} with {num_polygons} polygons.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a Monster KML for load testing.")
    parser.add_argument("--count", type=int, default=200, help="Number of polygons to generate")
    parser.add_argument("--out", type=str, default="monster_test.kml", help="Output filename")

    args = parser.parse_args()
    generate_kml(args.count, args.out)
