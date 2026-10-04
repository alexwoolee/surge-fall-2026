"""The offline boundary removes all records and closure facts after the cutoff."""

from datetime import date, timedelta
import json

import pytest

from backend.shared.dam_snapshots import (
    ASSESSMENT_WINDOWS, OBSERVATION_WINDOWS, SnapshotError, iter_snapshots,
    period_for, snapshot_days, snapshot_records,
)
from test_install_private_dataset import ANALYTICAL_RECORDS, CANONICAL


def encode(records):
    return ''.join(json.dumps(row) + '\n' for row in records).encode()


def decode(files, name):
    return [json.loads(line) for line in files[name].splitlines()]


def test_daily_preparation_covers_only_both_periods_and_seven_day_tails():
    days = list(snapshot_days())
    assert len(days) == len(set(days))
    assert date(2007, 9, 3) in days and date(2019, 8, 1) in days
    for key, (first, last) in OBSERVATION_WINDOWS.items():
        assert ASSESSMENT_WINDOWS[key] == (first, last+timedelta(days=7))
        assert first in days and last+timedelta(days=7) in days
        assert period_for(first) == key
        assert period_for(last+timedelta(days=7)) == key
        assert period_for(first-timedelta(days=1)) is None
        assert period_for(last+timedelta(days=8)) is None
    assert period_for(date(2013, 1, 1)) is None


def test_future_event_and_availability_records_are_absent_from_prepared_bytes():
    ops = ANALYTICAL_RECORDS['weekly_ops_logs.jsonl']
    old = {**ops, 'date': '2019-07-29', 'available_date': '2019-07-29'}
    future_event = {**ops, 'date': '2019-07-31', 'available_date': '2019-07-29', 'pool_level_mOD': 999.0}
    future_available = {**ops, 'date': '2019-07-29', 'available_date': '2019-07-31', 'pool_level_mOD': 998.0}
    files = {**CANONICAL, 'weekly_ops_logs.jsonl': encode([old, future_event, future_available])}
    selected = snapshot_records(files, date(2019, 7, 30))
    assert decode(selected, 'weekly_ops_logs.jsonl') == [old]
    assert b'999' not in selected['weekly_ops_logs.jsonl'] and b'998' not in selected['weekly_ops_logs.jsonl']
    assert b'2019-07-31' not in selected['weekly_ops_logs.jsonl']


def test_future_maintenance_closure_is_removed_until_its_exact_day():
    row = {**ANALYTICAL_RECORDS['maintenance_requests.jsonl'], 'closed_date': '2019-08-01'}
    files = {**CANONICAL, 'maintenance_requests.jsonl': encode([row])}
    before = snapshot_records(files, date(2019, 7, 31))
    after = snapshot_records(files, date(2019, 8, 1))
    assert decode(before, 'maintenance_requests.jsonl') == [{**row, 'closed_date': None}]
    assert b'2019-08-01' not in before['maintenance_requests.jsonl']
    assert decode(after, 'maintenance_requests.jsonl') == [row]


def test_2019_august_first_receives_july_last_observation_without_future_data():
    ops = ANALYTICAL_RECORDS['weekly_ops_logs.jsonl']
    outside_source_window = {**ops, 'date': '2019-08-01', 'available_date': '2019-08-01'}
    files = {**CANONICAL, 'weekly_ops_logs.jsonl': encode([ops, outside_source_window])}
    selected = snapshot_records(files, date(2019, 8, 1))
    assert decode(selected, 'weekly_ops_logs.jsonl') == [ops]


def test_partial_year_instrumentation_and_unreleased_inspection_are_not_inputs():
    instrumentation = {**ANALYTICAL_RECORDS['instrumentation_log.jsonl'], 'year': 2007, 'available_date': '2007-09-30'}
    inspection = {**ANALYTICAL_RECORDS['inspections_s10.jsonl'], 'date': '2007-10-01', 'available_date': '2008-01-01'}
    files = {**CANONICAL, 'instrumentation_log.jsonl': encode([instrumentation]), 'inspections_s10.jsonl': encode([inspection])}
    selected = snapshot_records(files, date(2007, 12, 9))
    assert selected['instrumentation_log.jsonl'] == b''
    assert selected['inspections_s10.jsonl'] == b''
    known = snapshot_records(files, date(2008, 1, 1))
    assert decode(known, 'instrumentation_log.jsonl') == [instrumentation]
    assert decode(known, 'inspections_s10.jsonl') == [inspection]


def test_2007_snapshot_does_not_receive_any_2019_record_or_reference():
    ops = {**ANALYTICAL_RECORDS['weekly_ops_logs.jsonl'], 'date': '2007-12-09', 'available_date': '2007-12-09'}
    files = {**CANONICAL, 'weekly_ops_logs.jsonl': encode([ops, ANALYTICAL_RECORDS['weekly_ops_logs.jsonl']])}
    selected = snapshot_records(files, date(2007, 12, 9))
    assert decode(selected, 'weekly_ops_logs.jsonl') == [ops]
    assert all(b'2019' not in data and b'2018' not in data for data in selected.values())


def test_2019_snapshot_drops_previous_window_operations():
    ops = ANALYTICAL_RECORDS['weekly_ops_logs.jsonl']
    old = {**ops, 'date': '2007-12-09', 'available_date': '2007-12-09'}
    selected = snapshot_records({**CANONICAL, 'weekly_ops_logs.jsonl': encode([old, ops])}, date(2019, 7, 31))
    assert decode(selected, 'weekly_ops_logs.jsonl') == [ops]


def test_snapshots_are_deterministic_and_do_not_modify_prepared_inputs():
    original = dict(CANONICAL)
    dates = [date(2019, 7, 31), date(2019, 8, 1)]
    assert list(iter_snapshots(CANONICAL, dates=dates)) == list(iter_snapshots(CANONICAL, dates=dates))
    assert CANONICAL == original


@pytest.mark.parametrize('day', [date(2013, 1, 1), date(2019, 8, 8)])
def test_no_snapshot_is_built_for_unsupported_dates(day):
    with pytest.raises(SnapshotError):
        snapshot_records(CANONICAL, day)


def test_snapshot_preparation_accepts_only_projected_inputs():
    polluted = {**ANALYTICAL_RECORDS['weekly_ops_logs.jsonl'], 'discarded_field': 'must not enter runtime'}
    with pytest.raises(SnapshotError):
        snapshot_records({**CANONICAL, 'weekly_ops_logs.jsonl': encode([polluted])}, date(2019, 7, 31))
