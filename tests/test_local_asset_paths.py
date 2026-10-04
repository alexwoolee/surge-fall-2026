"""Exercise both platform URI conventions without requiring Windows hardware."""

from pathlib import Path, PureWindowsPath

import pytest

from backend.workers.flood._raster import TerrainProcessingError, _file_uri_path, _local_path


@pytest.mark.parametrize("uri, expected", [
    ("file:///C:/Users/Kazi/source.tif", r"C:\Users\Kazi\source.tif"),
    ("file:///d:/Project%20Files/terrain.tif", r"D:\Project Files\terrain.tif"),
    ("file://LOCALHOST/C:/Project%20Files/terrain.tif", r"C:\Project Files\terrain.tif"),
    ("file:/C:/Project%20Files/terrain.tif", r"C:\Project Files\terrain.tif"),
    ("file:///C:/literal%2520name.tif", r"C:\literal%20name.tif"),
    ("file://server/share/Project%20Files/terrain.tif", r"\\server\share\Project Files\terrain.tif"),
    ("file:////server/share/terrain.tif", r"\\server\share\terrain.tif"),
])
def test_windows_file_uri_decoding_on_every_platform(uri, expected):
    assert _file_uri_path(uri, windows=True) == expected


@pytest.mark.parametrize("path", [
    PureWindowsPath(r"C:\Users\Kazi\Project Files\terrain.tif"),
    PureWindowsPath(r"\\server\share\folder\candidate_water.tif"),
])
def test_windows_path_as_uri_round_trip_has_the_same_drive_and_anchor(path):
    decoded = PureWindowsPath(_file_uri_path(path.as_uri(), windows=True))
    assert decoded == path
    assert decoded.drive == path.drive and decoded.anchor == path.anchor


@pytest.mark.parametrize("uri, expected", [
    ("file:///tmp/Project%20Files/terrain.tif", "/tmp/Project Files/terrain.tif"),
    ("file://LOCALHOST/tmp/terrain.tif", "/tmp/terrain.tif"),
    ("file:/tmp/terrain.tif", "/tmp/terrain.tif"),
    ("file:relative%20folder/terrain.tif", "relative folder/terrain.tif"),
    ("file:///tmp/literal%2520name.tif", "/tmp/literal%20name.tif"),
    ("file:///tmp/name%23with%3Fchars.tif", "/tmp/name#with?chars.tif"),
])
def test_posix_file_uri_decoding_on_every_platform(uri, expected):
    assert _file_uri_path(uri, windows=False) == expected


@pytest.mark.parametrize("href", [
    "relative folder/terrain.tif", "/tmp/terrain.tif", "literal%20name.tif",
    r"C:\Users\Kazi\terrain.tif", "C:/Users/Kazi/terrain.tif",
    "C://Users/Kazi/terrain.tif", r"\\server\share\terrain.tif",
])
def test_raw_filesystem_paths_keep_native_path_semantics(href):
    assert _local_path(href) == Path(href)


def test_native_file_uri_round_trip(tmp_path):
    path = tmp_path / "space and % sign.tif"
    assert _local_path(path.as_uri()) == path


@pytest.mark.parametrize("windows", [False, True])
@pytest.mark.parametrize("uri", [
    "file:///tmp/source.tif?token=private", "file:///tmp/source.tif#private",
    "file:///tmp/source.tif?", "file:///tmp/source.tif#", "file:///tmp/source%00.tif",
    "file://user:private@localhost/tmp/source.tif",
])
def test_ambiguous_file_uris_fail_closed_without_echoing_values(uri, windows):
    with pytest.raises(TerrainProcessingError, match="File URI") as caught:
        _file_uri_path(uri, windows=windows)
    assert "private" not in str(caught.value)


def test_posix_does_not_guess_a_local_mapping_for_remote_file_authority():
    with pytest.raises(TerrainProcessingError, match="File URI"):
        _file_uri_path("file://server/share/source.tif", windows=False)


@pytest.mark.parametrize("href", ["https://example.test/source.tif?sig=private", "s3://bucket/source.tif"])
def test_remote_asset_urls_are_not_local_files(href):
    assert _local_path(href) is None
