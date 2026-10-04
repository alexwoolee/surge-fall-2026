"""Verify the calibrated Sentinel-1 RTC dependency used by Phase 3B.

Search -> select VV -> sign -> inspect -> read a small real AOI window.
This access check does not classify water or replace the production processor.
"""

from pathlib import Path
import json

import numpy as np
import planetary_computer
from pystac_client import Client
import rasterio
from rasterio.warp import transform
from rasterio.windows import Window

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STAC_URL = 'https://planetarycomputer.microsoft.com/api/stac/v1'
SENTINEL_COLLECTION = 'sentinel-1-rtc'


def main() -> int:
    try:
        config = json.loads((PROJECT_ROOT / 'config/test_case.example.json').read_text(encoding='utf-8-sig'))
        bbox = config['bbox']
        print('Searching Sentinel-1 RTC VV...', flush=True)
        catalog = Client.open(STAC_URL, timeout=30)
        items = list(catalog.search(collections=[SENTINEL_COLLECTION], bbox=bbox,
                                   datetime=f"{config['sentinel1_smoke_start']}/{config['sentinel1_smoke_end']}",
                                   max_items=20).items())
        # Smoke reads one asset; complete production discovery has its own bounded pagination.
        items = [item for item in items if 'vv' in item.assets
                 and 'VV' in item.properties.get('sar:polarizations', [])]
        if not items:
            raise ValueError('No matching VV assets.')
        west, south, east, north = bbox
        def overlap(item):
            left, bottom, right, top = item.bbox
            return max(0, min(east, right) - max(west, left)) * max(0, min(north, top) - max(south, bottom))
        selected = sorted(items, key=lambda item: (-overlap(item), -item.datetime.timestamp(), item.id))[0]
        print(f'Collection: {SENTINEL_COLLECTION}\nScene: {selected.id}\nAcquired: {selected.datetime}\nPolarization: VV', flush=True)
        href = planetary_computer.sign(selected.assets['vv'].href)
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='TRUE', GDAL_HTTP_TIMEOUT=30,
                          GDAL_HTTP_CONNECTTIMEOUT=10, GDAL_HTTP_MAX_RETRY=2):
            with rasterio.open(href) as src:
                print(f'Grid: {src.width} x {src.height}; CRS: {src.crs}; dtype: {src.dtypes[0]}; nodata: {src.nodata}', flush=True)
                if src.crs is None or not src.crs.is_projected or np.dtype(src.dtypes[0]).kind != 'f':
                    raise ValueError('Expected georeferenced floating-point RTC intensity.')
                x, y = transform('EPSG:4326', src.crs, [(west + east)/2], [(south + north)/2])
                row, col = src.index(x[0], y[0])
                if not (0 <= row < src.height and 0 <= col < src.width):
                    raise ValueError('AOI center is outside the selected raster.')
                size = min(512, src.width, src.height)
                window = Window(max(0, min(src.width-size, col-size//2)),
                                max(0, min(src.height-size, row-size//2)), size, size)
                pixels = src.read(1, window=window, masked=True)
                raw = pixels.data
                valid = ~np.ma.getmaskarray(pixels) & np.isfinite(raw) & (raw > 0)
                if src.nodata is not None:
                    valid &= raw != src.nodata
                values = raw[valid]
                if not values.size:
                    raise ValueError('No valid positive power in AOI-center window.')
                print(f'Valid positive gamma0 power pixels: {values.size:,}; range: {values.min():.6g}–{values.max():.6g}', flush=True)
        print('SENTINEL-1 RTC SMOKE TEST: PASS', flush=True)
        return 0
    except Exception:
        # Catalog/GDAL errors can embed signed URLs; never print raw exceptions.
        print('SENTINEL-1 RTC SMOKE TEST: FAIL — check catalog access, VV asset and raster metadata.', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
