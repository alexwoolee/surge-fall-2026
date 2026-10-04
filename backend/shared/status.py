"""Worker lifecycle states shared by the API and its callers."""

from enum import StrEnum


class TaskState(StrEnum):
    TASK_RECEIVED = "task_received"
    DATASET_LOCATED = "dataset_located"
    PROCESSING = "processing"
    PREPARING_RESULT = "preparing_result"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


TERMINAL_STATES = frozenset({TaskState.COMPLETE, TaskState.PARTIAL, TaskState.FAILED})
