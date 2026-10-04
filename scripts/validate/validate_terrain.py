"""Run the Phase 3A public-data gate and save terrain rasters for manual review.

Run: python -m scripts.validate.validate_terrain
No NASA credentials are needed. Generated files belong under outputs/debug/.
"""

import argparse
from html import escape
import json
from pathlib import Path
import warnings

import numpy as np
import rasterio
from rasterio.errors import NotGeoreferencedWarning

from backend.workers.flood._raster import TerrainProcessingError
from backend.workers.flood.terrain import discover_dem_tiles, analyze_dem_tiles
from backend.workers.flood.hand import discover_hand_tiles, analyze_hand_tiles

ROOT = Path(__file__).resolve().parents[2]


def _check_raster(result):
    """Verify the saved artifact against the structured numerical evidence."""
    with rasterio.open(result["artifact_path"]) as src:
        values = src.read(1, masked=True).compressed()
        values = values[np.isfinite(values)]
    expected = result["statistics"]
    if values.size != expected["count"]:
        raise TerrainProcessingError("Saved raster pixel count differs from the result.")
    for name, value in (("min", values.min()), ("max", values.max()),
                        ("mean", values.mean()), ("median", np.median(values))):
        if not np.isclose(value, expected[name], rtol=1e-10, atol=1e-10):
            raise TerrainProcessingError(f"Saved raster {name} differs from the result.")
    if result["coverage"]["status"] != "complete":
        raise TerrainProcessingError("Real-data gate failed: the AOI has incomplete valid-data coverage.")


def _preview(result, path):
    """Produce a labeled downsampled preview with GDAL's PNG driver."""
    with rasterio.open(result["artifact_path"]) as src:
        scale = min(1, 720 / src.width, 720 / src.height)
        width, height = max(1, round(src.width * scale)), max(1, round(src.height * scale))
        values = src.read(1, out_shape=(height, width), masked=True)
    valid = ~np.ma.getmaskarray(values) & np.isfinite(values.data)
    finite = values.data[valid]
    if finite.size == 0:
        raise TerrainProcessingError("No valid pixels remain in the downsampled preview.")
    low, high = float(finite.min()), float(np.percentile(finite, 98))
    fraction = np.zeros(values.shape)
    fraction[valid] = np.clip((values.data[valid] - low) / max(high - low, 1e-9), 0, 1)
    colors = np.array([[33, 52, 71], [50, 130, 121], [229, 219, 153], [167, 92, 60]])
    rgba = np.zeros((4, height, width), dtype=np.uint8)
    for band in range(3):
        rgba[band] = np.interp(fraction, [0, 1/3, 2/3, 1], colors[:, band]).astype(np.uint8)
    rgba[3] = valid.astype(np.uint8) * 255
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with rasterio.open(path, "w", driver="PNG", width=width, height=height,
                           count=4, dtype="uint8") as dst:
            dst.write(rgba)
    return low, high


def _write_review(results, output_dir):
    cards = []
    for name, result in results.items():
        preview_path = output_dir / f"{name}.png"
        low, high = _preview(result, preview_path)
        stats = result["statistics"]
        tiles = "".join(f"<li>{escape(tile['tile_id'])}</li>" for tile in result["source_tiles"])
        limitations = "".join(f"<li>{escape(text)}</li>" for text in result["limitations"])
        cards.append(f'''<section><h2>{escape(result['source'])}</h2>
<img src="{name}.png" alt="{name.upper()} AOI preview; north is up">
<div class="legend"></div><p>{low:.2f} m → {high:.2f} m (preview 98th percentile; higher values use the final color).</p>
<p>Valid cells: {stats['count']:,} · Mean: {stats['mean']:.3f} m · Range: {stats['min']:.3f}–{stats['max']:.3f} m</p>
<p>Coverage: {result['coverage']['coverage_fraction']:.1%}; valid fraction: {result['coverage']['valid_fraction']:.1%}.</p>
<p><a href="{name}.tif">Full-resolution GeoTIFF</a></p>
<details><summary>Source tiles</summary><ul>{tiles}</ul></details>
<details><summary>Limitations</summary><ul>{limitations}</ul></details></section>''')
    document = '''<!doctype html><html lang="en"><meta charset="utf-8"><title>Phase 3A terrain review</title>
<style>body{font:16px system-ui;max-width:1200px;margin:40px auto;padding:0 20px;color:#243442;background:#f6f7f8}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:24px}section{background:white;padding:20px;border:1px solid #d3dbe0;border-radius:12px}
img{width:100%;display:block;background:#ddd}h1{font-size:30px}h2{font-size:21px}.legend{height:12px;margin-top:12px;background:linear-gradient(90deg,#213447,#328279,#e5db99,#a75c3c)}li{margin:8px 0}</style>
<h1>Phase 3A — real terrain review</h1><p>Automated real-data checks passed. Manual approval remains pending.</p>
<p>North is up. Previews use nearest-neighbor sampling of source-grid pixels; transparent gray areas are missing data.
These are geographic-grid previews, not equal-area maps. Inspect the GeoTIFFs for full-resolution alignment and tile edges.</p>
<p>Check the AOI, source-tile coverage, seams, nodata, and plausibility of elevation/HAND values. HAND supports terrain interpretation; it does not confirm flooding.</p>
<p><a href="result.json">Structured result and provenance</a></p><div class="grid">''' + "".join(cards) + "</div></html>"
    (output_dir / "review.html").write_text(document, encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/test_case.example.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/debug/terrain")
    parser.add_argument("--check-repeatability", action="store_true",
                        help="Reprocess with reversed source order and require identical evidence.")
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    try:
        config = json.loads(args.config.read_text(encoding="utf-8-sig"))
        bbox = config["bbox"]
        results = {}
        for name, discover, analyze in (
            ("dem", discover_dem_tiles, analyze_dem_tiles),
            ("hand", discover_hand_tiles, analyze_hand_tiles),
        ):
            print(f"Discovering {name.upper()} tiles...", flush=True)
            tiles = discover(bbox)
            print(f"Processing {len(tiles)} {name.upper()} tiles...", flush=True)
            output = args.output_dir / f"{name}.tif"
            result = analyze(tiles, bbox, output_path=output)
            _check_raster(result)
            if args.check_repeatability:
                repeated = analyze(list(reversed(tiles)), bbox)
                expected = {key: value for key, value in result.items() if key != "artifact_path"}
                actual = {key: value for key, value in repeated.items() if key != "artifact_path"}
                if expected != actual:
                    raise TerrainProcessingError(f"{name.upper()} changed when tile order was reversed.")
            results[name] = result
            print(f"{name.upper()} real-data check: PASS — {result['statistics']}", flush=True)
        _write_review(results, args.output_dir)
        report = {"phase": "3A", "real_data_check": "PASS", "manual_review": "PENDING",
                  "repeatability_checked": args.check_repeatability, "test_case": config.get("id"),
                  "bbox": bbox, "results": results}
        (args.output_dir / "result.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    except (TerrainProcessingError, OSError, ValueError, KeyError) as exc:
        print(f"Phase 3A real-data check: FAIL — {exc}", flush=True)
        (args.output_dir / "result.json").write_text(json.dumps({
            "phase": "3A", "real_data_check": "FAIL", "error": str(exc),
            "manual_review": "NOT_READY",
        }, indent=2) + "\n")
        # A previous successful preview must not be mistaken for this failed run.
        review = args.output_dir / "review.html"
        if review.exists():
            review.write_text("<h1>Phase 3A validation failed</h1><p>See result.json for this run.</p>")
        return 1
    print(f"Review ready: {args.output_dir / 'review.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
