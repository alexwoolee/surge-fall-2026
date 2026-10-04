"""The portable installer never executes archive helpers or exposes record text."""

from pathlib import Path
import stat
import zipfile

import pytest

from scripts import install_private_dataset as installer


RECORD = b'{"dam_id":"TODDBROOK","private_note":"do not print this"}\n'


def archive(tmp_path, *, overrides=None, extras=()):
    path = tmp_path / "owner.zip"
    entries = {installer.ARCHIVE_PREFIX + name: RECORD for name in installer.DATA_FILES}
    entries.update(overrides or {})
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for name, data in entries.items():
            if data is not None:
                output.writestr(name, data)
        for name, data in extras:
            output.writestr(name, data)
    return path


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return root


def destination(root):
    return root / "private_data/toddbrook_dataset/data"


def test_exact_allowlist_installs_atomically_without_helpers_or_evaluation_files(tmp_path, repository, monkeypatch):
    path = archive(tmp_path, extras=[
        ("toddbrook_dataset/scripts/install.py", b"raise RuntimeError('must not run')"),
        ("toddbrook_dataset/data/ground_truth_EVAL_ONLY.csv", b"private evaluation"),
        ("toddbrook_dataset/__pycache__/helper.pyc", b"not code to execute"),
        ("toddbrook_dataset/README.md", b"untrusted instructions"),
    ])
    rename = installer.os.rename
    calls = []
    def publish(source, target):
        calls.append((source, target))
        assert not destination(repository).exists()
        assert {item.name for item in Path(source).iterdir()} == installer.DATA_FILES
        assert all(item.read_bytes() == RECORD for item in Path(source).iterdir())
        rename(source, target)
    monkeypatch.setattr(installer.os, "rename", publish)
    assert installer.install_dataset(path, repo_root=repository) == "installed"
    assert len(calls) == 1
    assert {item.name for item in destination(repository).iterdir()} == installer.DATA_FILES
    assert not (destination(repository).parent / ".install.lock").exists()
    assert not list(destination(repository).parent.glob(".install-*"))


def test_identical_install_preserves_unconsumed_existing_files_and_timestamps(tmp_path, repository):
    path = archive(tmp_path)
    installer.install_dataset(path, repo_root=repository)
    extra = destination(repository) / "owner-kept-document.txt"
    extra.write_bytes(b"preserve without reading")
    before = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in destination(repository).iterdir()}
    assert installer.install_dataset(path, repo_root=repository) == "unchanged"
    assert before == {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in destination(repository).iterdir()}


@pytest.mark.parametrize("incomplete", [False, True])
def test_different_or_incomplete_install_is_never_overwritten(tmp_path, repository, incomplete):
    path = archive(tmp_path)
    installer.install_dataset(path, repo_root=repository)
    selected = destination(repository) / sorted(installer.DATA_FILES)[0]
    if incomplete:
        selected.unlink()
    else:
        selected.write_bytes(b"existing owner content")
    before = {p.name: p.read_bytes() for p in destination(repository).iterdir()}
    with pytest.raises(installer.InstallError, match="Preserve and inspect"):
        installer.install_dataset(path, repo_root=repository)
    assert before == {p.name: p.read_bytes() for p in destination(repository).iterdir()}


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/drive", "safe/../../escape", "safe\\escape", "safe//escape", "safe/./escape"])
def test_unsafe_paths_are_rejected_even_for_unselected_entries(tmp_path, repository, name):
    path = archive(tmp_path, extras=[(name, b"ignored content")])
    with pytest.raises(installer.InstallError):
        installer.install_dataset(path, repo_root=repository)
    assert not (repository / "private_data").exists()


def test_archive_symlink_is_rejected_without_extracting_anything(tmp_path, repository):
    link = zipfile.ZipInfo("toddbrook_dataset/scripts/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(installer.InstallError):
        installer.install_dataset(archive(tmp_path, extras=[(link, b"/outside")]), repo_root=repository)
    assert not destination(repository).exists()


@pytest.mark.parametrize("bad", [b"not json", b"[]", b'{"dam_id":"OTHER"}', b'{"dam_id":"TODDBROOK","x":NaN}', b'{"dam_id":"TODDBROOK","x":1,"x":2}', b'{"dam_id":"TODDBROOK","x":1e999}', b"\xff"])
def test_bad_record_format_rejected_before_publish_without_content_in_error(tmp_path, repository, bad):
    path = archive(tmp_path, overrides={installer.ARCHIVE_PREFIX + "weekly_ops_logs.jsonl": bad})
    with pytest.raises(installer.InstallError) as error:
        installer.install_dataset(path, repo_root=repository)
    assert "private_note" not in str(error.value) and "do not print" not in str(error.value)
    assert not destination(repository).exists()


def test_missing_duplicate_and_alternate_root_members_are_not_accepted(tmp_path, repository):
    required = installer.ARCHIVE_PREFIX + "weekly_ops_logs.jsonl"
    path = archive(tmp_path, overrides={required: None}, extras=[("data/weekly_ops_logs.jsonl", RECORD)])
    with pytest.raises(installer.InstallError):
        installer.install_dataset(path, repo_root=repository)
    with pytest.warns(UserWarning, match="Duplicate"):
        path = archive(tmp_path, extras=[(required, RECORD)])
    with pytest.raises(installer.InstallError):
        installer.install_dataset(path, repo_root=repository)


@pytest.mark.parametrize("limit,value", [("MAX_ARCHIVE_BYTES", 1), ("MAX_MEMBER_BYTES", 1), ("MAX_TOTAL_BYTES", 100), ("MAX_ENTRIES", 4), ("MAX_LINE_BYTES", 10), ("MAX_ROWS", 0)])
def test_each_archive_and_record_bound_is_enforced(tmp_path, repository, monkeypatch, limit, value):
    path = archive(tmp_path)
    monkeypatch.setattr(installer, limit, value)
    with pytest.raises(installer.InstallError):
        installer.install_dataset(path, repo_root=repository)
    assert not destination(repository).exists()


@pytest.mark.parametrize("where", ["private_data", "private_data/toddbrook_dataset", "private_data/toddbrook_dataset/data", "private_data/toddbrook_dataset/data/weekly_ops_logs.jsonl"])
def test_existing_symlink_destination_is_not_followed(tmp_path, repository, where):
    outside = tmp_path / "outside"
    outside.mkdir()
    target = repository / where
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows account cannot create symbolic links.")
        raise
    with pytest.raises(installer.InstallError):
        installer.install_dataset(archive(tmp_path), repo_root=repository)
    assert list(outside.iterdir()) == []


def test_write_failure_keeps_destination_absent_and_cleans_staging(tmp_path, repository, monkeypatch):
    def fail(*args):
        raise OSError("private filesystem detail")
    monkeypatch.setattr(installer.os, "rename", fail)
    with pytest.raises(installer.InstallError) as error:
        installer.install_dataset(archive(tmp_path), repo_root=repository)
    assert "private filesystem detail" not in str(error.value)
    assert not destination(repository).exists()
    assert list(destination(repository).parent.iterdir()) == []


def test_active_install_lock_prevents_concurrent_publish(tmp_path, repository):
    parent = destination(repository).parent
    parent.mkdir(parents=True)
    (parent / ".install.lock").write_text("existing lock")
    with pytest.raises(installer.InstallError, match="Another install"):
        installer.install_dataset(archive(tmp_path), repo_root=repository)
    assert (parent / ".install.lock").read_text() == "existing lock"
    assert not destination(repository).exists()


def test_cli_reports_only_fixed_outcomes_and_uses_the_supplied_path(monkeypatch, capsys):
    received = []
    monkeypatch.setattr(installer, "install_dataset", lambda path: received.append(path) or "installed")
    assert installer.main(["private-owner.zip"]) == 0
    assert received == [Path("private-owner.zip")]
    assert "five required" in capsys.readouterr().out
    def fail(path):
        raise installer.InstallError("The archive does not satisfy the bounded dataset format.")
    monkeypatch.setattr(installer, "install_dataset", fail)
    assert installer.main(["private-owner.zip"]) == 2
    assert "private-owner.zip" not in capsys.readouterr().out
