"""
Amalga Phase 1E
Global 30m HAND dataset-access smoke test.

Purpose:
- connect to the ASF STAC catalog
- search GLO-30 HAND
- inspect real HAND tiles
- open one real Cloud Optimized GeoTIFF
- read real HAND pixel values
- calculate simple test statistics

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

STAC_URL = "https://stac.asf.alaska.edu/"

HAND_COLLECTION = "glo-30-hand"

HAND_S3_BASE = (
    "https://glo-30-hand.s3.us-west-2.amazonaws.com"
    "/v1/2021"
)


def load_test_case() -> dict:
    """Load the shared Amalga test configuration."""

    with CONFIG_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def find_raster_asset(item):
    """
    Find a GeoTIFF-like asset without assuming
    the STAC asset key beforehand.

    Returns:
        tuple:
            asset key,
            asset URL,
            media type

        Returns (None, None, None) when no suitable
        raster asset is present.
    """

    for key, asset in item.assets.items():

        href = asset.href

        if not href:
            continue

        href_lower = href.lower()

        media_type = (
            asset.media_type
            if asset.media_type
            else ""
        )

        media_type_lower = media_type.lower()

        if (
            href_lower.endswith(".tif")
            or href_lower.endswith(".tiff")
            or "geotiff" in media_type_lower
            or "tiff" in media_type_lower
        ):
            return key, href, media_type

    return None, None, None


def main() -> None:

    print("=" * 60)
    print("Amalga - GLO-30 HAND Smoke Test")
    print("=" * 60)

    # -----------------------------------------------------
    # Load test case
    # -----------------------------------------------------

    test_case = load_test_case()

    bbox = test_case["bbox"]

    print(f"\nTest case: {test_case['name']}")
    print(f"Bounding box: {bbox}")

    # -----------------------------------------------------
    # Connect to ASF STAC
    # -----------------------------------------------------

    print("\nConnecting to ASF STAC...")

    catalog = Client.open(STAC_URL)

    collection = catalog.get_collection(
        HAND_COLLECTION
    )

    if collection is None:
        print("ERROR: HAND collection not found.")
        sys.exit(1)

    print(f"Collection: {collection.id}")
    print(f"Title: {collection.title}")

    # -----------------------------------------------------
    # Search HAND tiles
    # -----------------------------------------------------

    print("\nSearching GLO-30 HAND tiles...")

    search = catalog.search(
        collections=[HAND_COLLECTION],
        bbox=bbox,
        max_items=10,
    )

    items = list(search.items())

    print(f"Tiles returned: {len(items)}")

    if not items:
        print("ERROR: No HAND tiles found.")
        sys.exit(1)

    # -----------------------------------------------------
    # Try to re-fetch complete STAC items
    # -----------------------------------------------------
    #
    # ASF's search response may return lightweight items
    # where bbox/assets are not populated.
    #
    # Try retrieving each item directly from the
    # collection endpoint.

    full_items = []

    print("\nFetching complete item metadata...")

    for item in items:

        try:
            full_item = collection.get_item(item.id)
        except Exception as exc:
            print(
                f"  Could not re-fetch {item.id}: "
                f"{type(exc).__name__}"
            )
            full_item = None

        if full_item is not None:
            full_items.append(full_item)
        else:
            full_items.append(item)

    items = full_items

    # -----------------------------------------------------
    # Inspect matching tiles
    # -----------------------------------------------------

    print("\n--- MATCHING TILES ---")

    for index, item in enumerate(
        items,
        start=1,
    ):

        print(f"\nTile {index}")
        print(f"  ID: {item.id}")
        print(f"  BBox: {item.bbox}")
        print(
            f"  Assets: "
            f"{sorted(item.assets.keys())}"
        )

    # -----------------------------------------------------
    # Select raster asset
    # -----------------------------------------------------

    selected_item = None
    selected_asset_key = None
    selected_href = None
    selected_media_type = None
    used_s3_fallback = False

    for item in items:

        (
            asset_key,
            href,
            media_type,
        ) = find_raster_asset(item)

        if href is not None:
            selected_item = item
            selected_asset_key = asset_key
            selected_href = href
            selected_media_type = media_type
            break

    # -----------------------------------------------------
    # Public S3 fallback
    # -----------------------------------------------------
    #
    # ASF's current search response can return the tile ID
    # while omitting the STAC asset metadata.
    #
    # The GLO-30 HAND files follow a public documented
    # naming pattern:
    #
    # https://glo-30-hand.s3.us-west-2.amazonaws.com/
    # v1/2021/<ITEM_ID>.tif
    #
    # If the item contains no asset, construct that public
    # URL from the real tile ID returned by ASF.

    if selected_href is None:

        print(
            "\nNo raster asset was included in the "
            "returned STAC metadata."
        )

        print(
            "Using the official public GLO-30 HAND "
            "S3 path as a fallback."
        )

        selected_item = items[0]

        selected_asset_key = "public-s3-fallback"

        selected_href = (
            f"{HAND_S3_BASE}/"
            f"{selected_item.id}.tif"
        )

        selected_media_type = (
            "image/tiff; application=geotiff"
        )

        used_s3_fallback = True

    # -----------------------------------------------------
    # Show selected tile
    # -----------------------------------------------------

    print("\n--- SELECTED TILE ---")

    print(f"Tile: {selected_item.id}")
    print(f"Asset key: {selected_asset_key}")
    print(f"Media type: {selected_media_type}")

    if used_s3_fallback:
        print("Asset source: public S3 fallback")
    else:
        print("Asset source: STAC item")

    # -----------------------------------------------------
    # Open real HAND raster
    # -----------------------------------------------------

    print("\nOpening real HAND raster...")

    with rasterio.Env(
        AWS_NO_SIGN_REQUEST="YES",
        AWS_REGION="us-west-2",
    ):

        try:

            with rasterio.open(
                selected_href
            ) as src:

                print(f"Driver: {src.driver}")
                print(f"Width: {src.width}")
                print(f"Height: {src.height}")
                print(f"Band count: {src.count}")
                print(f"Data type: {src.dtypes[0]}")
                print(f"NoData: {src.nodata}")
                print(f"CRS: {src.crs}")
                print(f"Bounds: {src.bounds}")

                # -----------------------------------------
                # Read small test window
                # -----------------------------------------

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
                    (
                        src.width
                        - window_width
                    )
                    // 2,
                )

                row_offset = max(
                    0,
                    (
                        src.height
                        - window_height
                    )
                    // 2,
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

        except Exception as exc:

            print(
                "\nERROR: HAND raster could "
                "not be opened."
            )

            print(
                f"Exception type: "
                f"{type(exc).__name__}"
            )

            print(f"Message: {exc}")

            sys.exit(1)

    # -----------------------------------------------------
    # Validate real values
    # -----------------------------------------------------

    print("\n--- HAND VALUE TEST ---")

    print(f"Window shape: {data.shape}")
    print(f"Pixels read: {data.size}")

    values = data.compressed()

    print(f"Valid pixels: {values.size}")

    if values.size == 0:
        print(
            "ERROR: HAND raster contained "
            "no valid values."
        )
        sys.exit(1)

    finite = values[
        np.isfinite(values)
    ]

    if finite.size == 0:
        print(
            "ERROR: HAND raster contained "
            "no finite values."
        )
        sys.exit(1)

    print(
        f"Minimum HAND: "
        f"{finite.min():.2f} m"
    )

    print(
        f"Maximum HAND: "
        f"{finite.max():.2f} m"
    )

    print(
        f"Mean HAND: "
        f"{finite.mean():.2f} m"
    )

    # -----------------------------------------------------
    # Basic sanity check
    # -----------------------------------------------------

    if finite.min() < 0:

        print(
            "\nWARNING: Negative HAND values detected."
        )

        print(
            "We will inspect value and nodata semantics "
            "before production processing."
        )

    # -----------------------------------------------------
    # PASS
    # -----------------------------------------------------

    print("\n" + "=" * 60)
    print("HAND SMOKE TEST: PASS")
    print("=" * 60)


if __name__ == "__main__":
    main()