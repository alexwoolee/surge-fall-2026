"""Preparation schema for worker-local reservoir records.

Only named analytical fields survive this boundary. Unknown metadata is not
interpreted, classified or copied. This module performs no filesystem access.
"""

from datetime import date
import math


DATA_FILES = frozenset({'weekly_ops_logs.jsonl', 'se_reports.jsonl', 'inspections_s10.jsonl',
                        'maintenance_requests.jsonl', 'instrumentation_log.jsonl'})
OBSERVATION_FIELDS = ('sealant_defects', 'seepage_at_crest_joint', 'relief_holes_blocked')


class DamRecordError(ValueError):
    """Fixed diagnostic; original fields and values are never included."""


def _reject():
    raise DamRecordError('A required analytical record field is invalid.')


def _day(value):
    if not isinstance(value, str) or len(value) != 10:
        _reject()
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _reject()
    if parsed.isoformat() != value:
        _reject()
    return value


def _boolean(value):
    if type(value) is not bool:
        _reject()
    return value


def _text_or_null(value):
    if value is not None and not isinstance(value, str):
        _reject()
    return value


def _object(value):
    if not isinstance(value, dict):
        _reject()
    return value


def project_record(filename: str, raw: dict) -> dict:
    """Validate selected fields and return a fresh, recursively projected record.

    Optional maintenance values remain absent or null as supplied. Date strings
    and numeric measurements retain their values; no record is ranked or chosen
    according to any discarded metadata.
    """
    try:
        if filename not in DATA_FILES or _object(raw).get('dam_id') != 'TODDBROOK':
            _reject()
        result = {'dam_id': 'TODDBROOK'}
        if filename == 'maintenance_requests.jsonl':
            result['opened'] = _day(raw['opened'])
            if 'available_date' in raw:
                result['available_date'] = _day(raw['available_date'])
            if 'closed_date' in raw:
                closed = raw['closed_date']
                result['closed_date'] = None if closed is None else _day(closed)
                if closed is not None and closed < result['opened']:
                    _reject()
            if 'item_class' in raw:
                result['item_class'] = _text_or_null(raw['item_class'])
        elif filename == 'instrumentation_log.jsonl':
            year = raw['year']
            if type(year) is not int or not 1800 <= year <= 2200:
                _reject()
            result.update(year=year, available_date=_day(raw['available_date']),
                          piezometer_readings_taken=_boolean(raw['piezometer_readings_taken']),
                          piezometer_data_plotted=_boolean(raw['piezometer_data_plotted']))
        else:
            result.update(date=_day(raw['date']), available_date=_day(raw['available_date']))
            if filename == 'weekly_ops_logs.jsonl':
                pool = raw['pool_level_mOD']
                if type(pool) not in (int, float) or not math.isfinite(pool) or not 0 <= pool <= 1000:
                    _reject()
                observations = _object(raw['observations'])
                result.update(pool_level_mOD=pool,
                              aux_spillway_flowing=_boolean(raw['aux_spillway_flowing']),
                              observations={name: _boolean(observations[name]) for name in OBSERVATION_FIELDS})
            elif filename == 'se_reports.jsonl':
                result['piezometers_serviceable'] = _boolean(raw['piezometers_serviceable'])
            else:
                grade = raw['grade_after']
                if grade not in ('A', 'B', 'C', 'D', 'E', None):
                    _reject()
                actions = raw['mios']
                if not isinstance(actions, list) or len(actions) > 100:
                    _reject()
                projected = []
                for action in actions:
                    _object(action)
                    projected.append({'klass': _text_or_null(action['klass'])} if 'klass' in action else {})
                result.update(grade_after=grade, mios=projected)
        return result
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        raise DamRecordError('A required analytical record field is invalid.') from None
