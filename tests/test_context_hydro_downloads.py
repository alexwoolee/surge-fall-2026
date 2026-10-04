"""Bounded parallel acquisition keeps every observation and owns its sessions."""

from datetime import datetime, timedelta
from threading import Barrier, Lock, get_ident
from types import SimpleNamespace

import pytest
import requests

from backend.workers.hydro import context_sources as sources
from test_context_sources import Granule


def selection(count):
    result = []
    start = datetime(2019, 8, 1)
    for index in range(count):
        begin = start + timedelta(minutes=30 * index)
        finish = begin + timedelta(minutes=30, seconds=-1)
        name = f"3B-HHR.MS.MRG.3IMERG.{begin:%Y%m%d}-S{begin:%H%M%S}-E{finish:%H%M%S}.{index * 30:04d}.V07B.HDF5"
        item = Granule(name)
        result.append((item, name, sources.granule_identity(item, "gpm")[1]))
    return result


def concurrent_provider(monkeypatch, *, streams=4, failure=None):
    provider = sources.NASAContextProvider()
    barrier, lock = Barrier(streams), Lock()
    calls, sessions, login = [], [], []
    counters = {"active": 0, "peak": 0}
    class Response:
        headers = {}  # Exercise streamed rather than only declared byte limits.
        def __enter__(self):
            with lock:
                counters["active"] += 1
                counters["peak"] = max(counters["peak"], counters["active"])
            return self
        def __exit__(self, *args):
            with lock:
                counters["active"] -= 1
        def raise_for_status(self):
            pass
        def iter_content(self, size):
            assert size == 1024 * 1024
            barrier.wait(timeout=5)
            if failure:
                raise failure("do not disclose private provider details")
            yield b"data"
    class Session:
        hooks = {}
        def __init__(self):
            self.thread = None
            self.closed = False
            sessions.append(self)
        def get(self, url, **kwargs):
            if self.thread is None:
                self.thread = get_ident()
            assert self.thread == get_ident(), "Sessions must never be shared across download threads"
            assert kwargs["timeout"] == (10, 30) and kwargs["stream"] is True
            assert kwargs["hooks"]["response"] == [provider._redirect_guard]
            with lock:
                calls.append(url.rsplit("/", 1)[-1])
            return Response()
        def close(self):
            self.closed = True
    def authenticate_once():
        login.append(get_ident())
        provider.auth = SimpleNamespace(get_session=Session)
        provider.download_session = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(provider, "_login", authenticate_once)
    return provider, calls, sessions, login, counters


def test_four_independent_sessions_download_every_granule_and_preserve_order(tmp_path, monkeypatch):
    selected = selection(8)
    provider, calls, sessions, login, counters = concurrent_provider(monkeypatch)
    paths = provider.obtain(selected, tmp_path)
    assert [path.name for path in paths] == [row[1] for row in selected]
    assert sorted(calls) == sorted(row[1] for row in selected)
    assert all(path.read_bytes() == b"data" for path in paths)
    assert login == [get_ident()]
    assert len(sessions) == 4 and all(session.closed for session in sessions)
    assert len({session.thread for session in sessions}) == 4
    assert counters == {"active": 0, "peak": 4}
    assert provider.downloaded_bytes == 32
    assert not list(tmp_path.glob("*.part"))


def test_cached_inputs_do_not_consume_download_streams_or_change_order(tmp_path, monkeypatch):
    selected = selection(6)
    (tmp_path / selected[0][1]).write_bytes(b"cached")
    (tmp_path / selected[3][1]).write_bytes(b"cached")
    provider, calls, sessions, login, counters = concurrent_provider(monkeypatch)
    paths = provider.obtain(selected, tmp_path)
    assert [path.name for path in paths] == [row[1] for row in selected]
    assert sorted(calls) == sorted(row[1] for index, row in enumerate(selected) if index not in (0, 3))
    assert paths[0].read_bytes() == paths[3].read_bytes() == b"cached"
    assert provider.downloaded_bytes == 16
    assert len(sessions) == 4 and all(session.closed for session in sessions)


def test_parallel_streams_share_one_aggregate_byte_budget_and_clean_partial_files(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "MAX_DOWNLOAD_BYTES", 10)
    provider, calls, sessions, login, counters = concurrent_provider(monkeypatch)
    with pytest.raises(sources.SourceUnavailable, match="download_limit"):
        provider.obtain(selection(4), tmp_path)
    assert all(session.closed for session in sessions)
    assert counters["active"] == 0
    assert not list(tmp_path.glob("*.part"))
    assert sum(path.stat().st_size for path in tmp_path.iterdir()) <= 10


def test_provider_timeouts_stop_batches_without_publishing_partial_files(tmp_path, monkeypatch):
    provider, calls, sessions, login, counters = concurrent_provider(monkeypatch, failure=requests.Timeout)
    monkeypatch.setattr(provider, "search", lambda *args: selection(8))
    paths, reason = sources.live_paths(provider, "gpm", None, tmp_path)
    assert paths == [] and reason == "provider_timeout"
    assert len(calls) == 4
    assert len(sessions) == 4 and all(session.closed for session in sessions)
    assert list(tmp_path.iterdir()) == []


def test_duplicate_targets_are_rejected_before_login_or_threads(tmp_path, monkeypatch):
    provider = sources.NASAContextProvider()
    monkeypatch.setattr(provider, "_login", lambda: pytest.fail("Duplicate target must fail before credentials"))
    with pytest.raises(sources.SourceUnavailable, match="invalid_result"):
        provider.obtain(selection(1) * 2, tmp_path)


def test_task_deadline_is_checked_before_any_cached_or_remote_acquisition(tmp_path, monkeypatch):
    provider = sources.NASAContextProvider()
    monkeypatch.setattr(sources.time, "monotonic", lambda: provider.deadline + 1)
    monkeypatch.setattr(provider, "_login", lambda: pytest.fail("Expired task must not authenticate"))
    with pytest.raises(sources.SourceUnavailable, match="provider_timeout"):
        provider.obtain(selection(4), tmp_path)
