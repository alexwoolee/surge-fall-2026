"""
MeshMind Phase 1D
Copernicus DEM GLO-30 dataset-access smoke test.

Purpose:
- connect to Earth Search with pystac-client
- search the Copernicus DEM GLO-30 collection
- inspect real DEM tile metadata
- open one real raster asset with rasterio
- read elevation pixels
- report basic elevation statistics

This is not the final terrain-analysis pipeline.
"""

from pathlib import Path
import json
import sys

import numpy as np
import rasterio
from pystac_client import Client
from rasterio.windows import Window


PROJECT_ROOT = Path(__file__).resolve().parents[2]

CONFIG_PATH = (
    PROJECT_ROOT
    / "config"
    / "test_case.example.json"
)

STAC_URL = "https://earth-search.aws.element84.com/v1"

DEM_COLLECTION = "cop-dem-glo-30"


def load_test_case() -> dict:
    with CONFIG_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def main() -> None:

    print("=" * 60)
    print("MeshMind - Copernicus DEM GLO-30 Smoke Test")
    print("=" * 60)

    test_case = load_test_case()

    bbox = test_case["bbox"]

    print(f"\nTest case: {test_case['name']}")
    print(f"Bounding box: {bbox}")

    # -----------------------------------------------------
    # Connect to Earth Search
    # -----------------------------------------------------

    print("\nConnecting to Earth Search STAC...")

    catalog = Client.open(STAC_URL)

    collection = catalog.get_collection(
        DEM_COLLECTION
    )

    if collection is None:
        print("ERROR: Copernicus DEM collection not found.")
        sys.exit(1)

    print(f"Collection: {collection.id}")
    print(f"Title: {collection.title}")

    # -----------------------------------------------------
    # Search DEM tiles
    # -----------------------------------------------------

    print("\nSearching Copernicus DEM tiles...")

    search = catalog.search(
        collections=[DEM_COLLECTION],
        bbox=bbox,
        max_items=10,
    )

    items = list(search.items())

    print(f"Tiles returned: {len(items)}")

    if not items:
        print("ERROR: No DEM tiles found.")
        sys.exit(1)

    # -----------------------------------------------------
    # Inspect returned tiles
    # -----------------------------------------------------

    print("\n--- MATCHING TILES ---")

    for index, item in enumerate(items, start=1):

        print(f"\nTile {index}")
        print(f"  ID: {item.id}")
        print(f"  BBox: {item.bbox}")
        print(f"  Assets: {sorted(item.assets.keys())}")

    # -----------------------------------------------------
    # Select first tile with data asset
    # -----------------------------------------------------

    selected_item = None

    for item in items:

        if "data" in item.assets:
            selected_item = item
            break

    if selected_item is None:
        print("ERROR: No DEM 'data' asset found.")
        sys.exit(1)

    asset = selected_item.assets["data"]

    print("\n--- SELECTED TILE ---")
    print(f"Tile: {selected_item.id}")
    print(f"Asset type: {asset.media_type}")

    # Avoid printing full URLs unless needed.
    # The important test is whether rasterio can open the asset.

    # -----------------------------------------------------
    # Open DEM raster
    # -----------------------------------------------------

    print("\nOpening real Copernicus DEM raster...")

    with rasterio.Env(
        AWS_NO_SIGN_REQUEST="YES",
        AWS_REGION="eu-central-1",
    ):

        with rasterio.open(asset.href) as src:

            print(f"Driver: {src.driver}")
            print(f"Width: {src.width}")
            print(f"Height: {src.height}")
            print(f"Band count: {src.count}")
            print(f"Data type: {src.dtypes[0]}")
            print(f"NoData: {src.nodata}")
            print(f"CRS: {src.crs}")
            print(f"Bounds: {src.bounds}")

            # Read a centered test window instead of
            # loading the entire raster into memory.

            window_size = 512

            window_width = min(
                window_size,
                src.width,
            )

            window_height = min(
                window_size,
                src.height,
            )

            col_offset = max(
                0,
                (src.width - window_width) // 2,
            )

            row_offset = max(
                0,
                (src.height - window_height) // 2,
            )

            window = Window(
                col_offset,
                row_offset,
                window_width,
                window_height,
            )

            data = src.read(
                1,
                window=window,
                masked=True,
            )

    # -----------------------------------------------------
    # Validate elevations
    # -----------------------------------------------------

    print("\n--- ELEVATION TEST ---")

    print(f"Window shape: {data.shape}")
    print(f"Pixels read: {data.size}")

    compressed = data.compressed()

    print(f"Valid pixels: {compressed.size}")

    if compressed.size == 0:
        print(
            "ERROR: DEM opened but contained "
            "no valid elevation pixels."
        )
        sys.exit(1)

    finite = compressed[
        np.isfinite(compressed)
    ]

    if finite.size == 0:
        print(
            "ERROR: DEM contained no finite "
            "elevation values."
        )
        sys.exit(1)

    print(f"Minimum elevation: {finite.min():.2f} m")
    print(f"Maximum elevation: {finite.max():.2f} m")
    print(f"Mean elevation: {finite.mean():.2f} m")

    print("\n" + "=" * 60)
    print("COPERNICUS DEM SMOKE TEST: PASS")
    print("=" * 60)


if __name__ == "__main__":
    main()