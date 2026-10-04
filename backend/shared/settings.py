"""Explicit worker and Control settings; credentials never come from HTTP tasks."""

from dataclasses import dataclass, field
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class WorkerSettings:
    gpm_dir: Path = ROOT / 'data/cache/gpm'
    smap_dir: Path = ROOT / 'data/cache/smap'
    worker_token: str | None = field(default=None, repr=False)
    max_tasks: int = 128

    def __post_init__(self):
        object.__setattr__(self, 'gpm_dir', Path(self.gpm_dir).expanduser().resolve())
        object.__setattr__(self, 'smap_dir', Path(self.smap_dir).expanduser().resolve())
        if isinstance(self.max_tasks, bool) or not isinstance(self.max_tasks, int) or not 1 <= self.max_tasks <= 1024:
            raise ValueError('MESHMIND_MAX_TASKS must be an integer from 1 to 1024.')
        validate_token(self.worker_token)

    @classmethod
    def from_env(cls):
        try:
            capacity = int(os.environ.get('MESHMIND_MAX_TASKS', '128'))
        except ValueError:
            raise ValueError('MESHMIND_MAX_TASKS must be an integer from 1 to 1024.') from None
        return cls(
            gpm_dir=Path(os.environ.get('MESHMIND_GPM_DIR') or ROOT / 'data/cache/gpm'),
            smap_dir=Path(os.environ.get('MESHMIND_SMAP_DIR') or ROOT / 'data/cache/smap'),
            worker_token=os.environ.get('MESHMIND_WORKER_TOKEN') or None,
            max_tasks=capacity,
        )


def validate_token(token: str | None) -> None:
    """Check a Bearer header value without including credentials in errors."""
    if token is not None and (
        not isinstance(token, str) or not 1 <= len(token) <= 512
        or any(not 33 <= ord(character) <= 126 for character in token)
    ):
        raise ValueError('Worker tokens must contain 1 to 512 printable ASCII characters without whitespace.')


@dataclass(frozen=True)
class WorkerEndpoint:
    """An explicitly configured HTTP origin and the worker expected there."""

    url: str
    expected_worker_id: str
    token: str | None = field(default=None, repr=False)

    def __post_init__(self):
        from urllib.parse import urlsplit, urlunsplit

        if not isinstance(self.expected_worker_id, str) or self.expected_worker_id not in {'hydro-worker', 'flood-worker'}:
            raise ValueError('A supported expected_worker_id is required.')
        try:
            if (not isinstance(self.url, str) or not self.url
                    or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in self.url)
                    or '\\' in self.url or len(self.url) > 2048):
                raise ValueError
            parsed = urlsplit(self.url)
            if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or parsed.path not in {'', '/'} or parsed.query or parsed.fragment
                    or '?' in self.url or '#' in self.url or '%' in parsed.netloc or parsed.netloc.endswith(':')
                    or (parsed.port is not None and not 1 <= parsed.port <= 65535)):
                raise ValueError
            # HTTPX receives an origin, never a credential-bearing URL or a path.
            origin = urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), '', '', ''))
        except (TypeError, ValueError):
            raise ValueError('Worker URL must be an http(s) origin without credentials, query, fragment or extra path.') from None
        validate_token(self.token)
        object.__setattr__(self, 'url', origin)


def _bounded_number(value, *, name: str, minimum: float, maximum: float) -> float:
    import math

    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not minimum <= value <= maximum or not math.isfinite(value)):
        raise ValueError(f'{name} must be a finite number from {minimum} to {maximum}.')
    return float(value)


@dataclass(frozen=True)
class ControlSettings:
    """Explicit destinations and finite limits for one Control dispatch run."""

    hydro: WorkerEndpoint
    flood: WorkerEndpoint
    request_timeout: float = 15.0
    task_timeout: float = 600.0
    poll_interval: float = 0.5
    max_response_bytes: int = 8 * 1024 * 1024

    def __post_init__(self):
        if (not isinstance(self.hydro, WorkerEndpoint) or self.hydro.expected_worker_id != 'hydro-worker'
                or not isinstance(self.flood, WorkerEndpoint) or self.flood.expected_worker_id != 'flood-worker'):
            raise ValueError('Control requires explicit Hydro and Flood endpoints with matching worker roles.')
        for name, minimum, maximum in (
            ('request_timeout', 0.1, 120), ('task_timeout', 0.1, 3600), ('poll_interval', 0.01, 30),
        ):
            object.__setattr__(self, name, _bounded_number(getattr(self, name), name=name, minimum=minimum, maximum=maximum))
        if (isinstance(self.max_response_bytes, bool) or not isinstance(self.max_response_bytes, int)
                or not 1024 <= self.max_response_bytes <= 32 * 1024 * 1024):
            raise ValueError('max_response_bytes must be an integer from 1024 to 33554432.')

    @classmethod
    def from_env(cls):
        def number(variable, default):
            try:
                return float(os.environ.get(variable, str(default)))
            except (ValueError, OverflowError):
                raise ValueError(f'{variable} must contain a finite number within its documented bounds.') from None

        return cls(
            hydro=WorkerEndpoint(os.environ.get('HYDRO_WORKER_URL', ''), 'hydro-worker',
                                 os.environ.get('HYDRO_WORKER_TOKEN') or None),
            flood=WorkerEndpoint(os.environ.get('FLOOD_WORKER_URL', ''), 'flood-worker',
                                 os.environ.get('FLOOD_WORKER_TOKEN') or None),
            request_timeout=number('MESHMIND_REQUEST_TIMEOUT_SECONDS', 15),
            task_timeout=number('MESHMIND_TASK_TIMEOUT_SECONDS', 600),
            poll_interval=number('MESHMIND_POLL_INTERVAL_SECONDS', 0.5),
        )
