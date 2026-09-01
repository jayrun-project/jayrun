from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .context_state import ContextState
from .identities import BaseIdentity


@dataclass(frozen=True, slots=True)
class StateTransition:
    actor: BaseIdentity
    previous_state: ContextState
    next_state: ContextState
    recorded_at: datetime
    revision: int


@dataclass(frozen=True, slots=True)
class StopRequested:
    actor: BaseIdentity
    recorded_at: datetime
    revision: int


@dataclass(frozen=True, slots=True)
class IterationStarted:
    actor: BaseIdentity
    iteration: int
    recorded_at: datetime
    revision: int


ContextHistoryEntry = StateTransition | StopRequested | IterationStarted


@dataclass(slots=True)
class ContextStatus:
    state: ContextState = ContextState.SUBMITTED
    revision: int = 0
    iteration_count: int = 0
    transitioned_by: BaseIdentity | None = None
    stop_requested: bool = False
    stop_requested_by: BaseIdentity | None = None
    stop_requested_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    validated_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    history: list[ContextHistoryEntry] = field(default_factory=list)

    @property
    def has_been_validated(self) -> bool:
        return self.validated_at is not None

    def apply_transition(
        self,
        next_state: ContextState,
        actor: BaseIdentity,
    ) -> None:
        now = datetime.now(timezone.utc)
        self.revision += 1
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

    def request_stop(self, actor: BaseIdentity) -> None:
        if self.stop_requested:
            return

        now = datetime.now(timezone.utc)
        self.revision += 1
        self.stop_requested = True
        self.stop_requested_by = actor
        self.stop_requested_at = now
        self.updated_at = now
        self.history.append(
            StopRequested(
                actor=actor,
                recorded_at=now,
                revision=self.revision,
            )
        )

    def start_iteration(self, actor: BaseIdentity) -> None:
        now = datetime.now(timezone.utc)
        self.revision += 1
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
