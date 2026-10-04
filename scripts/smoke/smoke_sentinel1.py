"""
MeshMind Phase 1C
Sentinel-1 SAR dataset-access smoke test.

Purpose:
- connect to a STAC API with pystac-client
- search real Sentinel-1 GRD scenes
- inspect scene metadata and polarization assets
- sign one real raster asset
- open the Cloud Optimized GeoTIFF with rasterio
- read a small real pixel window

This is not the final surface-water analysis pipeline.
"""

from pathlib import Path
import json
import sys

import numpy as np
import planetary_computer
import rasterio
from pystac_client import Client
from rasterio.windows import Window


PROJECT_ROOT = Path(__file__).resolve().parents[2]

CONFIG_PATH = (
    PROJECT_ROOT
    / "config"
    / "test_case.example.json"
)

STAC_URL = (
    "https://planetarycomputer.microsoft.com/"
    "api/stac/v1"
)

SENTINEL_COLLECTION = "sentinel-1-grd"


def load_test_case() -> dict:
    with CONFIG_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def main() -> None:

    print("=" * 60)
    print("MeshMind - Sentinel-1 SAR Smoke Test")
    print("=" * 60)

    test_case = load_test_case()

    bbox = test_case["bbox"]
    start_time = test_case["sentinel1_smoke_start"]
    end_time = test_case["sentinel1_smoke_end"]

    print(f"\nTest case: {test_case['name']}")
    print(f"Bounding box: {bbox}")
    print(f"Time: {start_time} -> {end_time}")

    # -----------------------------------------------------
    # Connect to STAC
    # -----------------------------------------------------

    print("\nConnecting to Planetary Computer STAC...")

    catalog = Client.open(
        STAC_URL,
        modifier=planetary_computer.sign_inplace,
    )

    collection = catalog.get_collection(
        SENTINEL_COLLECTION
    )

    if collection is None:
        print("ERROR: Sentinel-1 collection not found.")
        sys.exit(1)

    print(f"Collection: {collection.id}")
    print(f"Title: {collection.title}")

    # -----------------------------------------------------
    # Search real Sentinel-1 scenes
    # -----------------------------------------------------

    print("\nSearching Sentinel-1 GRD...")

    search = catalog.search(
        collections=[SENTINEL_COLLECTION],
        bbox=bbox,
        datetime=f"{start_time}/{end_time}",
        max_items=10,
    )

    items = list(search.items())

    print(f"Scenes returned: {len(items)}")

    if not items:
        print("ERROR: No Sentinel-1 scenes found.")
        sys.exit(1)

    # -----------------------------------------------------
    # Inspect returned scenes
    # -----------------------------------------------------

    print("\n--- MATCHING SCENES ---")

    for index, item in enumerate(items, start=1):

        properties = item.properties

        print(f"\nScene {index}")
        print(f"  ID: {item.id}")
        print(f"  Date: {item.datetime}")
        print(
            "  Platform:",
            properties.get("platform")
        )
        print(
            "  Orbit state:",
            properties.get("sat:orbit_state")
        )
        print(
            "  Instrument mode:",
            properties.get("sar:instrument_mode")
        )
        print(
            "  Polarizations:",
            properties.get("sar:polarizations")
        )
        print(
            "  Assets:",
            sorted(item.assets.keys())
        )

    # -----------------------------------------------------
    # Select first scene containing useful SAR data
    # -----------------------------------------------------

    preferred_assets = [
        "vv",
        "vh",
        "hh",
        "hv",
    ]

    selected_item = None
    selected_asset_key = None

    for item in items:

        for asset_key in preferred_assets:

            if asset_key in item.assets:
                selected_item = item
                selected_asset_key = asset_key
                break

        if selected_item is not None:
            break

    if selected_item is None:
        print(
            "ERROR: No VV/VH/HH/HV raster "
            "asset was found."
        )
        sys.exit(1)

    print("\n--- SELECTED SCENE ---")
    print(f"Scene: {selected_item.id}")
    print(f"Date: {selected_item.datetime}")
    print(f"Polarization asset: {selected_asset_key}")

    asset = selected_item.assets[selected_asset_key]

    # Do not print asset.href.
    # Planetary Computer adds a temporary signed
    # access token to this URL.

    # -----------------------------------------------------
    # Open real SAR raster
    # -----------------------------------------------------

    print("\nOpening real Sentinel-1 raster...")

    with rasterio.open(asset.href) as src:

        print(f"Driver: {src.driver}")
        print(f"Width: {src.width}")
        print(f"Height: {src.height}")
        print(f"Band count: {src.count}")
        print(f"Data type: {src.dtypes[0]}")
        print(f"NoData: {src.nodata}")
        print(f"CRS: {src.crs}")

        gcps, gcp_crs = src.gcps

        print(f"GCP count: {len(gcps)}")
        print(f"GCP CRS: {gcp_crs}")

        # Read only a small section.
        # We do not need to download the full SAR image
        # for the smoke test.

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
        )

    print("\n--- PIXEL TEST ---")

    print(f"Window shape: {data.shape}")

    valid = data[
        np.isfinite(data)
        & (data != 0)
    ]

    print(f"Pixels read: {data.size}")
    print(f"Valid non-zero pixels: {valid.size}")

    if valid.size == 0:
        print(
            "ERROR: Raster opened but test "
            "window contained no valid data."
        )
        sys.exit(1)

    print(f"Minimum value: {valid.min()}")
    print(f"Maximum value: {valid.max()}")
    print(f"Mean value: {valid.mean():.3f}")

    print("\n" + "=" * 60)
    print("SENTINEL-1 SMOKE TEST: PASS")
    print("=" * 60)


if __name__ == "__main__":
    main()