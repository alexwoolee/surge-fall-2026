"""Offline preparation of exact-date analytical inputs.

Worker execution selects a prepared day; it must never call the preparation
functions on the full owner archive. This module has no filesystem access.
"""

from datetime import date, timedelta
import json

from backend.shared.dam_records import DATA_FILES, project_record


OBSERVATION_WINDOWS = {
    '2007-2008': (date(2007, 9, 3), date(2008, 2, 29)),
    '2015-2019': (date(2015, 10, 1), date(2019, 7, 31)),
}
ASSESSMENT_WINDOWS = {key: (start, end + timedelta(days=7))
                      for key, (start, end) in OBSERVATION_WINDOWS.items()}


class SnapshotError(ValueError):
    """A fixed preparation diagnostic without original record contents."""


def period_for(as_of):
    if type(as_of) is not date:
        raise SnapshotError('An exact assessment date is required.')
    return next((key for key, (start, end) in ASSESSMENT_WINDOWS.items() if start <= as_of <= end), None)


def snapshot_days():
    for start, end in ASSESSMENT_WINDOWS.values():
        day = start
        while day <= end:
            yield day
            day += timedelta(days=1)


def _prepared_rows(files):
    if set(files) != DATA_FILES:
        raise SnapshotError('Five prepared analytical inputs are required.')
    result = {}
    for filename in sorted(DATA_FILES):
        rows = []
        for line in files[filename].decode('utf-8').splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            record = project_record(filename, raw)
            if record != raw:
                raise SnapshotError('Only prepared analytical inputs are accepted.')
            if filename == 'maintenance_requests.jsonl':
                event = date.fromisoformat(record['opened'])
                available = date.fromisoformat(record.get('available_date', record['opened']))
            elif filename == 'instrumentation_log.jsonl':
                event = date(record['year'], 12, 31)
                available = date.fromisoformat(record['available_date'])
            else:
                event = date.fromisoformat(record['date'])
                available = date.fromisoformat(record['available_date'])
            rows.append((record, event, available))
        result[filename] = rows
    return result


def iter_snapshots(files, *, dates=None):
    """Yield canonical daily inputs with future records and closures removed."""
    rows = _prepared_rows(files)
    for as_of in snapshot_days() if dates is None else dates:
        period = period_for(as_of)
        if period is None:
            raise SnapshotError('The requested date has no prepared assessment period.')
        start, observed_end = OBSERVATION_WINDOWS[period]
        prepared = {}
        for filename, records in rows.items():
            selected = []
            for original, event, available in records:
                if event > as_of or available > as_of:
                    continue
                if filename == 'weekly_ops_logs.jsonl' and not start <= event <= observed_end:
                    continue
                record = original.copy()
                if filename == 'maintenance_requests.jsonl' and record.get('closed_date') is not None:
                    if date.fromisoformat(record['closed_date']) > as_of:
                        record['closed_date'] = None
                selected.append(json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n')
            prepared[filename] = ''.join(selected).encode('utf-8')
        yield as_of, prepared


def snapshot_records(files, as_of):
    return next(iter_snapshots(files, dates=[as_of]))[1]
