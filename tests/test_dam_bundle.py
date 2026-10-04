"""A Dam job reads only its exact-day bundled inputs, without extraction."""

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import stat
import warnings
import zipfile

import pytest

from backend.shared.dam_contracts import DamTask
from backend.shared.dam_snapshots import snapshot_records
from backend.shared.settings import WorkerSettings
from backend.workers.dam import service
from test_dam_worker import FILES, records, task, visit, write_snapshot


ERROR = '^Local evidence could not be validated.$'


def prepared(rows, day):
    source = {FILES[key]: ''.join(json.dumps(row) + '\n' for row in values).encode()
              for key, values in rows.items()}
    return {f'{day}/data/{name}': content
            for name, content in snapshot_records(source, date.fromisoformat(day)).items()}


def write_bundle(root, entries, *, compression=zipfile.ZIP_DEFLATED):
    path = root / 'as_of.zip'
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        with zipfile.ZipFile(path, 'w', compression=compression) as package:
            for name, content in entries:
                package.writestr(name, content)
    return path


def run(root, requested=None):
    return service.run_dam_task(requested or task(), None,
                                settings=WorkerSettings(dam_data_dir=root / 'data'))


def test_bundle_opens_only_requested_members_and_never_extracts(tmp_path, records, monkeypatch):
    rows = deepcopy(records)
    rows['operations'] += [visit(day) for day in ('2007-12-01', '2007-12-04', '2007-12-09')]
    requested = DamTask(task_id='bundle-test', window='2007-2008', as_of='2007-12-09')
    selected = prepared(rows, '2007-12-09')
    other_day = {name: b'\xffINVALID_UNOPENED_RECORD' for name in prepared(rows, '2019-08-01')}
    archive = write_bundle(tmp_path, {**selected, **other_day}.items())
    reference = tmp_path / 'reference'
    reference.mkdir()
    for name, data in selected.items():
        (reference / name.rsplit('/', 1)[1]).write_bytes(data)
    expected = service.analyze(requested, data_dir=reference).model_dump(mode='json')
    opened = []
    member_open, path_open = zipfile.ZipFile.open, Path.open

    def bounded_member(package, member, *args, **kwargs):
        name = member.filename if isinstance(member, zipfile.ZipInfo) else member
        assert name in selected, 'Another date or nonanalytical member was opened.'
        opened.append(name)
        return member_open(package, member, *args, **kwargs)

    def only_bundle(path, *args, **kwargs):
        assert path == archive, 'Worker opened another private file.'
        return path_open(path, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, 'open', bounded_member)
    monkeypatch.setattr(zipfile.ZipFile, 'extract', lambda *a, **k: pytest.fail('Extraction attempted.'))
    monkeypatch.setattr(zipfile.ZipFile, 'extractall', lambda *a, **k: pytest.fail('Extraction attempted.'))
    monkeypatch.setattr(Path, 'open', only_bundle)
    monkeypatch.setattr(Path, 'read_bytes', lambda *a: pytest.fail('Folder or master records read.'))
    result = run(tmp_path, requested)
    assert result == expected
    assert len(opened) == 5 and set(opened) == set(selected)
    assert not (tmp_path / 'as_of').exists()


def test_bundle_has_priority_over_legacy_folders(tmp_path, records):
    _, legacy = write_snapshot(tmp_path, records, task())
    before = service.analyze(task(), data_dir=legacy)
    rows = deepcopy(records)
    rows['inspection'][0]['grade_after'] = 'D'
    rows['operations'][-1].update(pool_level_mOD=186., aux_spillway_flowing=True)
    write_bundle(tmp_path, prepared(rows, '2019-07-31').items())
    assert before.summary.risk_level == 'low'
    assert run(tmp_path)['summary']['risk_level'] == 'critical'


@pytest.mark.parametrize('case', ['not_zip', 'missing_date', 'missing_member', 'duplicate',
                                  'unapproved_member', 'traversal', 'unsupported_date', 'directory',
                                  'symlink_member', 'unsupported_compression', 'encrypted', 'bad_crc'])
def test_invalid_present_bundle_never_falls_back(tmp_path, records, monkeypatch, case):
    write_snapshot(tmp_path, records, task())
    entries = list(prepared(records, '2019-07-31').items())
    if case == 'missing_date': entries = list(prepared(records, '2019-08-01').items())
    elif case == 'missing_member': entries.pop()
    elif case == 'duplicate': entries.append(entries[0])
    elif case == 'unapproved_member': entries.append(('2019-07-31/data/unused.jsonl', b'ignored'))
    elif case == 'traversal': entries.append(('../data/weekly_ops_logs.jsonl', b'ignored'))
    elif case == 'unsupported_date': entries.append(('2013-01-01/data/weekly_ops_logs.jsonl', b''))
    elif case == 'directory': entries.append(('2019-07-31/data/', b''))
    elif case == 'symlink_member':
        info = zipfile.ZipInfo(entries[0][0]); info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        entries[0] = (info, b'elsewhere')
    compression = zipfile.ZIP_BZIP2 if case == 'unsupported_compression' else zipfile.ZIP_STORED if case == 'bad_crc' else zipfile.ZIP_DEFLATED
    archive = write_bundle(tmp_path, entries, compression=compression)
    if case == 'not_zip': archive.write_bytes(b'INVALID_PRIVATE_BYTES')
    elif case == 'encrypted':
        encoded = bytearray(archive.read_bytes())
        central = encoded.index(b'PK\x01\x02')
        encoded[central + 8] |= 1  # Encryption flag in the invented archive's central directory.
        archive.write_bytes(encoded)
    elif case == 'bad_crc':
        encoded = bytearray(archive.read_bytes())
        start = encoded.index(entries[0][1])
        encoded[start] ^= 1  # Corrupt a stored member while preserving its declared CRC.
        archive.write_bytes(encoded)
    monkeypatch.setattr(Path, 'read_bytes', lambda *a: pytest.fail('Legacy fallback attempted.'))
    with pytest.raises(ValueError, match=ERROR): run(tmp_path)


@pytest.mark.parametrize('field', ['_MAX_BUNDLE_BYTES', '_MAX_BUNDLE_ENTRIES',
                                  '_MAX_BUNDLE_TOTAL_BYTES', '_MAX_BYTES'])
def test_bundle_resource_limits_reject_before_any_member_read(tmp_path, records, monkeypatch, field):
    write_bundle(tmp_path, prepared(records, '2019-07-31').items())
    monkeypatch.setattr(service, field, 1)
    monkeypatch.setattr(zipfile.ZipFile, 'open', lambda *a, **k: pytest.fail('Over-budget member opened.'))
    with pytest.raises(ValueError, match=ERROR): run(tmp_path)


@pytest.mark.parametrize('case', ['extra_field', 'future_event', 'future_available',
                                  'future_closure', 'incomplete_year', 'wrong_window'])
def test_corrupt_snapshot_contents_fail_instead_of_filtering(tmp_path, records, case):
    entries = prepared(records, '2019-07-31')
    name = '2019-07-31/data/weekly_ops_logs.jsonl'
    row = visit('2019-07-31')
    if case == 'extra_field': row['unused_marker'] = 'PRIVATE_DO_NOT_EXPOSE'
    elif case == 'future_event': row['date'] = '2019-08-01'
    elif case == 'future_available': row['available_date'] = '2019-08-01'
    elif case == 'wrong_window': row.update(date='2007-12-09', available_date='2007-12-09')
    elif case == 'future_closure':
        name = '2019-07-31/data/maintenance_requests.jsonl'
        row = {**records['maintenance'][0], 'closed_date': '2019-08-01'}
    elif case == 'incomplete_year':
        name = '2019-07-31/data/instrumentation_log.jsonl'
        row = {**records['instrumentation'][0], 'year': 2019}
    entries[name] = (json.dumps(row) + '\n').encode()
    write_bundle(tmp_path, entries.items())
    with pytest.raises(ValueError, match=ERROR): run(tmp_path)


def test_bundle_symlink_rejected_even_when_legacy_snapshots_exist(tmp_path, records):
    write_snapshot(tmp_path, records, task())
    archive = write_bundle(tmp_path, prepared(records, '2019-07-31').items())
    other = tmp_path / 'other.zip'
    archive.rename(other)
    try:
        archive.symlink_to(other)
    except OSError as error:
        if getattr(error, 'winerror', None) == 1314:
            pytest.skip('Windows account lacks symlink privilege.')
        raise
    with pytest.raises(ValueError, match=ERROR): run(tmp_path)


def test_outside_coverage_never_opens_bundle_or_private_files(tmp_path, monkeypatch):
    settings = WorkerSettings(dam_data_dir=tmp_path / 'data')
    monkeypatch.setattr(Path, 'open', lambda *a, **k: pytest.fail('Private file opened.'))
    monkeypatch.setattr(zipfile, 'ZipFile', lambda *a, **k: pytest.fail('Archive opened.'))
    requested = DamTask(window='outside-coverage', as_of='2013-01-01')
    result = service.run_dam_task(requested, None, settings=settings)
    assert result['summary']['risk_level'] == 'unknown'
    assert result['evidence']['record_count'] == 0
