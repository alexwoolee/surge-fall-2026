"""Run Phase 3B on public calibrated Sentinel-1 RTC and prepare manual review.

Run: .venv/bin/python -m scripts.validate.validate_sentinel1 --check-repeatability
"""

import argparse
from html import escape
import json
from pathlib import Path
import warnings

import numpy as np
import rasterio
from rasterio.errors import NotGeoreferencedWarning
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject

from backend.workers.flood._raster import _aoi_mask
from backend.workers.flood.sentinel1 import (
    Sentinel1ProcessingError, analyze_sentinel1_scene, discover_sentinel1_scene,
)

ROOT = Path(__file__).resolve().parents[2]


def _check_rasters(result):
    """Independently reconcile delivered rasters, threshold, counts and area."""
    with rasterio.open(result['artifacts']['backscatter_db']) as src:
        if src.count != 1 or src.dtypes[0] != 'float64' or src.nodata is None or not np.isnan(src.nodata):
            raise Sentinel1ProcessingError('Backscatter artifact must contain one float64 band with NaN nodata.')
        db = src.read(1)
        grid, crs = src.transform, src.crs
        declared = result['raster']
        if (crs != rasterio.crs.CRS.from_user_input(declared['crs'])
            or src.width != declared['width'] or src.height != declared['height']
            or not np.array_equal(list(grid)[:6], declared['transform'])
            or not np.array_equal([grid.a, -grid.e], declared['resolution'])
            or not np.isclose(abs(grid.a * grid.e), declared['pixel_area_m2'], rtol=1e-12, atol=1e-12)):
            raise Sentinel1ProcessingError('Artifact grid metadata differs from the result.')
    with rasterio.open(result['artifacts']['candidate_water']) as src:
        if src.count != 1 or src.dtypes[0] != 'uint8':
            raise Sentinel1ProcessingError('Candidate artifact must contain one uint8 band.')
        mask = src.read(1)
        if src.transform != grid or src.crs != crs or mask.shape != db.shape:
            raise Sentinel1ProcessingError('Artifact grids differ.')
        if src.nodata != 255:
            raise Sentinel1ProcessingError('Candidate raster must declare 255 as nodata.')
    valid = np.isfinite(db)
    aoi = _aoi_mask(db.shape, grid, crs, result['bbox'])
    aoi_count = int(aoi.sum())
    if not aoi_count or (valid & ~aoi).any():
        raise Sentinel1ProcessingError('Artifact contains pixels outside the AOI or an empty AOI.')
    coverage = result['coverage']
    if coverage['aoi_pixels'] != aoi_count or not np.isclose(
        coverage['valid_fraction'], int(valid.sum()) / aoi_count, rtol=1e-12, atol=1e-12
    ):
        raise Sentinel1ProcessingError('Artifact AOI coverage differs from the result.')
    if not np.array_equal(mask != 255, valid) or not np.isin(mask, [0, 1, 255]).all():
        raise Sentinel1ProcessingError('Artifact valid-data masks differ.')
    expected = valid & (db <= result['method']['threshold_db'])
    if not np.array_equal(mask == 1, expected):
        raise Sentinel1ProcessingError('Candidate raster differs from its documented threshold.')
    values = db[valid]
    stats = result['backscatter_db']
    if values.size != stats['count'] or values.size != result['coverage']['valid_pixels']:
        raise Sentinel1ProcessingError('Artifact valid count differs from the result.')
    for name, value in [('min', values.min()), ('max', values.max()),
                        ('mean', values.mean()), ('median', np.median(values))]:
        if not np.isclose(value, stats[name], rtol=1e-10, atol=1e-10):
            raise Sentinel1ProcessingError(f'Artifact {name} differs from the result.')
    count = int(expected.sum())
    area = count * abs(grid.a * grid.e - grid.b * grid.d) / 1e6
    if count != result['candidate_water']['count'] or not np.isclose(
        area, result['candidate_water']['area_km2'], rtol=1e-12, atol=1e-12
    ):
        raise Sentinel1ProcessingError('Candidate count or area differs from the result.')
    for entry in [result['candidate_water'], *result['sensitivity']]:
        candidate_count = int(np.count_nonzero(values <= entry.get('threshold_db', result['method']['threshold_db'])))
        if (candidate_count != entry['count'] or not np.isclose(
            entry['fraction_valid'], candidate_count / values.size, rtol=1e-12, atol=1e-12
        ) or not np.isclose(entry['area_km2'], candidate_count * abs(grid.a * grid.e) / 1e6, rtol=1e-12, atol=1e-12)):
            raise Sentinel1ProcessingError('Candidate fraction or sensitivity differs from the artifact.')
    if coverage['coverage_fraction'] != 1 or coverage['covered_pixels'] != aoi_count:
        raise Sentinel1ProcessingError('Real-data gate requires full AOI raster coverage.')
    # Real RTC may mask radar shadow; it must remain invalid, never count as water.
    if result['coverage']['valid_fraction'] < 0.95:
        raise Sentinel1ProcessingError('Real-data gate requires at least 95% valid AOI pixels.')
    histogram, edges = np.histogram(values, bins=np.arange(-40, 11, 1))
    return {'edges_db': edges.tolist(), 'counts': histogram.tolist(),
            'outside_histogram_range': int(values.size - histogram.sum())}


def _preview(result, output_dir):
    """Warp only the visual preview to the exact WGS84 bbox, nearest neighbor."""
    west, south, east, north = result['bbox']
    center_lat = np.deg2rad((south + north) / 2)
    aspect = (east - west) * np.cos(center_lat) / (north - south)
    width, height = (1000, round(1000 / aspect)) if aspect >= 1 else (round(1000 * aspect), 1000)
    width, height = max(1, width), max(1, height)
    grid = from_bounds(west, south, east, north, width, height)
    db = np.full((height, width), np.nan, dtype='float64')
    mask = np.full((height, width), 255, dtype='uint8')
    for key, target, nodata in [('backscatter_db', db, np.nan), ('candidate_water', mask, 255)]:
        with rasterio.open(result['artifacts'][key]) as src:
            reproject(source=rasterio.band(src, 1), destination=target,
                      src_transform=src.transform, src_crs=src.crs, src_nodata=src.nodata,
                      dst_transform=grid, dst_crs='EPSG:4326', dst_nodata=nodata,
                      resampling=Resampling.nearest)
    valid = np.isfinite(db) & (mask != 255)
    gray = np.zeros(db.shape, dtype='uint8')
    gray[valid] = (np.clip((db[valid] + 30) / 30, 0, 1) * 255).astype('uint8')
    base = np.stack([gray, gray, gray, valid.astype('uint8') * 255])
    overlay = base.copy()
    overlay[:3, mask == 1] = np.array([25, 150, 255], dtype='uint8')[:, None]
    for name, pixels in [('backscatter', base), ('overlay', overlay)]:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', NotGeoreferencedWarning)
            with rasterio.open(output_dir / f'{name}.png', 'w', driver='PNG', width=width,
                               height=height, count=4, dtype='uint8') as dst:
                dst.write(pixels)
    return width, height


def _write_review(result, histogram, output_dir, case_name="Configured study area"):
    width, height = _preview(result, output_dir)
    west, south, east, north = result['bbox']
    candidate, coverage = result['candidate_water'], result['coverage']
    threshold = result['method']['threshold_db']
    rows = ''.join(f"<tr><td>{entry['threshold_db']:g} dB</td><td>{entry['count']:,}</td>"
                   f"<td>{entry['area_km2']:.3f} km²</td><td>{entry['fraction_valid']:.2%}</td></tr>"
                   for entry in result['sensitivity'])
    limits = ''.join(f'<li>{escape(text)}</li>' for text in result['limitations'])
    scene = result['scene']
    bars = []
    peak = max(histogram['counts'], default=1) or 1
    for index, count in enumerate(histogram['counts']):
        x, top = 40 + index * 10, 140 - count / peak * 110
        color = '#1996ff' if histogram['edges_db'][index + 1] <= threshold else '#737f8b'
        bars.append(f'<rect x="{x}" y="{top}" width="9" height="{140-top}" fill="{color}"><title>{histogram["edges_db"][index]} to {histogram["edges_db"][index+1]} dB: {count:,} pixels</title></rect>')
    histogram_svg = '<svg viewBox="0 0 570 175" role="img" aria-label="One dB histogram of all valid native pixels">' + ''.join(bars) + '<text x="40" y="163">−40 dB</text><text x="420" y="163">0 dB</text><text x="510" y="163">10 dB</text></svg>'
    document = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Phase 3B — Sentinel-1 review</title><style>
body{{font:16px system-ui;max-width:1280px;margin:32px auto;padding:0 24px;color:#213344;background:#f5f7f9}}
h1{{font-size:30px}}h2{{font-size:21px}}section,.callout{{background:white;border:1px solid #d4dce3;border-radius:10px;padding:20px;margin:20px 0}}.metrics{{display:flex;gap:28px;flex-wrap:wrap}}.metrics strong{{display:block;font-size:27px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}figure{{margin:0;min-width:0}}.map{{position:relative;cursor:crosshair;background:#d9dee3}}.map img{{display:block;width:100%}}.axis{{display:flex;justify-content:space-between;font:12px ui-monospace;margin:6px 0}}.legend{{height:12px;background:linear-gradient(90deg,black,white);border:1px solid #aaa}}.blue{{display:inline-block;background:#1996ff;width:14px;height:14px}}table{{border-collapse:collapse;width:100%}}td,th{{padding:10px;text-align:left;border-bottom:1px solid #ddd}}li{{margin:8px 0}}code{{overflow-wrap:anywhere}}button{{padding:8px 14px}}@media(max-width:850px){{.grid{{grid-template-columns:1fr}}}}</style>
<h1>Phase 3B — Candidate surface water</h1>
<p>{escape(str(case_name))} · Sentinel-1 VV · {escape(str(scene['acquired_at']))}</p>
<div class="callout"><strong>Numerical real-data checks: PASS · Manual review: PENDING</strong><p>Blue pixels are low-backscatter candidates at ≤ {threshold:g} dB. This snapshot includes permanent water and possible false positives. It does not establish flood extent or water depth.</p></div>
<section class="metrics"><div><strong>{candidate['area_km2']:.3f} km²</strong>candidate area (approximate UTM)</div><div><strong>{candidate['fraction_valid']:.2%}</strong>of valid AOI pixels</div><div><strong>{coverage['valid_fraction']:.2%}</strong>valid AOI coverage</div></section>
<section><h2>Compare radar signal and candidates</h2><p>North ↑ · Both previews cover the exact longitude/latitude box below. Click either map to locate a feature on OpenStreetMap. That map supplies geographic context, not event-date water truth.</p>
<div class="grid"><figure><figcaption><strong>Calibrated VV gamma0 backscatter</strong></figcaption><div class="axis"><span>{north:.2f}°N</span><span>North ↑</span></div><div class="map"><img src="backscatter.png" width="{width}" height="{height}" alt="Calibrated radar backscatter, geographic AOI" style="height:auto"></div><div class="axis"><span>{west:.2f}°</span><span>{south:.2f}°N</span><span>{east:.2f}°</span></div><div class="legend"></div><div class="axis"><span>−30 dB (dark)</span><span>0 dB (bright)</span></div></figure>
<figure><figcaption><strong>Candidate overlay</strong> <button id="toggle">Hide candidates</button></figcaption><div class="axis"><span>{north:.2f}°N</span><span>North ↑</span></div><div class="map"><img id="overlay" src="overlay.png" width="{width}" height="{height}" alt="Candidate surface-water pixels in blue over radar" style="height:auto"></div><div class="axis"><span>{west:.2f}°</span><span>{south:.2f}°N</span><span>{east:.2f}°</span></div><p><span class="blue"></span> candidate · gray background = invalid/no data</p></figure></div>
<p id="location">Click a feature to read its coordinates.</p><p>Previews use nearest-neighbor sampling on a smaller geographic grid. Small candidate patches may disappear in the preview. Statistics use all native pixels. The grayscale display saturates outside −30 to 0 dB.</p></section>
<section><h2>What to inspect</h2><ol><li>Locate familiar rivers and lakes using the coordinate link. Look for plausible dark water signal and candidate continuity; rough water may be brighter.</li><li>Inspect low-lying areas and compare blue patches with the underlying radar. Separate familiar permanent water from possible event-related patches.</li><li>Look at hills, roads and smooth fields for false positives. Check for isolated speckle, straight scene edges or blank areas. Terrain correction cannot resolve every ambiguous signal.</li><li>Review the sensitivity table. The threshold is a configurable heuristic, not a validated flood classifier. Flag implausible patterns before approving Phase 3B.</li></ol></section>
<section><h2>Threshold sensitivity</h2><p>These are alternative parameter settings, not a confidence interval. They use the same valid pixels.</p><table><thead><tr><th>VV threshold</th><th>Candidate pixels</th><th>Area</th><th>Valid-pixel fraction</th></tr></thead><tbody>{rows}</tbody></table><h2>Backscatter distribution</h2>{histogram_svg}<p>{histogram['outside_histogram_range']:,} valid pixels fall outside the histogram display range.</p></section>
<section><h2>Evidence and method</h2><p><code>{escape(scene['scene_id'])}</code></p><p>Collection: sentinel-1-rtc · Polarization: VV · {escape(str(scene['orbit_state']))} orbit · {escape(result['raster']['crs'])} · {result['raster']['resolution'][0]:g} m pixel spacing.</p><p>Provider: calibrated gamma0 power, radiometric terrain correction and UTM orthorectification. MeshMind masks invalid values, converts positive power with 10 log10, clips by AOI pixel centers, and applies the threshold. No additional smoothing is applied.</p><p><a href="result.json">Structured evidence and provenance</a> · <a href="backscatter_db.tif">Full-resolution backscatter GeoTIFF</a> · <a href="candidate_water.tif">Full-resolution candidate mask GeoTIFF</a></p><details><summary>Limitations</summary><ul>{limits}</ul></details></section>
<script>const box={json.dumps(result['bbox'])};document.querySelectorAll('.map').forEach(map=>map.addEventListener('click',event=>{{const r=map.getBoundingClientRect();const lon=box[0]+(event.clientX-r.left)/r.width*(box[2]-box[0]);const lat=box[3]-(event.clientY-r.top)/r.height*(box[3]-box[1]);const target=document.getElementById('location');target.textContent=lat.toFixed(5)+'°N, '+lon.toFixed(5)+'° · ';const a=document.createElement('a');a.href='https://www.openstreetmap.org/?mlat='+lat+'&mlon='+lon+'#map=13/'+lat+'/'+lon;a.target='_blank';a.rel='noopener';a.textContent='Locate on OpenStreetMap';target.appendChild(a);}}));let shown=true;document.getElementById('toggle').onclick=()=>{{shown=!shown;document.getElementById('overlay').src=shown?'overlay.png':'backscatter.png';document.getElementById('toggle').textContent=shown?'Hide candidates':'Show candidates';}};</script></html>'''
    (output_dir / 'review.html').write_text(document, encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/test_case.example.json')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'outputs/debug/sentinel1')
    parser.add_argument('--threshold-db', type=float, default=-17.0)
    parser.add_argument('--check-repeatability', action='store_true')
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # Invalidate any earlier PASS before starting a network call or long raster read.
    (args.output_dir / 'review.html').write_text('<h1>Phase 3B validation in progress</h1><p>This run has not passed yet.</p>')
    (args.output_dir / 'result.json').write_text(json.dumps({'phase': '3B', 'real_data_check': 'RUNNING', 'manual_review': 'NOT_READY'}) + '\n')
    try:
        config = json.loads(args.config.read_text(encoding='utf-8-sig'))
        print('Discovering calibrated Sentinel-1 RTC VV scene...', flush=True)
        scene = discover_sentinel1_scene(config['bbox'], config['sentinel1_smoke_start'],
                                        config['sentinel1_smoke_end'], reference_time=config['event_end'])
        print(f'Processing {scene.scene_id}...', flush=True)
        result = analyze_sentinel1_scene(scene, config['bbox'], threshold_db=args.threshold_db,
                                         output_dir=args.output_dir)
        histogram = _check_rasters(result)
        if args.check_repeatability:
            print('Checking repeated processing...', flush=True)
            repeated = analyze_sentinel1_scene(scene, config['bbox'], threshold_db=args.threshold_db)
            expected = {key: value for key, value in result.items() if key != 'artifacts'}
            actual = {key: value for key, value in repeated.items() if key != 'artifacts'}
            if expected != actual:
                raise Sentinel1ProcessingError('Repeated processing changed numerical evidence.')
        _write_review(result, histogram, args.output_dir, config.get('name', config.get('id', 'Configured study area')))
        report = {'phase': '3B', 'real_data_check': 'PASS', 'manual_review': 'PENDING',
                  'repeatability_checked': args.check_repeatability, 'test_case': config.get('id'),
                  'search_start': config['sentinel1_smoke_start'], 'search_end': config['sentinel1_smoke_end'],
                  'reference_time': config['event_end'], 'gate_min_valid_fraction': 0.95,
                  'result': result, 'histogram': histogram}
        (args.output_dir / 'result.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    except (Sentinel1ProcessingError, OSError, ValueError, KeyError) as exc:
        # Public processor errors are sanitized; file/config errors need no raw details here.
        error = str(exc) if isinstance(exc, Sentinel1ProcessingError) else 'Configuration or output file operation failed.'
        (args.output_dir / 'result.json').write_text(json.dumps({'phase': '3B', 'real_data_check': 'FAIL',
                                                               'error': error, 'manual_review': 'NOT_READY'}, indent=2) + '\n')
        (args.output_dir / 'review.html').write_text('<h1>Phase 3B validation failed</h1><p>See result.json for this run.</p>')
        print(f'Phase 3B real-data check: FAIL — {error}', flush=True)
        return 1
    print(f"Phase 3B real-data check: PASS — {result['candidate_water']}", flush=True)
    print(f"Review ready: {args.output_dir / 'review.html'}", flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
