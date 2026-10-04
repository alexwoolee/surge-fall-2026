"""
MeshMind Phase 1A
GPM IMERG dataset-access smoke test.

Purpose:
- authenticate with NASA Earthdata
- search GPM IMERG
- inspect real granule metadata
- download one real HDF5 granule
- inspect its actual dataset structure

This is not the final rainfall-analysis pipeline.
"""

from pathlib import Path
import json
import sys

import earthaccess
import h5py


PROJECT_ROOT = Path(__file__).resolve().parents[2]

CONFIG_PATH = (
    PROJECT_ROOT
    / "config"
    / "test_case.example.json"
)

DOWNLOAD_DIR = (
    PROJECT_ROOT
    / "data"
    / "cache"
    / "gpm_smoke"
)

GPM_SHORT_NAME = "GPM_3IMERGHH"
GPM_VERSION = "07"


def load_test_case() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def inspect_hdf5(file_path: Path) -> None:
    print("\n--- HDF5 INSPECTION ---")
    print(f"File: {file_path}")

    dataset_paths = []

    with h5py.File(file_path, "r") as hdf:
        print("\nTop-level groups:")

        for name in hdf.keys():
            print(f"  - {name}")

        def visitor(name, obj):
            if isinstance(obj, h5py.Dataset):
                dataset_paths.append(name)

        hdf.visititems(visitor)

        print(f"\nDatasets found: {len(dataset_paths)}")

        print("\nDataset paths:")

        for path in dataset_paths:
            dataset = hdf[path]

            print(
                f"  {path}"
                f" | shape={dataset.shape}"
                f" | dtype={dataset.dtype}"
            )

        precipitation_candidates = [
            path
            for path in dataset_paths
            if "precip" in path.lower()
        ]

        print("\nPrecipitation-related datasets:")

        if precipitation_candidates:
            for path in precipitation_candidates:
                print(f"  - {path}")
        else:
            print("  None found")


def main() -> None:
    print("=" * 60)
    print("MeshMind - GPM IMERG Smoke Test")
    print("=" * 60)

    test_case = load_test_case()

    bbox = tuple(test_case["bbox"])
    start_time = test_case["gpm_smoke_start"]
    end_time = test_case["gpm_smoke_end"]

    print(f"\nTest case: {test_case['name']}")
    print(f"Bounding box: {bbox}")
    print(f"Time: {start_time} -> {end_time}")

    print("\nAuthenticating with NASA Earthdata...")

    auth = earthaccess.login()

    if not auth.authenticated:
        print("ERROR: Earthdata authentication failed.")
        sys.exit(1)

    print("Authentication: PASS")

    print("\nSearching GPM IMERG...")

    results = earthaccess.search_data(
        short_name=GPM_SHORT_NAME,
        version=GPM_VERSION,
        bounding_box=bbox,
        temporal=(start_time, end_time),
        count=5,
    )

    print(f"Granules returned: {len(results)}")

    if not results:
        print("ERROR: No GPM granules were returned.")
        sys.exit(1)

    first = results[0]

    print("\n--- FIRST GRANULE ---")
    print(first)

    links = first.data_links()

    print(f"\nData links found: {len(links)}")

    for link in links[:5]:
        print(f"  {link}")

    DOWNLOAD_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("\nDownloading one granule...")
    print(f"Destination: {DOWNLOAD_DIR}")

    downloaded_files = earthaccess.download(
        [first],
        str(DOWNLOAD_DIR),
    )

    if not downloaded_files:
        print(
            "ERROR: earthaccess returned "
            "no downloaded file."
        )
        sys.exit(1)

    local_file = Path(downloaded_files[0])

    if not local_file.exists():
        print(
            "ERROR: Downloaded path "
            f"does not exist: {local_file}"
        )
        sys.exit(1)

    print(f"Downloaded: {local_file.name}")
    print(f"Bytes: {local_file.stat().st_size}")

    inspect_hdf5(local_file)

    print("\n" + "=" * 60)
    print("GPM SMOKE TEST: PASS")
    print("=" * 60)


if __name__ == "__main__":
    main()