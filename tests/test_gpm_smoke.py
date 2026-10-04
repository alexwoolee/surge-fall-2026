"""Check the bounded smoke download workflow without NASA/network access."""

from types import SimpleNamespace

import pytest

from scripts.smoke import smoke_gpm


@pytest.fixture
def smoke_dependencies(tmp_path, monkeypatch):
    granules = [SimpleNamespace(data_links=lambda: []) for _ in range(2)]
    calls = {}

    def search(**kwargs):
        calls["search"] = kwargs
        return granules

    def download(selected, destination):
        calls["selected"] = selected
        files = []
        for index, _ in enumerate(selected):
            path = tmp_path / f"download-{index}.HDF5"
            path.write_bytes(b"mock download")
            files.append(path)
        return files

    monkeypatch.setattr(smoke_gpm, "DOWNLOAD_DIR", tmp_path)
    monkeypatch.setattr(smoke_gpm.earthaccess, "login", lambda: SimpleNamespace(authenticated=True))
    monkeypatch.setattr(smoke_gpm.earthaccess, "search_data", search)
    monkeypatch.setattr(smoke_gpm.earthaccess, "download", download)
    monkeypatch.setattr(smoke_gpm, "inspect_hdf5", lambda path: None)
    return calls, granules


@pytest.mark.parametrize("all_in_window, expected_count", [(False, 1), (True, 2)])
def test_download_scope(smoke_dependencies, monkeypatch, all_in_window, expected_count):
    calls, granules = smoke_dependencies
    monkeypatch.setattr("sys.argv", ["smoke_gpm.py"] + (["--all-in-window"] if all_in_window else []))
    smoke_gpm.main()
    assert calls["selected"] == granules[:expected_count]
    assert calls["search"]["count"] == (-1 if all_in_window else 5)


def test_partial_download_cannot_report_pass(smoke_dependencies, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("sys.argv", ["smoke_gpm.py", "--all-in-window"])
    path = tmp_path / "only-one.HDF5"
    path.write_bytes(b"mock download")
    monkeypatch.setattr(smoke_gpm.earthaccess, "download", lambda *args: [path])
    with pytest.raises(SystemExit) as error:
        smoke_gpm.main()
    assert error.value.code == 1
    output = capsys.readouterr().out
    assert "Not every selected granule" in output
    assert "GPM SMOKE TEST: PASS" not in output
