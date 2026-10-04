"""Preparation accesses only analytical fields and never interprets other metadata."""

from copy import deepcopy

import pytest

from backend.shared.dam_records import DamRecordError, project_record
from test_install_private_dataset import ANALYTICAL_RECORDS


@pytest.mark.parametrize('filename', ANALYTICAL_RECORDS)
def test_projection_preserves_required_measurements_and_dates(filename):
    expected = ANALYTICAL_RECORDS[filename]
    row = {**deepcopy(expected), 'arbitrary_unconsumed': {'nested': ['not inspected']}}
    result = project_record(filename, row)
    assert result == expected
    assert result is not row


class NoMetadataTraversal(dict):
    def items(self):
        raise AssertionError('All metadata values were traversed.')
    def values(self):
        raise AssertionError('All metadata values were traversed.')
    def __iter__(self):
        raise AssertionError('Unknown metadata keys were traversed.')


def test_unselected_metadata_values_are_not_inspected_or_classified():
    ops = deepcopy(ANALYTICAL_RECORDS['weekly_ops_logs.jsonl'])
    ops['observations'] = NoMetadataTraversal({**ops['observations'], 'ignored': object()})
    guarded = NoMetadataTraversal({**ops, 'ignored': object()})
    assert project_record('weekly_ops_logs.jsonl', guarded) == ANALYTICAL_RECORDS['weekly_ops_logs.jsonl']
    inspection = NoMetadataTraversal({**ANALYTICAL_RECORDS['inspections_s10.jsonl'],
                                      'mios': [NoMetadataTraversal({'klass': 'spillway_hydraulic_integrity', 'ignored': object()})]})
    assert project_record('inspections_s10.jsonl', inspection)['mios'] == [{'klass': 'spillway_hydraulic_integrity'}]


def test_optional_maintenance_fields_remain_absent_or_null():
    basic = {'dam_id': 'TODDBROOK', 'opened': '2017-01-01'}
    assert project_record('maintenance_requests.jsonl', basic) == basic
    nullable = {**basic, 'closed_date': None, 'item_class': None, 'available_date': '2017-01-02'}
    assert project_record('maintenance_requests.jsonl', nullable) == nullable


@pytest.mark.parametrize('filename,field,value', [
    ('weekly_ops_logs.jsonl', 'pool_level_mOD', float('nan')),
    ('weekly_ops_logs.jsonl', 'pool_level_mOD', float('inf')),
    ('weekly_ops_logs.jsonl', 'pool_level_mOD', True),
    ('weekly_ops_logs.jsonl', 'aux_spillway_flowing', 'false'),
    ('weekly_ops_logs.jsonl', 'observations', {'sealant_defects': False}),
    ('weekly_ops_logs.jsonl', 'available_date', 'tomorrow'),
    ('se_reports.jsonl', 'piezometers_serviceable', 0),
    ('inspections_s10.jsonl', 'grade_after', 'PRIVATE_INVALID_GRADE'),
    ('inspections_s10.jsonl', 'mios', [{'klass': {'arbitrary': 'text'}}]),
    ('inspections_s10.jsonl', 'mios', [None]),
    ('maintenance_requests.jsonl', 'closed_date', '2016-01-01'),
    ('maintenance_requests.jsonl', 'item_class', ['PRIVATE_RAW_ITEM']),
    ('instrumentation_log.jsonl', 'year', True),
    ('instrumentation_log.jsonl', 'piezometer_data_plotted', 'yes'),
])
def test_malformed_analytical_fields_are_rejected_without_echoing_values(filename, field, value):
    row = {**deepcopy(ANALYTICAL_RECORDS[filename]), field: value}
    with pytest.raises(DamRecordError, match='^A required analytical record field is invalid.$'):
        project_record(filename, row)


def test_unknown_file_cannot_become_a_new_runtime_input():
    with pytest.raises(DamRecordError):
        project_record('another.jsonl', {'dam_id': 'TODDBROOK'})


def test_projection_does_not_select_records_based_on_discarded_values():
    base = ANALYTICAL_RECORDS['weekly_ops_logs.jsonl']
    variants = [{**deepcopy(base), 'unused': value} for value in (None, True, False, 'first', 'second', {'nested': []})]
    assert [project_record('weekly_ops_logs.jsonl', row) for row in variants] == [base] * len(variants)
