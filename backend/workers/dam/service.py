"""Read bounded local records and emit only validated aggregate screening evidence."""

from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path

from backend.shared.dam_contracts import (
    DamCounts, DamEvidence, DamMetrics, DamResult, DamRule, DamTask,
    LIMITATIONS, RULE_CRITERIA, WINDOWS, expected_rules, expected_summary,
)

_FILES = {
    'operations': 'weekly_ops_logs.jsonl', 'supervision': 'se_reports.jsonl',
    'inspection': 'inspections_s10.jsonl', 'maintenance': 'maintenance_requests.jsonl',
    'instrumentation': 'instrumentation_log.jsonl',
}
_FLAGS = ('sealant_defects', 'seepage_at_crest_joint', 'relief_holes_blocked')
_ENGINEERING = frozenset({'vegetation_and_patch_repairs', 'joint_sealant', 'seepage_review',
                         'left_wall', 'vegetation_in_joints', 'pressure_relief_holes',
                         'spillway_hydraulic_integrity'})
_MAX_BYTES = 4 * 1024 * 1024
_ERROR = 'Local evidence could not be validated.'


def _bad():
    raise ValueError(_ERROR)


def _day(value):
    if not isinstance(value, str) or len(value) != 10:
        _bad()
    try:
        result = date.fromisoformat(value)
        if result.isoformat() != value:
            _bad()
        return result
    except ValueError:
        _bad()


def _boolean(value):
    if type(value) is not bool:
        _bad()
    return value


def _number(value, minimum, maximum):
    if type(value) not in (float, int) or not math.isfinite(value) or not minimum <= value <= maximum:
        _bad()
    return float(value)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _bad()
        result[key] = value
    return result


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        _bad()
    if isinstance(value, dict):
        for item in value.values():
            _finite(item)
    elif isinstance(value, list):
        for item in value:
            _finite(item)


def _load(data_dir: Path, category: str):
    """Read exactly one approved regular file, with no directory or file API."""
    try:
        root = Path(data_dir).expanduser().resolve(strict=True)
        path = root / _FILES[category]
        if path.is_symlink() or not path.is_file() or not path.resolve(strict=True).is_relative_to(root) or path.stat().st_size > _MAX_BYTES:
            _bad()
        # The entire bounded read is local to the worker. No imported archive code runs.
        data = path.read_bytes()
        if len(data) > _MAX_BYTES:
            _bad()
        rows = []
        for line in data.decode('utf-8').splitlines():
            if not line.strip():
                continue
            if len(line.encode('utf-8')) > 65536 or len(rows) >= 10000:
                _bad()
            row = json.loads(line, parse_constant=lambda _: _bad(), object_pairs_hook=_unique)
            _finite(row)
            if not isinstance(row, dict) or row.get('dam_id') != 'TODDBROOK':
                _bad()
            rows.append(row)
        return rows
    except (OSError, UnicodeError, TypeError, ValueError, RecursionError, OverflowError):
        raise ValueError(_ERROR) from None


def _visible(data_dir, task):
    selected = {}
    for category in _FILES:
        rows = []
        reference_counts = {}
        for raw in _load(data_dir, category):
            try:
                if category == 'maintenance':
                    observed = _day(raw['opened'])
                    available = _day(raw.get('available_date', raw['opened']))
                elif category == 'instrumentation':
                    year = raw['year']
                    if type(year) is not int or not 1800 <= year <= 2200:
                        _bad()
                    observed = date(year, 12, 31)
                    available = _day(raw['available_date'])
                else:
                    observed, available = _day(raw['date']), _day(raw['available_date'])
                if observed > task.as_of or available > task.as_of:
                    continue
                if category == 'operations' and observed < WINDOWS[task.window][0]:
                    continue
                row = {'date': observed, 'available': available}
                if category == 'operations':
                    row['pool'] = _number(raw['pool_level_mOD'], 0, 1000)
                    row['flowing'] = _boolean(raw['aux_spillway_flowing'])
                    for flag in _FLAGS:
                        row[flag] = _boolean(raw['observations'][flag])
                elif category == 'supervision':
                    row['monitoring'] = _boolean(raw['piezometers_serviceable'])
                elif category == 'inspection':
                    grade = raw['grade_after']
                    if grade not in ('A', 'B', 'C', 'D', 'E', None):
                        _bad()
                    row['grade'] = grade
                    mios = raw['mios']
                    if not isinstance(mios, list) or len(mios) > 100 or any(not isinstance(item, dict) for item in mios):
                        _bad()
                    row['integrity'] = any(item.get('klass') == 'spillway_hydraulic_integrity' for item in mios)
                elif category == 'maintenance':
                    closed = _day(raw['closed_date']) if raw.get('closed_date') is not None else None
                    if closed is not None and closed < observed:
                        _bad()
                    # A future closure is never used to hide an item that was still open.
                    row['open'] = closed is None or closed > task.as_of
                    row['engineering'] = raw.get('item_class') in _ENGINEERING
                    row['integrity'] = raw.get('item_class') == 'spillway_hydraulic_integrity'
                else:
                    row['monitoring'] = _boolean(raw['piezometer_readings_taken']) and _boolean(raw['piezometer_data_plotted'])
                    # Validate both flags even when the first is false.
                    _boolean(raw['piezometer_data_plotted'])
                # Opaque references expose neither local names nor the original identifiers.
                key = (observed, available)
                ordinal = reference_counts.get(key, 0)
                reference_counts[key] = ordinal + 1
                identity = f'{category}:{observed.isoformat()}:{available.isoformat()}:{ordinal}'
                row['ref'] = 'r_' + hashlib.sha256(identity.encode()).hexdigest()[:24]
                rows.append(row)
            except (KeyError, TypeError, ValueError, OverflowError):
                raise ValueError(_ERROR) from None
        selected[category] = sorted(rows, key=lambda r: (r['date'], r['available'], r['ref']))
    return selected


def analyze(task: DamTask, *, data_dir: Path, progress=None) -> DamResult:
    rows = {key: [] for key in _FILES} if task.window == 'outside-coverage' else _visible(data_dir, task)
    if progress is not None:
        if task.window != 'outside-coverage':
            progress('dataset_located')
        progress('processing')
    operations = rows['operations']
    # Inclusive 90 calendar days, bounded by the selected supported interval.
    recent = [row for row in operations if row['date'] >= task.as_of - timedelta(days=89)]
    full = [row for row in recent if row['pool'] >= 185.64]
    latest = operations[-1] if operations else None
    supervision = rows['supervision'][-1] if rows['supervision'] else None
    instrumentation = rows['instrumentation'][-1] if rows['instrumentation'] else None
    inspection = rows['inspection'][-1] if rows['inspection'] else None
    opened = [row for row in rows['maintenance'] if row['open'] and row['engineering']]
    age = (task.as_of - latest['date']).days if latest else None
    monitoring_gap = (supervision is None or instrumentation is None
                      or not supervision['monitoring'] or not instrumentation['monitoring'])
    metrics = DamMetrics(
        recent_visit_count=len(recent), full_pool_visit_count=len(full),
        latest_pool_level_mod=latest['pool'] if latest else None,
        latest_pool_departure_m=round(latest['pool'] - 185.67, 6) if latest else None,
        latest_visit_age_days=age,
        latest_supervision_age_days=(task.as_of - supervision['date']).days if supervision else None,
        latest_instrumentation_age_days=(task.as_of - instrumentation['available']).days if instrumentation else None,
        sealant_defect_fraction=sum(row['sealant_defects'] for row in recent) / len(recent) if recent else None,
        blocked_relief_fraction=sum(row['relief_holes_blocked'] for row in recent) / len(recent) if recent else None,
        seepage_at_full_pool_fraction=sum(row['seepage_at_crest_joint'] for row in full) / len(full) if full else None,
        current_spillway_flowing=latest['flowing'] if latest and age <= 7 else None,
        open_maintenance_count=len(opened),
        long_open_maintenance_count=sum((task.as_of - row['date']).days > 365 for row in opened),
        latest_inspection_grade=inspection['grade'] if inspection else None,
        known_integrity_action=(inspection is not None and inspection['integrity']) or any(row['integrity'] for row in opened),
        monitoring_gap=monitoring_gap,
    )
    counts = DamCounts(**{key: len(value) for key, value in rows.items()})
    refs = [row['ref'] for group in rows.values() for row in group]
    evidence = DamEvidence(record_count=len(refs), record_refs=refs, counts=counts,
                           first_observation=operations[0]['date'] if operations else None,
                           last_observation=latest['date'] if latest else None)
    support_counts = {'D01': len(recent), 'D02': len(recent), 'D03': len(full),
                      'D04': len(opened), 'D05': int(inspection is not None) + len(opened),
                      'D06': int(latest is not None and age <= 7),
                      'D07': int(supervision is not None) + int(instrumentation is not None)}
    rules = [DamRule(rule_id=key, criterion=RULE_CRITERIA[key], triggered=value, record_count=support_counts[key])
             for key, value in expected_rules(metrics).items()]
    return DamResult(task_id=task.task_id, window=task.window, as_of=task.as_of,
                     summary=expected_summary(metrics, counts), metrics=metrics,
                     evidence=evidence, rules=rules, limitations=list(LIMITATIONS))


def run_dam_task(task: DamTask, progress, *, settings):
    result = analyze(task, data_dir=settings.dam_data_dir, progress=progress)
    return result.model_dump(mode='json')
