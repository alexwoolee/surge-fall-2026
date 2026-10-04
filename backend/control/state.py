"""Control observations kept separate from worker execution timestamps.

These are collection records, not environmental fusion or proof of physical
distribution. A timeout records the end of Control's wait; it never changes a
worker's state or cancels remote processing.
"""

from typing import Literal, Self

from pydantic import Field, model_validator

from backend.shared.contracts import (
    AnalysisType, CombinedAnalysis, Contract, FloodResult, HydroResult,
    Nonempty, TaskID, TaskStatus, Timestamp, WorkerID, WorkerStatus,
)


DispatchOutcome = Literal[
    "complete", "partial", "worker_failed", "transport_error", "protocol_error", "rejected", "timed_out",
]


class DispatchError(Contract):
    code: Literal["worker_failed", "transport_error", "protocol_error", "rejected", "timed_out"]
    message: Nonempty


class StatusObservation(Contract):
    observed_at: Timestamp
    status: TaskStatus


class DispatchRecord(Contract):
    task_id: TaskID
    worker_id: WorkerID
    analysis_type: AnalysisType
    outcome: DispatchOutcome
    control_started_at: Timestamp
    control_completed_at: Timestamp
    submitted_at: Timestamp | None = None
    accepted: bool = False
    acceptance_unknown: bool = False
    worker_status: WorkerStatus | None = None
    task_status: TaskStatus | None = None
    observations: list[StatusObservation] = Field(default_factory=list, max_length=16)
    result: HydroResult | FloodResult | None = None
    error: DispatchError | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.control_completed_at < self.control_started_at:
            raise ValueError("Control observation times must be ordered.")
        expected = "hydrometeorology" if self.worker_id == "hydro-worker" else "surface_water_and_terrain"
        if self.analysis_type != expected:
            raise ValueError("Dispatch identity and analysis type must agree.")
        if self.submitted_at is not None and not self.control_started_at <= self.submitted_at <= self.control_completed_at:
            raise ValueError("Submission time must lie inside the Control observation interval.")
        if self.accepted and self.acceptance_unknown:
            raise ValueError("Acknowledged acceptance cannot also be unknown.")
        if (self.accepted or self.acceptance_unknown) and self.submitted_at is None:
            raise ValueError("Acceptance metadata requires an attempted submission.")
        if self.accepted and self.task_status is None:
            raise ValueError("Acknowledged acceptance requires a validated task status.")
        if self.worker_status is not None and (
            self.worker_status.worker_id != self.worker_id or self.worker_status.analysis_type != self.analysis_type
        ):
            raise ValueError("Worker preflight status must match the dispatch identity.")
        if self.result is not None and (
            not self.accepted or self.result.task_id != self.task_id
            or self.result.worker_id != self.worker_id or self.result.analysis_type != self.analysis_type
        ):
            raise ValueError("Retained result must match an acknowledged worker task.")
        if self.outcome in {"complete", "partial"}:
            if self.result is None or self.result.status != self.outcome or self.error is not None:
                raise ValueError("Successful outcomes require the matching validated result.")
        elif self.error is None or self.error.code != self.outcome:
            raise ValueError("Unsuccessful outcomes require an explicit matching error.")
        if self.task_status is not None and (
            self.task_status.task_id != self.task_id or self.task_status.worker_id != self.worker_id
            or self.task_status.analysis_type != self.analysis_type
        ):
            raise ValueError("Retained task status must match the dispatch identity.")
        if self.result is not None and (self.task_status is None or self.result.status != self.task_status.state.value):
            raise ValueError("Retained result and terminal task status must agree.")
        if self.outcome == "worker_failed" and (self.task_status is None or self.task_status.state.value != "failed"):
            raise ValueError("Worker failure requires a reported failed task state.")
        if bool(self.observations) != (self.task_status is not None) or (
            self.observations and self.observations[-1].status != self.task_status
        ):
            raise ValueError("The latest observation must describe the retained task status.")
        previous_time = self.control_started_at
        for observation in self.observations:
            if not previous_time <= observation.observed_at <= self.control_completed_at:
                raise ValueError("Control observations must be ordered within the dispatch interval.")
            if (observation.status.task_id != self.task_id or observation.status.worker_id != self.worker_id
                    or observation.status.analysis_type != self.analysis_type):
                raise ValueError("Observed status must match the dispatch identity.")
            previous_time = observation.observed_at
        return self


class DispatchRun(Contract):
    task_id: TaskID
    execution_mode: Literal["sequential"] = "sequential"
    control_started_at: Timestamp
    control_completed_at: Timestamp
    hydro: DispatchRecord
    flood: DispatchRecord
    combined: CombinedAnalysis

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if any(record.task_id != self.task_id for record in (self.hydro, self.flood, self.combined)):
            raise ValueError("Both branches and the collection must share the investigation ID.")
        if self.hydro.worker_id != "hydro-worker" or self.flood.worker_id != "flood-worker":
            raise ValueError("Both specialist worker branches must be retained.")
        if self.control_completed_at < self.control_started_at:
            raise ValueError("Control observation times must be ordered.")
        if not (self.control_started_at <= self.hydro.control_started_at <= self.hydro.control_completed_at
                <= self.flood.control_started_at <= self.flood.control_completed_at <= self.control_completed_at):
            raise ValueError("Sequential branch intervals must be ordered inside the Control run.")
        if self.combined.hydro != self.hydro.result or self.combined.flood != self.flood.result:
            raise ValueError("The collection must preserve exactly the validated branch results.")
        return self
