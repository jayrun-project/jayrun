from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..messages.origin import CommandOrigin
from .context_state import ContextRequest, ContextState
from ..history_budget import _HistoryBudget


@dataclass(frozen=True, slots=True)
class StateTransition:
    actor: CommandOrigin
    previous_state: ContextState
    next_state: ContextState
    recorded_at: datetime
    revision: int


@dataclass(frozen=True, slots=True)
class StopRequested:
    actor: CommandOrigin
    recorded_at: datetime
    revision: int


@dataclass(frozen=True, slots=True)
class IterationStarted:
    actor: CommandOrigin
    iteration: int
    recorded_at: datetime
    revision: int


@dataclass(frozen=True, slots=True)
class ControlRequested:
    actor: CommandOrigin
    request: ContextRequest
    duration_seconds: float | None
    recorded_at: datetime
    revision: int


@dataclass(frozen=True, slots=True)
class EngineChanged:
    actor: CommandOrigin
    previous_engine_id: str
    current_engine_id: str
    generation: int
    checkpoint_iteration: int
    recorded_at: datetime
    revision: int


ContextHistoryEntry = (
    StateTransition
    | StopRequested
    | IterationStarted
    | ControlRequested
    | EngineChanged
)


@dataclass(slots=True)
class ContextStatus:
    state: ContextState = ContextState.SUBMITTED
    revision: int = 0
    iteration_count: int = 0
    transitioned_by: CommandOrigin | None = None
    stop_requested: bool = False
    stop_requested_by: CommandOrigin | None = None
    stop_requested_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    validated_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    history: list[ContextHistoryEntry] = field(default_factory=list)
    _budget: _HistoryBudget | None = field(default=None, repr=False)

    @property
    def has_been_validated(self) -> bool:
        return self.validated_at is not None

    def apply_transition(
        self,
        next_state: ContextState,
        actor: CommandOrigin,
    ) -> None:
        now = datetime.now(timezone.utc)
        self.revision += 1
        if self._budget is not None:
            self._budget.account()
        self.history.append(
            StateTransition(
                actor=actor,
                previous_state=self.state,
                next_state=next_state,
                recorded_at=now,
                revision=self.revision,
            )
        )
        self.state = next_state
        self.transitioned_by = actor
        self.updated_at = now

        if next_state is ContextState.VALIDATED:
            self.validated_at = now

        if next_state is ContextState.RUNNING and self.started_at is None:
            self.started_at = now

        if next_state.is_terminal:
            self.finished_at = now

    def request_stop(self, actor: CommandOrigin) -> StopRequested | None:
        if self.stop_requested:
            return

        now = datetime.now(timezone.utc)
        self.revision += 1
        if self._budget is not None:
            self._budget.account()
        self.stop_requested = True
        self.stop_requested_by = actor
        self.stop_requested_at = now
        self.updated_at = now
        entry = StopRequested(
            actor=actor,
            recorded_at=now,
            revision=self.revision,
        )
        self.history.append(entry)
        return entry

    def start_iteration(self, actor: CommandOrigin) -> None:
        if self.stop_requested:
            raise RuntimeError("cannot start an iteration after stop acceptance")
        now = datetime.now(timezone.utc)
        self.revision += 1
        if self._budget is not None:
            self._budget.account()
        self.iteration_count += 1
        self.updated_at = now
        self.history.append(
            IterationStarted(
                actor=actor,
                iteration=self.iteration_count,
                recorded_at=now,
                revision=self.revision,
            )
        )

    def request_control(
        self,
        request: ContextRequest,
        duration_seconds: float | None,
        actor: CommandOrigin,
    ) -> None:
        now = datetime.now(timezone.utc)
        self.revision += 1
        if self._budget is not None:
            self._budget.account()
        self.updated_at = now
        self.history.append(
            ControlRequested(
                actor=actor,
                request=request,
                duration_seconds=duration_seconds,
                recorded_at=now,
                revision=self.revision,
            )
        )

    def change_engine(
        self,
        previous_engine_id: str,
        current_engine_id: str,
        generation: int,
        checkpoint_iteration: int,
        actor: CommandOrigin,
    ) -> None:
        now = datetime.now(timezone.utc)
        self.revision += 1
        if self._budget is not None:
            self._budget.account()
        self.updated_at = now
        self.history.append(
            EngineChanged(
                actor=actor,
                previous_engine_id=previous_engine_id,
                current_engine_id=current_engine_id,
                generation=generation,
                checkpoint_iteration=checkpoint_iteration,
                recorded_at=now,
                revision=self.revision,
            )
        )
