"""Live NASA selection is mandatory; I/O limits and credentials stay local."""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from backend.shared.context_contracts import ContextTask
from backend.workers.hydro import context_sources as sources


NAME = "3B-HHR.MS.MRG.3IMERG.20190725-S230000-E232959.1380.V07B.HDF5"
SOIL = "SMAP_L4_SM_gph_20190725T223000_Vv8010_001.h5"


def requested():
    return ContextTask(task_id="nasa-test", analysis_type="hydrometeorology", location_id="arbitrary-aoi",
                       bbox={"west": 10., "south": 20., "east": 10.2, "north": 20.2}, as_of="2019-07-25",
                       start_time="2019-07-25T00:00:00Z", end_time="2019-07-26T00:00:00Z")


class Granule(dict):
    def __init__(self, name=NAME, url=None):
        super().__init__(umm={"GranuleUR": name})
        self.url = url or "https://gpm1.gesdisc.eosdis.nasa.gov/data/" + name

    def data_links(self, *, access):
        assert access == "external"
        return [self.url]


def mock_query(monkeypatch, found):
    import earthaccess
    calls = []
    class Query:
        def __init__(self): self.session = SimpleNamespace(close=lambda: None)
        def parameters(self, **kwargs): calls.append(kwargs); return self
        def get(self, limit): calls.append(limit); return found
    monkeypatch.setattr(earthaccess, "DataGranules", Query)
    return calls


def test_runtime_discovery_receives_requested_aoi_dates_and_exact_product(monkeypatch, tmp_path):
    calls = mock_query(monkeypatch, [Granule()])
    (tmp_path / NAME).write_bytes(b"cached only after live discovery")
    provider = sources.NASAContextProvider()
    monkeypatch.setattr(provider, "_login", lambda: pytest.fail("Exact cache hit needs no new download login"))
    paths, reason = sources.live_paths(provider, "gpm", requested(), tmp_path)
    assert reason is None and paths == [tmp_path / NAME]
    assert calls[0]["bounding_box"] == (10., 20., 10.2, 20.2)
    assert calls[0]["short_name"] == "GPM_3IMERGHH"
    assert calls[0]["temporal"][0].startswith("2019-07-25T00:00:00")
    assert calls[0]["temporal"][1].startswith("2019-07-25T23:59:59")
    assert calls[1] == 337


def test_cmr_collection_prefix_is_not_a_local_filename_or_path():
    name, interval = sources.granule_identity(Granule("GPM_3IMERGHH.07:" + NAME), "gpm")
    assert name == NAME and interval[0].hour == 23
    with pytest.raises(sources.SourceUnavailable):
        sources.granule_identity(Granule("UNRELATED.07:" + NAME), "gpm")


def test_existing_cache_does_not_override_empty_live_catalog(monkeypatch, tmp_path):
    mock_query(monkeypatch, [])
    (tmp_path / NAME).write_bytes(b"previous cached file")
    paths, reason = sources.live_paths(sources.NASAContextProvider(), "gpm", requested(), tmp_path)
    assert paths == [] and reason == "source_unavailable"


def test_smap_selection_includes_only_latest_wholly_contained_three_hours(monkeypatch):
    mock_query(monkeypatch, [Granule(SOIL.replace("223000", "193000")), Granule(SOIL),
                            Granule(SOIL.replace("20190725T223000", "20190726T013000"))])
    selected = sources.NASAContextProvider().search("smap", requested())
    assert len(selected) == 1 and selected[0][1] == SOIL
    assert selected[0][2][0].hour == 21 and selected[0][2][1].day == 26


@pytest.mark.parametrize("found,reason", [([Granule()] * 337, "resource_limit"),
                                          ([Granule(), Granule()], "invalid_result"),
                                          ([Granule("../../owner.json")], "invalid_result")])
def test_invalid_or_excessive_catalog_never_downloads(monkeypatch, tmp_path, found, reason):
    mock_query(monkeypatch, found)
    provider = sources.NASAContextProvider()
    monkeypatch.setattr(provider, "obtain", lambda *a: pytest.fail("Invalid catalog must not download"))
    assert sources.live_paths(provider, "gpm", requested(), tmp_path) == ([], reason)


def test_timeout_error_has_no_provider_detail(monkeypatch, tmp_path):
    provider = sources.NASAContextProvider()
    def fail(*args): raise requests.Timeout("https://secret.example/?token=NEVER_RETURN")
    monkeypatch.setattr(provider, "search", fail)
    assert sources.live_paths(provider, "gpm", requested(), tmp_path) == ([], "provider_timeout")


def test_login_never_uses_interactive_or_persists_credentials(monkeypatch, caplog):
    import earthaccess.auth
    import logging
    calls = []
    class Auth:
        def login(self, **kwargs):
            calls.append(kwargs)
            logging.getLogger("earthaccess.auth").error("Raw provider secret MUST_NOT_APPEAR")
            raise RuntimeError("credential detail")
    monkeypatch.setattr(earthaccess.auth, "Auth", Auth)
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    monkeypatch.delenv("EARTHDATA_USERNAME", raising=False)
    with pytest.raises(sources.SourceUnavailable, match="authentication_unavailable"):
        sources.NASAContextProvider()._login()
    assert calls == [{"strategy": "netrc", "persist": False}]
    assert "MUST_NOT_APPEAR" not in caplog.text
    assert not any(isinstance(item, sources._PrivateAuthLogs) for item in logging.getLogger("earthaccess.auth").filters)


class Response:
    def __init__(self, payload=b"data", declared=None):
        self.payload = payload
        self.headers = {"Content-Length": str(len(payload)) if declared is None else str(declared)}
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def raise_for_status(self): pass
    def iter_content(self, size): yield self.payload


def download_provider(monkeypatch, response):
    provider = sources.NASAContextProvider()
    calls = []
    def get(url, **kwargs): calls.append((url, kwargs)); return response
    provider.download_session = SimpleNamespace(get=get, close=lambda: None)
    monkeypatch.setattr(provider, "_login", lambda: None)
    return provider, calls


def test_download_uses_bounded_stream_and_atomic_file(monkeypatch, tmp_path):
    provider, calls = download_provider(monkeypatch, Response())
    auth_hook = lambda response, **kwargs: response
    provider.download_session.hooks = {"response": [auth_hook]}
    item = Granule()
    paths = provider.obtain([(item, NAME, sources.granule_identity(item, "gpm")[1])], tmp_path)
    assert paths == [tmp_path / NAME] and paths[0].read_bytes() == b"data"
    assert calls[0][1]["timeout"] == (10, 30) and calls[0][1]["stream"] is True
    assert calls[0][1]["hooks"]["response"] == [auth_hook, provider._redirect_guard]
    assert list(tmp_path.glob("*.part")) == []


@pytest.mark.parametrize("case", ["declared", "stream", "aggregate", "truncated"])
def test_oversize_or_incomplete_download_removes_temporary_files(monkeypatch, tmp_path, case):
    response = Response(payload=b"x" * 10, declared=20 if case == "truncated" else 10)
    provider, _ = download_provider(monkeypatch, response)
    if case == "declared": monkeypatch.setattr(sources, "MAX_FILE_BYTES", 5)
    elif case == "stream": response.headers = {}; monkeypatch.setattr(sources, "MAX_FILE_BYTES", 5)
    elif case == "aggregate": monkeypatch.setattr(sources, "MAX_DOWNLOAD_BYTES", 5)
    item = Granule()
    with pytest.raises(sources.SourceUnavailable): provider.obtain([(item, NAME, ())], tmp_path)
    assert not (tmp_path / NAME).exists() and not list(tmp_path.iterdir())


@pytest.mark.parametrize("url", ["http://data.nasa.gov/a", "https://127.0.0.1/a", "https://evil.example/a", "https://user:password@data.nasa.gov/a"])
def test_provider_links_cannot_point_to_other_devices_or_credentials(url):
    with pytest.raises(sources.SourceUnavailable): sources._allowed_url(url)


def test_total_provider_deadline_enforced(monkeypatch):
    provider = sources.NASAContextProvider()
    monkeypatch.setattr(sources.time, "monotonic", lambda: provider.deadline + 1)
    with pytest.raises(sources.SourceUnavailable, match="provider_timeout"): provider.check_deadline()


def test_download_link_must_match_catalog_identity(monkeypatch, tmp_path):
    provider, _ = download_provider(monkeypatch, Response())
    item = Granule(url="https://gpm1.gesdisc.eosdis.nasa.gov/data/unrelated.HDF5")
    with pytest.raises(sources.SourceUnavailable, match="invalid_result"):
        provider.obtain([(item, NAME, ())], tmp_path)
    assert not list(tmp_path.iterdir())


def test_optional_preparation_cap_rejects_before_provider_or_login(monkeypatch, tmp_path):
    from scripts.validate import prepare_context_hydro as cli
    from backend.shared.settings import WorkerSettings
    monkeypatch.setattr(cli, "NASAContextProvider", lambda: pytest.fail("Cap must reject before provider access"))
    with pytest.raises(ValueError, match="download count"):
        cli.prepare(requested(), WorkerSettings(gpm_dir=tmp_path, smap_dir=tmp_path), max_granules=1)
