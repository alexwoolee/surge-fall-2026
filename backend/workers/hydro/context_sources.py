"""Live NASA discovery with finite I/O budgets and exact cache identities.

The provider is used only inside the Hydro process. Credentials never become
task fields, results, URLs in reports, or interactive prompts.
"""

import os
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
from threading import Event, Lock
import time
from urllib.parse import unquote, urljoin, urlsplit

import requests

from backend.workers.hydro.context import gpm_interval, smap_interval

MAX_DISCOVERY_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 4 * 1024 * 1024 * 1024
MAX_PROVIDER_SECONDS = 300
MAX_DOWNLOAD_WORKERS = 4
# NASA's GES DISC and NSIDC HTTPS data services currently issue signed redirects
# to these distributions. CDN links are accepted only after provider discovery;
# they are not permitted as initial catalog links.
NASA_CDN_HOSTS = frozenset({"d2b3c3wh8s6en5.cloudfront.net", "d3h5e2j7riftk6.cloudfront.net"})


class _PrivateAuthLogs(logging.Filter):
    """earthaccess may log an EDL response body; expose only our safe reason."""
    def filter(self, record):
        return False


class SourceUnavailable(Exception):
    def __init__(self, reason="source_unavailable"):
        self.reason = reason
        super().__init__(reason)


def granule_identity(item, component):
    """Accept only this pinned product's concrete native filename convention."""
    parser = gpm_interval if component == "gpm" else smap_interval
    suffix = ".HDF5" if component == "gpm" else ".h5"
    prefix = "GPM_3IMERGHH.07:" if component == "gpm" else "SPL4SMGP.008:"
    candidates = [item.get("umm", {}).get("GranuleUR"), item.get("meta", {}).get("native-id")]
    for name in candidates:
        if isinstance(name, str):
            # CMR GES DISC identities include the exact collection/version
            # prefix; it is metadata, not part of the downloadable basename.
            if name.startswith(prefix):
                name = name[len(prefix):]
            for candidate in (name, name + suffix):
                interval = parser(candidate)
                if interval:
                    return candidate, interval
    raise SourceUnavailable("invalid_result")


def _allowed_url(url, *, redirect=False):
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        trusted = host.endswith(".nasa.gov") or host.endswith(".nsidc.org")
        cloud = redirect and (host.endswith(".amazonaws.com") or host in NASA_CDN_HOSTS)
        if (parsed.scheme != "https" or not (trusted or cloud) or parsed.username or parsed.password
                or parsed.port not in (None, 443) or any(char.isspace() for char in url)):
            raise ValueError
    except (TypeError, ValueError):
        raise SourceUnavailable("invalid_result") from None
    return url


class _CMRSession:
    def __init__(self, owner):
        self.owner = owner
        self.session = requests.Session()

    def get(self, url, **kwargs):
        self.owner.check_deadline()
        if urlsplit(url).hostname != "cmr.earthdata.nasa.gov":
            raise SourceUnavailable("invalid_result")
        with self.session.get(url, **kwargs, stream=True, timeout=(10, 30), allow_redirects=False) as response:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_content(65536):
                self.owner.check_deadline()
                body.extend(chunk)
                if len(body) > MAX_DISCOVERY_BYTES:
                    raise SourceUnavailable("resource_limit")
            # earthaccess's bounded pagination consumes json(), headers and status.
            response._content = bytes(body)
            response._content_consumed = True
            return response


class NASAContextProvider:
    """One task-scoped provider: live metadata first, then exact local reuse."""
    def __init__(self):
        self.deadline = time.monotonic() + MAX_PROVIDER_SECONDS
        self.downloaded_bytes = 0
        self.auth = None
        self.download_session = None
        self._bytes_lock = Lock()

    def check_deadline(self):
        if time.monotonic() >= self.deadline:
            raise SourceUnavailable("provider_timeout")

    def search(self, component, task):
        from earthaccess import DataGranules

        short_name, version, maximum = (("GPM_3IMERGHH", "07", 336) if component == "gpm" else ("SPL4SMGP", "008", 57))
        from datetime import timedelta
        self.check_deadline()
        query = DataGranules().parameters(short_name=short_name, version=version,
                                          bounding_box=task.bbox.as_tuple(),
                                          temporal=(task.start_time.isoformat(), (task.end_time - timedelta(microseconds=1)).isoformat()))
        query.session.close()
        bounded = _CMRSession(self)
        query.session = bounded
        try:
            found = query.get(maximum + 1)
        finally:
            bounded.session.close()
        if len(found) > maximum:
            raise SourceUnavailable("resource_limit")
        selected = {}
        for item in found:
            name, interval = granule_identity(item, component)
            # Providers may legitimately return intersecting edge granules;
            # never include one extending outside the requested interval.
            if not task.start_time <= interval[0] < interval[1] <= task.end_time:
                continue
            if interval[0] in selected:
                raise SourceUnavailable("invalid_result")
            selected[interval[0]] = (item, name, interval)
        result = [selected[key] for key in sorted(selected)]
        return result[-1:] if component == "smap" else result

    def _login(self):
        if self.download_session is not None:
            return
        self.check_deadline()
        from earthaccess.auth import Auth

        strategy = "environment" if os.environ.get("EARTHDATA_TOKEN") or os.environ.get("EARTHDATA_USERNAME") else "netrc"
        logger = logging.getLogger("earthaccess.auth")
        private_logs = _PrivateAuthLogs()
        logger.addFilter(private_logs)
        try:
            # The pinned Auth.login's token POST has timeout=10; get_session
            # performs no network I/O. Avoid earthaccess.login(), which would
            # initialize its broader, unnecessary download store as well.
            self.auth = Auth().login(strategy=strategy, persist=False)
            self.check_deadline()
            if not self.auth.authenticated:
                raise ValueError
            self.download_session = self.auth.get_session()
            self.download_session.max_redirects = 6
        except SourceUnavailable:
            raise
        except Exception:
            raise SourceUnavailable("authentication_unavailable") from None
        finally:
            logger.removeFilter(private_logs)

    def _redirect_guard(self, response, *args, **kwargs):
        self.check_deadline()
        _allowed_url(response.url, redirect=True)
        if response.is_redirect:
            _allowed_url(urljoin(response.url, response.headers.get("Location", "")), redirect=True)
        return response

    def obtain(self, selected, folder):
        """Acquire all selected observations with at most four download streams.

        Authentication is established before threads start. Each download batch
        owns a separate session, while byte/deadline limits cover the whole task.
        """
        folder = Path(folder).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        paths, missing = [], []
        for item, name, _ in selected:
            self.check_deadline()
            target = folder / name
            if target.is_symlink() or target.resolve().parent != folder:
                raise SourceUnavailable("invalid_result")
            if target.is_file():
                if not 0 < target.stat().st_size <= MAX_FILE_BYTES:
                    raise SourceUnavailable("download_limit")
            else:
                missing.append((item, name, target))
            paths.append(target)
        if len(set(paths)) != len(paths):
            raise SourceUnavailable("invalid_result")
        if not missing:
            return paths
        self._login()
        stop = Event()
        if len(missing) == 1:
            self._download_one(*missing[0], self.download_session, stop)
            return paths
        sessions, errors = [], []
        error_lock = Lock()
        workers = min(MAX_DOWNLOAD_WORKERS, len(missing))
        def batch(index):
            try:
                for entry in missing[index::workers]:
                    if stop.is_set():
                        return
                    self._download_one(*entry, sessions[index], stop)
            except Exception as error:
                with error_lock:
                    errors.append(error)
                    stop.set()
        try:
            for _ in range(workers):
                session = self.auth.get_session()
                session.max_redirects = 6
                sessions.append(session)
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="nasa-download") as executor:
                list(executor.map(batch, range(workers)))
            if errors:
                raise errors[0]
        finally:
            for session in sessions:
                session.close()
        return paths

    def _download_one(self, item, name, target, session, stop):
        self.check_deadline()
        links = item.data_links(access="external")
        if not links or len(links) > 16:
            raise SourceUnavailable("invalid_result")
        url = _allowed_url(links[0])
        if unquote(urlsplit(url).path).rsplit("/", 1)[-1] != name:
            raise SourceUnavailable("invalid_result")
        temporary = None
        try:
            with session.get(url, stream=True, allow_redirects=True,
                             timeout=(10, 30), hooks={"response": [
                                 *getattr(session, "hooks", {}).get("response", []), self._redirect_guard,
                             ]}) as response:
                response.raise_for_status()
                declared = response.headers.get("Content-Length")
                declared = int(declared) if declared is not None else None
                with self._bytes_lock:
                    if declared is not None and (declared < 1 or declared > MAX_FILE_BYTES or self.downloaded_bytes + declared > MAX_DOWNLOAD_BYTES):
                        raise SourceUnavailable("download_limit")
                size = 0
                with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".context-", suffix=".part", delete=False) as output:
                    temporary = Path(output.name)
                    for chunk in response.iter_content(1024 * 1024):
                        self.check_deadline()
                        if stop.is_set():
                            raise SourceUnavailable("source_unavailable")
                        size += len(chunk)
                        with self._bytes_lock:
                            self.downloaded_bytes += len(chunk)
                            if size > MAX_FILE_BYTES or self.downloaded_bytes > MAX_DOWNLOAD_BYTES:
                                raise SourceUnavailable("download_limit")
                        output.write(chunk)
                if size < 1 or declared is not None and size != declared:
                    raise SourceUnavailable("source_unavailable")
            if stop.is_set():
                raise SourceUnavailable("source_unavailable")
            if target.exists():
                raise SourceUnavailable("invalid_result")
            temporary.replace(target)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def close(self):
        if self.download_session is not None:
            self.download_session.close()


def live_paths(provider, component, task, folder):
    """Translate provider failures to public, allowlisted reasons."""
    try:
        selected = provider.search(component, task)
        if not selected:
            return [], "no_matching_observations"
        paths = provider.obtain(selected, folder)
        if len(paths) != len(selected):
            raise SourceUnavailable("invalid_result")
        return paths, None
    except SourceUnavailable as error:
        return [], error.reason
    except requests.Timeout:
        return [], "provider_timeout"
    except Exception:
        return [], "source_unavailable"
