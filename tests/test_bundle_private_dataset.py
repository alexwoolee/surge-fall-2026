"""Bundle publication uses only prepared inputs and deterministic ZIP metadata."""

from datetime import date
import json
import os
from pathlib import Path
import stat
import zipfile

import pytest

from backend.shared.dam_snapshots import snapshot_records
from scripts import bundle_private_dataset as builder
from test_install_private_dataset import ANALYTICAL_RECORDS, CANONICAL


DAYS = (date(2019, 7, 31), date(2019, 8, 1))


@pytest.fixture(autouse=True)
def short_calendar(monkeypatch):
    monkeypatch.setattr(builder, "snapshot_days", lambda: iter(reversed(DAYS)))


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repo"
    source = root / "private_data/toddbrook_runtime/data"
    source.mkdir(parents=True)
    for name, data in CANONICAL.items():
        (source / name).write_bytes(data)
    return root


def source(root):
    return root / "private_data/toddbrook_runtime/data"


def bundle(root):
    return source(root).parent / "as_of.zip"


def assert_no_temporary(root):
    assert not list(source(root).parent.glob(".as-of-bundle-*"))


def test_exact_deterministic_archive_and_unchanged_master_files(repository):
    masters = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in source(repository).iterdir()}
    assert builder.bundle_dataset(repo_root=repository) == "bundled"
    original = bundle(repository).read_bytes()
    original_mtime = bundle(repository).stat().st_mtime_ns
    with zipfile.ZipFile(bundle(repository)) as archive:
        expected = [f"{day}/data/{name}" for day in DAYS for name in sorted(builder.DATA_FILES)]
        assert archive.namelist() == expected
        for entry in archive.infolist():
            assert not entry.is_dir()
            assert entry.date_time == builder.FIXED_TIMESTAMP
            assert entry.create_system == 3
            assert entry.external_attr >> 16 == stat.S_IFREG | 0o600
            assert entry.compress_type == zipfile.ZIP_DEFLATED
        for day in DAYS:
            prepared = snapshot_records(CANONICAL, day)
            for name, content in prepared.items():
                assert archive.read(f"{day}/data/{name}") == content
    assert builder.bundle_dataset(repo_root=repository) == "unchanged"
    assert bundle(repository).read_bytes() == original
    assert bundle(repository).stat().st_mtime_ns == original_mtime
    assert masters == {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in source(repository).iterdir()}
    assert_no_temporary(repository)


def test_future_records_withheld_and_future_maintenance_closure_masked(repository):
    ops = ANALYTICAL_RECORDS["weekly_ops_logs.jsonl"]
    after_end = dict(ops, date="2019-08-01", available_date="2019-08-01", pool_level_mOD=199)
    later_available = dict(ops, date="2019-07-30", available_date="2019-08-01", pool_level_mOD=188)
    (source(repository) / "weekly_ops_logs.jsonl").write_text("\n".join(json.dumps(row) for row in (ops, after_end, later_available)) + "\n")
    request = dict(ANALYTICAL_RECORDS["maintenance_requests.jsonl"], closed_date="2019-08-01")
    (source(repository) / "maintenance_requests.jsonl").write_text(json.dumps(request) + "\n")
    builder.bundle_dataset(repo_root=repository)
    with zipfile.ZipFile(bundle(repository)) as archive:
        first = archive.read("2019-07-31/data/weekly_ops_logs.jsonl").decode().splitlines()
        second = archive.read("2019-08-01/data/weekly_ops_logs.jsonl").decode().splitlines()
        assert [json.loads(line)["pool_level_mOD"] for line in first] == [185.7]
        assert [json.loads(line)["pool_level_mOD"] for line in second] == [185.7, 188]
        assert json.loads(archive.read("2019-07-31/data/maintenance_requests.jsonl"))["closed_date"] is None
        assert json.loads(archive.read("2019-08-01/data/maintenance_requests.jsonl"))["closed_date"] == "2019-08-01"


def test_reads_only_five_masters_never_evaluation_archive_or_extra_documents(repository, monkeypatch):
    for name in ("evaluation.jsonl", "owner.zip", "private_notes.txt"):
        (source(repository) / name).write_bytes(b"must not open")
    opened = []
    original_open = os.open
    def guarded_open(path, flags, *args, **kwargs):
        path = Path(path)
        if path.parent == source(repository):
            assert path.name in builder.DATA_FILES
            opened.append(path.name)
        return original_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(builder.os, "open", guarded_open)
    builder.bundle_dataset(repo_root=repository)
    assert opened == sorted(builder.DATA_FILES)


@pytest.mark.parametrize("content", [
    b'{"dam_id":"TODDBROOK","dam_id":"TODDBROOK"}\n',
    b'not valid PRIVATE_MARKER json',
    b'\xff',
    json.dumps({**ANALYTICAL_RECORDS["weekly_ops_logs.jsonl"], "private_note": "PRIVATE_MARKER"}).encode(),
    json.dumps({**ANALYTICAL_RECORDS["weekly_ops_logs.jsonl"], "observations": {**ANALYTICAL_RECORDS["weekly_ops_logs.jsonl"]["observations"], "note": "PRIVATE_MARKER"}}).encode(),
    json.dumps({**ANALYTICAL_RECORDS["weekly_ops_logs.jsonl"], "pool_level_mOD": float("nan")}).encode(),
    json.dumps({**ANALYTICAL_RECORDS["weekly_ops_logs.jsonl"], "date": "2019-02-31"}).encode(),
    json.dumps({**ANALYTICAL_RECORDS["weekly_ops_logs.jsonl"], "dam_id": "PRIVATE_MARKER"}).encode(),
])
def test_invalid_prepared_content_fails_without_disclosure_or_replacing_bundle(repository, content):
    bundle(repository).write_bytes(b"existing bundle preserved")
    before = bundle(repository).stat().st_mtime_ns
    (source(repository) / "weekly_ops_logs.jsonl").write_bytes(content)
    with pytest.raises(builder.BundleError) as error:
        builder.bundle_dataset(repo_root=repository)
    assert "PRIVATE_MARKER" not in str(error.value)
    assert str(repository) not in str(error.value)
    assert bundle(repository).read_bytes() == b"existing bundle preserved"
    assert bundle(repository).stat().st_mtime_ns == before
    assert_no_temporary(repository)


@pytest.mark.parametrize("limit,value", [
    ("MAX_FILE_BYTES", 1), ("MAX_ROWS", 0), ("MAX_LINE_BYTES", 1),
    ("MAX_UNCOMPRESSED_BYTES", 1), ("MAX_ENTRIES", 1), ("MAX_ARCHIVE_BYTES", 1),
])
def test_resource_limits_reject_without_publishing(repository, monkeypatch, limit, value):
    monkeypatch.setattr(builder, limit, value)
    with pytest.raises(builder.BundleError):
        builder.bundle_dataset(repo_root=repository)
    assert not bundle(repository).exists()
    assert_no_temporary(repository)


def test_missing_master_rejected_without_publish(repository):
    (source(repository) / "se_reports.jsonl").unlink()
    with pytest.raises(builder.BundleError):
        builder.bundle_dataset(repo_root=repository)
    assert not bundle(repository).exists()


@pytest.mark.parametrize("target", ["root", "data", "master", "bundle"])
def test_symlinks_are_rejected(repository, tmp_path, target):
    path = {"root": repository, "data": source(repository), "master": source(repository) / "se_reports.jsonl", "bundle": bundle(repository)}[target]
    outside = tmp_path / f"outside-{target}"
    if target == "bundle":
        outside.write_bytes(b"outside untouched")
    else:
        path.rename(outside)
    try:
        path.symlink_to(outside, target_is_directory=outside.is_dir())
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows account lacks symlink privilege")
        raise
    with pytest.raises(builder.BundleError):
        builder.bundle_dataset(repo_root=repository)
    if target == "bundle":
        assert outside.read_bytes() == b"outside untouched"


def test_changed_inputs_publish_atomically_and_failed_publish_preserves_existing(repository, monkeypatch):
    builder.bundle_dataset(repo_root=repository)
    before = bundle(repository).read_bytes()
    row = dict(ANALYTICAL_RECORDS["weekly_ops_logs.jsonl"], pool_level_mOD=186.1)
    (source(repository) / "weekly_ops_logs.jsonl").write_text(json.dumps(row) + "\n")
    replace = os.replace
    def fail_replace(temporary, destination):
        assert Path(destination) == bundle(repository)
        assert bundle(repository).read_bytes() == before
        assert Path(temporary).read_bytes() != before
        raise OSError("PRIVATE_MARKER")
    monkeypatch.setattr(builder.os, "replace", fail_replace)
    with pytest.raises(builder.BundleError, match="could not be built") as error:
        builder.bundle_dataset(repo_root=repository)
    assert "PRIVATE_MARKER" not in str(error.value)
    assert bundle(repository).read_bytes() == before
    assert_no_temporary(repository)
    monkeypatch.setattr(builder.os, "replace", replace)
    assert builder.bundle_dataset(repo_root=repository) == "bundled"
    assert bundle(repository).read_bytes() != before


def test_cli_fixed_success_and_failure_messages(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["bundle_private_dataset"])
    monkeypatch.setattr(builder, "bundle_dataset", lambda: "unchanged")
    assert builder.main() == 0
    assert capsys.readouterr().out == "Prepared historical input bundle: unchanged.\n"
    def fail():
        raise builder.BundleError("Only prepared analytical fields are accepted.")
    monkeypatch.setattr(builder, "bundle_dataset", fail)
    assert builder.main() == 2
    assert capsys.readouterr().out == "Only prepared analytical fields are accepted.\n"
