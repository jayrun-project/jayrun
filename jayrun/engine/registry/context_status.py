from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
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


@dataclass(frozen=True, slots=True)
class LifecycleCheckpoint:
    """Lifecycle facts immediately before the first retained history entry."""

    count: int = 0
    revision: int = 0
    state: ContextState = ContextState.SUBMITTED
    iteration: int = 0
    generation: int = 0
    engine_id: str | None = None
    stop: StopRequested | None = None
    validated: bool = False
    started: bool = False
    awaiting_queue: bool = False
    control_revision: int = 0

    def _validate(self, snapshot_revision: int) -> None:
        counters = (self.count, self.revision, self.iteration, self.generation, self.control_revision)
        if (any(type(value) is not int for value in counters)
                or not 1 <= self.count <= self.revision < snapshot_revision
                or not 0 <= self.iteration <= self.count or not 0 <= self.generation <= self.count
                or not 0 <= self.control_revision <= self.revision):
            raise ValueError("invalid lifecycle checkpoint counters")
        if (not isinstance(self.state, ContextState) or self.state.is_terminal
                or any(type(v) is not bool for v in (self.started, self.validated, self.awaiting_queue))
                or (self.started and not self.validated) or (self.iteration and not self.started)):
            raise ValueError("invalid lifecycle checkpoint state")
        if ((self.generation == 0) != (self.engine_id is None)
                or (self.engine_id is not None and (type(self.engine_id) is not str or not self.engine_id.strip()))
                or (self.awaiting_queue and not self.generation)):
            raise ValueError("invalid lifecycle checkpoint owner")
        if self.stop is not None and (
            not isinstance(self.stop, StopRequested) or not isinstance(self.stop.actor, CommandOrigin)
            or not isinstance(self.stop.recorded_at, datetime) or type(self.stop.revision) is not int
            or not 0 < self.stop.revision <= self.control_revision
        ):
            raise ValueError("invalid lifecycle checkpoint stop acceptance")

    def _advance(self, entry: ContextHistoryEntry) -> LifecycleCheckpoint:
        changes = {}
        if isinstance(entry, StateTransition):
            changes.update(state=entry.next_state, awaiting_queue=False,
                           validated=self.validated or entry.next_state is ContextState.VALIDATED,
                           started=self.started or entry.next_state is ContextState.RUNNING)
        elif isinstance(entry, IterationStarted):
            changes["iteration"] = entry.iteration
        elif isinstance(entry, StopRequested):
            changes["stop"] = entry
        elif isinstance(entry, EngineChanged):
            changes.update(engine_id=entry.current_engine_id, generation=entry.generation,
                           iteration=entry.checkpoint_iteration,
                           awaiting_queue=self.state is not ContextState.QUEUED)
        if isinstance(entry, (StateTransition, StopRequested, ControlRequested)):
            changes["control_revision"] = entry.revision
        return replace(self, count=self.count + 1, revision=entry.revision, **changes)


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
    history: deque[ContextHistoryEntry] = field(default_factory=deque)
    history_prefix: LifecycleCheckpoint | None = None
    _budget: _HistoryBudget | None = field(default=None, repr=False)

    def _append(self, entry: ContextHistoryEntry) -> None:
        if len(self.history) == self.history.maxlen:
            prefix = self.history_prefix or LifecycleCheckpoint()
            self.history_prefix = prefix._advance(self.history[0])
        self.history.append(entry)

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
        self._append(
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
        self._append(entry)
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
        self._append(
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
        self._append(
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
        self._append(
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
