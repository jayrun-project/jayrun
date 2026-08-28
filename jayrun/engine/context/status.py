from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..artifact.result import ArtifactResult
from ..recorders.execution.records import ExecutionReport
from ..registry.identities import BaseIdentity
from .state import State


@dataclass(slots=True)
class ContextStatus:
    state: State = State.PENDING
    max_iterations: int | None = None
    iteration_count: int = 1
    identity: BaseIdentity | None = None
    failure: Exception | None = None
    resumed_at: datetime | None = None
    stop_requested: bool = False
    validated: bool = False
    report: ExecutionReport | None = None
    artifacts: ArtifactResult | None = None

    def validate(self) -> None:
        self.validated = True

    def run(self) -> None:
        self.state = State.RUNNING

    def pause(self, identity: BaseIdentity, resume_at: float | None) -> None:
        self.state = State.PAUSED
        self.identity = identity

    def resume(self, identity: BaseIdentity | None = None) -> None:
        if self.state is not State.PAUSED:
            return
        self.identity = identity
        self.state = State.RUNNING
        self.resumed_at = datetime.now()

    def abort(self, identity: BaseIdentity) -> None:
        self.state = State.ABORTED
        self.identity = identity
        self.failure = None

    def stop(self, identity: BaseIdentity):
        self.identity = identity
        self.stop_requested = True

    def fail(
        self,
        failure: Exception,
        identity: BaseIdentity,
    ) -> None:
        self.state = State.FAILED
        self.identity = identity
        self.failure = failure

    def finish(self, identity: BaseIdentity) -> None:
        self.state = State.FINISHED
        self.identity = identity
        self.failure = None

    def reiterate(self) -> None:
        self.state = State.RUNNING
        self.iteration_count += 1
        self.failure = None
        self.identity = None

    def finalize(self, report: ExecutionReport, artifacts: ArtifactResult) -> None:
        self.report = report
        self.artifacts = artifacts

    @property
    def can_dispatch(self):
        if self.state is State.RUNNING:
            return True
        return False

    @property
    def should_reiterate(self) -> bool:
        if self.stop_requested:
            return False
        if self.max_iterations is None:
            return True
        return self.iteration_count < self.max_iterations

    @property
    def is_running(self) -> bool:
        return self.state is State.RUNNING

    @property
    def is_paused(self) -> bool:
        return self.state is State.PAUSED

    @property
    def is_failed(self) -> bool:
        return self.state is State.FAILED

    @property
    def is_finished(self) -> bool:
        return self.state is State.FINISHED

    @property
    def is_terminated(self) -> bool:
        return self.state in (State.FINISHED, State.ABORTED, State.FAILED)
