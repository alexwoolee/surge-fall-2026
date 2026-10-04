"""Local worker settings; paths and credentials never come from HTTP tasks."""

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
        if self.worker_token is not None and (
            not isinstance(self.worker_token, str) or not self.worker_token
            or self.worker_token != self.worker_token.strip() or len(self.worker_token) > 512
        ):
            raise ValueError('MESHMIND_WORKER_TOKEN must be a nonempty token without surrounding whitespace.')

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
