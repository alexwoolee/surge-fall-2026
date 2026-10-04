"""Run the Phase 3C combined Flood worker against real public sources.

Terminal-only checkpoint; no new HTML or raster artifacts are generated.
Run: .venv/bin/python -m scripts.validate.validate_flood --check-repeatability
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path

from backend.workers.flood._raster import _safe_href
from backend.workers.flood.terrain import discover_dem_tiles
from backend.workers.flood.hand import discover_hand_tiles
from backend.workers.flood.sentinel1 import _iso, discover_sentinel1_scene
from backend.workers.flood.service import run_flood_analysis

ROOT = Path(__file__).resolve().parents[2]


class FloodValidationError(Exception):
    """A completed invocation did not meet the numerical validation gate."""


def _same(actual, expected, description):
    if isinstance(expected, float):
        equal = isinstance(actual, (float, int)) and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)
    else:
        equal = actual == expected
    if not equal:
        raise FloodValidationError(f'Combined result mismatch: {description}.')


def _check_result(result, bbox, scene, dem_tiles, hand_tiles):
    """Verify integration, provenance, numerical summaries and explicit coverage."""
    if result['status'] != 'complete' or result['errors']:
        raise FloodValidationError('All three processors must succeed for the Phase 3C gate.')
    _same(result['bbox'], dict(zip(('west', 'south', 'east', 'north'), bbox)), 'AOI')
    _same(result['worker_id'], 'flood-worker', 'worker identity')
    _same(set(result['evidence']), {'sentinel1', 'dem', 'hand'}, 'evidence components')
    _same(len(result['sources']), 3, 'source count')
    _same({source['component'] for source in result['sources']}, {'sentinel1', 'dem', 'hand'}, 'source components')
    summary, evidence = result['summary'], result['evidence']
    sources = {source['component']: source for source in result['sources']}
    for key in ('sentinel1', 'dem', 'hand'):
        _same(evidence[key]['bbox'], list(bbox), f'{key} AOI')
        _same(result['coverage'][key], evidence[key]['coverage'], f'{key} coverage')
        _same(sources[key]['name'], evidence[key]['source'], f'{key} source name')
        _same(sources[key]['collection'], evidence[key]['collection'], f'{key} source collection')
    sar = evidence['sentinel1']
    _same(sar['scene']['scene_id'], scene.scene_id, 'selected acquisition')
    _same(sar['scene']['acquired_at'], _iso(scene.acquired_at), 'acquisition timestamp')
    _same(sar['scene']['polarization'], scene.polarization, 'acquisition polarization')
    _same(sar['scene']['href'], _safe_href(scene.href), 'acquisition asset')
    _same(sources['sentinel1']['resources_used'], [sar['scene']['href']], 'SAR source resource')
    for key in ('scene_id', 'acquired_at', 'polarization'):
        _same(sources['sentinel1'][key], sar['scene'][key], f'SAR source {key}')
    coverage = sar['coverage']
    if not (0 < coverage['valid_pixels'] <= coverage['covered_pixels'] <= coverage['aoi_pixels']):
        raise FloodValidationError('Sentinel-1 coverage counts are inconsistent.')
    _same(coverage['valid_fraction'], coverage['valid_pixels'] / coverage['aoi_pixels'], 'SAR valid fraction')
    _same(coverage['coverage_fraction'], coverage['covered_pixels'] / coverage['aoi_pixels'], 'SAR source coverage')
    if coverage['coverage_fraction'] != 1 or coverage['valid_fraction'] < 0.95:
        raise FloodValidationError('Sentinel-1 gate requires full raster extent coverage and at least 95% valid pixels.')
    candidate = sar['candidate_water']
    if not 0 <= candidate['count'] <= coverage['valid_pixels']:
        raise FloodValidationError('Candidate count exceeds valid Sentinel-1 pixels.')
    _same(candidate['area_km2'], candidate['count'] * sar['raster']['pixel_area_m2'] / 1e6, 'candidate area')
    _same(candidate['fraction_valid'], candidate['count'] / coverage['valid_pixels'], 'candidate fraction')
    for key, expected in {
        'candidate_area_km2': candidate['area_km2'], 'candidate_fraction_valid': candidate['fraction_valid'],
        'valid_fraction': coverage['valid_fraction'], 'scene_id': sar['scene']['scene_id'],
        'acquired_at': sar['scene']['acquired_at'], 'threshold_db': sar['method']['threshold_db'],
    }.items():
        _same(summary['surface_water'][key], expected, f'surface-water {key}')
    for key, summary_key, tiles in [('dem', 'elevation', dem_tiles), ('hand', 'hand', hand_tiles)]:
        data = evidence[key]
        cov, stats = data['coverage'], data['statistics']
        if cov['status'] != 'complete' or cov['valid_fraction'] != 1 or cov['coverage_fraction'] != 1:
            raise FloodValidationError(f'{key.upper()} gate requires complete valid AOI coverage.')
        if not (cov['aoi_pixels'] == cov['covered_pixels'] == cov['valid_pixels'] == stats['count']):
            raise FloodValidationError(f'{key.upper()} pixel counts do not reconcile.')
        _same({tile['tile_id'] for tile in data['source_tiles']}, {tile.tile_id for tile in tiles}, f'{key} tile provenance')
        _same(len(data['source_tiles']), len({tile.tile_id for tile in tiles}), f'{key} unique source count')
        expected_hrefs = {tile.tile_id: _safe_href(tile.href) for tile in tiles}
        for tile in data['source_tiles']:
            _same(tile['href'], expected_hrefs[tile['tile_id']], f'{key} source asset')
        _same(sources[key]['resources_used'], [tile['href'] for tile in data['source_tiles']], f'{key} source resources')
        _same(sum(tile['contributed_pixels'] for tile in data['source_tiles']), stats['count'], f'{key} contributed cells')
        for metric in ('mean', 'min', 'max', 'median'):
            _same(summary[summary_key][f'{metric}_m'], stats[metric], f'{key} {metric}')
        _same(summary[summary_key]['valid_pixels'], stats['count'], f'{key} valid pixels')
        _same(summary[summary_key]['valid_fraction'], cov['valid_fraction'], f'{key} valid fraction')
        _same(summary[summary_key]['tile_count'], len(data['source_tiles']), f'{key} source count')
    if not result['limitations']:
        raise FloodValidationError('Interpretation limitations are missing.')
    # Round-trip the same payload consumed by later contract/API work.
    _same(json.loads(json.dumps(result, allow_nan=False)), result, 'JSON round trip')


def _print_summary(result):
    print(f"Worker processing: {result['status'].upper()}", flush=True)
    water = result['summary'].get('surface_water')
    if water:
        print(f"Candidate water: {water['candidate_area_km2']:.4f} km²; "
              f"{water['candidate_fraction_valid']:.4%} of valid pixels; "
              f"valid AOI coverage {water['valid_fraction']:.4%}", flush=True)
        print(f"Acquired: {water['acquired_at']}; VV threshold {water['threshold_db']:g} dB", flush=True)
    for key, label in [('elevation', 'DEM'), ('hand', 'HAND')]:
        data = result['summary'].get(key)
        if data:
            print(f"{label}: {data['tile_count']} tiles; {data['valid_pixels']:,} valid pixels; "
                  f"mean {data['mean_m']:.6f} m; valid AOI coverage {data['valid_fraction']:.4%}", flush=True)
    for error in result['errors']:
        print(f"{error['component']}: {error['message']}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/test_case.example.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/debug/flood/result.json')
    parser.add_argument('--threshold-db', type=float, default=-17)
    parser.add_argument('--check-repeatability', action='store_true')
    args = parser.parse_args(argv)
    report = {'phase': '3C', 'real_data_check': 'RUNNING', 'manual_review': 'NOT_READY',
              'started_at': datetime.now(timezone.utc).isoformat(), 'result': None}
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        config = json.loads(args.config.read_text(encoding='utf-8-sig'))
        bbox = config['bbox']
        print('Discovering Sentinel-1 RTC, DEM and HAND resources...', flush=True)
        scene = discover_sentinel1_scene(bbox, config['sentinel1_smoke_start'], config['sentinel1_smoke_end'],
                                        reference_time=config['event_end'])
        dem_tiles, hand_tiles = discover_dem_tiles(bbox), discover_hand_tiles(bbox)
        print(f'Selected {scene.scene_id}; {len(dem_tiles)} DEM tiles; {len(hand_tiles)} HAND tiles.', flush=True)
        print('Running the combined Flood worker...', flush=True)
        result = run_flood_analysis(scene, dem_tiles, hand_tiles, bbox,
                                    task_id='phase3c-real-validation', threshold_db=args.threshold_db)
        report['result'] = result
        _print_summary(result)
        _check_result(result, bbox, scene, dem_tiles, hand_tiles)
        if args.check_repeatability:
            print('Repeating with reversed DEM/HAND source order...', flush=True)
            repeated = run_flood_analysis(scene, list(reversed(dem_tiles)), list(reversed(hand_tiles)), bbox,
                                           task_id='phase3c-real-validation', threshold_db=args.threshold_db)
            if repeated != result:
                raise FloodValidationError('Repeated worker run changed the combined result.')
        report.update(real_data_check='PASS', manual_review='PENDING',
                      repeatability_checked=args.check_repeatability, test_case=config.get('id'),
                      search_start=config['sentinel1_smoke_start'], search_end=config['sentinel1_smoke_end'],
                      reference_time=config['event_end'], gate_min_sentinel_valid_fraction=0.95)
    except Exception as exc:
        # Discovery/GDAL exceptions may embed signed URLs or infrastructure details.
        message = str(exc) if isinstance(exc, FloodValidationError) else 'Resource discovery, configuration or worker validation failed.'
        report.update(real_data_check='FAIL', manual_review='NOT_READY', error=message)
        print(f'Phase 3C real-data check: FAIL — {message}', flush=True)
    report['completed_at'] = datetime.now(timezone.utc).isoformat()
    try:
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    except (OSError, ValueError, TypeError):
        print('Phase 3C real-data check: FAIL — could not save a valid result report.', flush=True)
        return 1
    if report['real_data_check'] == 'PASS':
        print('Phase 3C real-data check: PASS', flush=True)
        print('Coverage can be partial even when processing is complete; candidate water is not confirmed flooding.', flush=True)
    print(f'Terminal checkpoint saved: {args.output}', flush=True)
    return 0 if report['real_data_check'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
