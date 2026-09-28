from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import count
from traceback import format_tb
from typing import ClassVar, TYPE_CHECKING

if TYPE_CHECKING:
    from ..progress_history import _TimingScope
    from .._history import _ContextCapture

from ...core.artifact.base import Artifact
from ...core.artifact.context import ArtifactContext
from ...core.config.context import ConfigContext
from ...core.context.runtime_data import Data
from ...core.graph.definition.artifact import ArtifactDefinition
from ..artifact.result import ArtifactResult
from ..context.step_reference import StepReference
from ..interfaces.context_record import ContextRecord
from ..interfaces.services.storage import ContextRecordRepository
from ..messages.origin import CommandOrigin
from ..progress import (
    ProgressSnapshot,
    _ProgressProfile,
    _ProgressTracker,
    _ProgressUpdate,
)
from ..recorders.context.report import ContextReport
from ..recorders.execution.records import ExecutionReport, FailureRecord
from ..settings.combined_context import CombinedContextSettings
from ..settings.context import ArtifactPolicy, ContextSettings
from ..snapshot import ContextSnapshot
from ..history_budget import _HistoryBudget
from ..submission import _NormalizedSubmission, _SupervisionScope
from .context_state import ContextRequest, ContextState
from .context_status import ContextStatus, ControlRequested, StateTransition, StopRequested


@dataclass(slots=True)
class _SyncStateWaiter:
    state: ContextState | None
    event: threading.Event = field(default_factory=threading.Event)


@dataclass(slots=True)
class _AsyncStateWaiter:
    state: ContextState | None
    loop: asyncio.AbstractEventLoop
    future: asyncio.Future[None]


def _detach_failure_tracebacks(failures: tuple[BaseException, ...]) -> None:
    """Keep printable diagnostics without retaining execution frames.

    Finalization owns this operation for the context failure and recorded
    attempts. Native frames can reach active worker callers through f_back;
    clearing only completed locals cannot sever that ownership reliably.
    Exception identity, chains, groups and application-owned fields survive.
    Live artifact/resource references and placement leases are never modified.
    """
    pending = list(failures)
    seen: set[int] = set()
    while pending:
        failure = pending.pop()
        if id(failure) in seen:
            continue
        seen.add(id(failure))
        trace = failure.__traceback__
        if trace is not None:
            diagnostic = (
                "Jayrun execution traceback (most recent call last):\n"
                + "".join(format_tb(trace))
            )
            BaseException.add_note(failure, diagnostic.rstrip())
            failure.__traceback__ = None
        if failure.__cause__ is not None:
            pending.append(failure.__cause__)
        if failure.__context__ is not None:
            pending.append(failure.__context__)
        if isinstance(failure, BaseExceptionGroup):
            pending.extend(failure.exceptions)


class ContextInstance:
    _allowed_transitions: ClassVar[dict[ContextState, frozenset[ContextState]]] = {
        ContextState.SUBMITTED: frozenset(
            {ContextState.VALIDATING, ContextState.ABORTED}
        ),
        ContextState.VALIDATING: frozenset(
            {
                ContextState.VALIDATED,
                ContextState.REJECTED,
                ContextState.ABORTED,
            }
        ),
        ContextState.VALIDATED: frozenset(
            {
                ContextState.ROUTING,
                ContextState.QUEUED,
                ContextState.RUNNING,
                ContextState.STOPPED,
                ContextState.FINISHED,
                ContextState.ABORTED,
            }
        ),
        ContextState.ROUTING: frozenset(
            {
                ContextState.QUEUED,
                ContextState.STOPPED,
                ContextState.FINISHED,
                ContextState.ABORTED,
            }
        ),
        ContextState.QUEUED: frozenset(
            {
                ContextState.RUNNING,
                ContextState.STOPPED,
                ContextState.FINISHED,
                ContextState.ABORTED,
            }
        ),
        ContextState.RUNNING: frozenset(
            {
                ContextState.PLACEMENT_WAITING,
                ContextState.PAUSED,
                ContextState.ABORTING,
                ContextState.FAILING,
                ContextState.FINISHED,
                ContextState.STOPPED,
            }
        ),
        ContextState.PLACEMENT_WAITING: frozenset(
            {
                ContextState.RUNNING,
                ContextState.PAUSED,
                ContextState.ABORTING,
                ContextState.FAILING,
                ContextState.STOPPED,
                ContextState.FINISHED,
            }
        ),
        ContextState.PAUSED: frozenset(
            {
                ContextState.RUNNING,
                ContextState.PLACEMENT_WAITING,
                ContextState.ABORTING,
                ContextState.FAILING,
            }
        ),
        ContextState.ABORTING: frozenset({ContextState.ABORTED}),
        ContextState.FAILING: frozenset({ContextState.FAILED}),
        ContextState.REJECTED: frozenset(),
        ContextState.FINISHED: frozenset(),
        ContextState.STOPPED: frozenset(),
        ContextState.FAILED: frozenset(),
        ContextState.ABORTED: frozenset(),
    }

    def __init__(
        self,
        context_id: int,
        submission: _NormalizedSubmission,
        supervises: _SupervisionScope,
        settings: CombinedContextSettings,
        progress_profile: _ProgressProfile,
        lifecycle_reporter: Callable[[ContextInstance, StateTransition | StopRequested], None],
        engine_id: str,
        local_engine_id: str,
        controller: bool = False,
        history_limit: int | None = None,
        history_capture: _ContextCapture | None = None,
        timing_key: _TimingScope = None,
    ) -> None:
        self._inspection_lock = threading.RLock()
        self._waiter_ids = count()
        self._sync_waiters: dict[int, _SyncStateWaiter] = {}
        self._async_waiters: dict[int, _AsyncStateWaiter] = {}
        self._finalized = False
        self._history_capture = history_capture
        self.context_id = context_id
        self.graph = submission.graph
        self.graph_scope = submission.graph_scope
        self.supervised_graphs = supervises
        self.controller = controller
        self._local_engine_id = local_engine_id
        self.engine_id = engine_id
        self.generation = 0
        self.artifact_context = submission.artifacts
        self.config_context = submission.configs

        self._history_budget = _HistoryBudget(history_limit)
        self.status = ContextStatus(_budget=self._history_budget)
        self._snapshot_revision = 0
        self._published_state = ContextState.SUBMITTED
        self._executions: list[ExecutionReport] = []
        self._executions_snapshot: tuple[ExecutionReport, ...] | None = ()
        self._record_repository = ContextRecordRepository(settings, context_id)
        self._report: ContextReport | None = None
        self._artifacts: dict[Artifact, ArtifactResult] = {}
        self._artifact_context_snapshot = self._encode_artifact_context(
            submission.artifacts
        )
        self._checkpoint_data = dict(submission.artifacts.instances)
        self._config_context_snapshot = self._encode_config_context(
            submission.configs
        )
        self._artifact_results_snapshot: tuple[
            tuple[int, ArtifactResult], ...
        ] = ()
        self._progress_profile = progress_profile
        self._selected_progress_profile = progress_profile
        self._timing_key = timing_key
        self._timing_learning_generation: int | None = 0 if engine_id == local_engine_id else None
        self._timing_remote_reported = False
        self._completed_iterations = 0
        self._remote_progress: ProgressSnapshot | None = None
        self._history_finalized = False
        self._history_completed_iterations = 0
        self._accepted_request_revision = -1
        self.failure: Exception | None = None
        self.failed_step: StepReference | None = None
        self.settings: CombinedContextSettings | None = None
        self._settings = settings
        self._lifecycle_reporter = lifecycle_reporter
        self._progress_tracker = _ProgressTracker(
            context_id=context_id,
            graph_scope=submission.graph_scope,
            graph_version=submission.graph.version,
            compiled_steps=submission.graph._compiled_graph.steps,
            max_iterations=settings.max_iterations,
            profile=progress_profile,
            learn_progress=settings.instrumentation.learn_progress,
        )

    @property
    def state(self) -> ContextState:
        with self._inspection_lock:
            return self.status.state

    @property
    def observed_state(self) -> ContextState:
        with self._inspection_lock:
            return self._published_state

    @property
    def submitted_artifact_context(self) -> ArtifactContext:
        return self.artifact_context

    @property
    def submitted_config_context(self) -> ConfigContext:
        return self.config_context

    @property
    def finalized(self) -> bool:
        with self._inspection_lock:
            return self._finalized

    @property
    def iteration_count(self) -> int:
        with self._inspection_lock:
            return self.status.iteration_count

    @property
    def progress(self) -> ProgressSnapshot:
        with self._inspection_lock:
            if self._remote_progress is not None:
                return self._remote_progress
            return self._progress_tracker.snapshot

    @property
    def stop_requested(self) -> bool:
        with self._inspection_lock:
            return self.status.stop_requested

    @property
    def runtime_alive(self) -> bool:
        with self._inspection_lock:
            return (
                not self.status.stop_requested
                and not self.status.state.is_draining
                and not self.status.state.is_terminal
            )

    @property
    def is_local(self) -> bool:
        with self._inspection_lock:
            return self.engine_id == self._local_engine_id

    def _is_local_engine(self, engine_id: str) -> bool:
        return engine_id == self._local_engine_id

    @property
    def can_dispatch(self) -> bool:
        return self.is_local and self.state in (
            ContextState.RUNNING,
            ContextState.PLACEMENT_WAITING,
        )

    @property
    def can_reiterate(self) -> bool:
        """Whether the owner may start another iteration at this instant."""
        with self._inspection_lock:
            if self.status.stop_requested or not self.is_running or self.settings is None:
                return False
            return (
                self.settings.max_iterations is None
                or self.status.iteration_count < self.settings.max_iterations
            )

    def _reiterate(self, actor: CommandOrigin) -> bool:
        with self._inspection_lock:
            if not self.can_reiterate:
                return False
            self.status.start_iteration(actor)
            self._touch_snapshot_locked()
            self._update_progress_context()
            return True

    @property
    def has_been_validated(self) -> bool:
        with self._inspection_lock:
            return self.status.has_been_validated

    @property
    def is_queued(self) -> bool:
        return self.state is ContextState.QUEUED

    @property
    def is_routing(self) -> bool:
        return self.state is ContextState.ROUTING

    @property
    def is_running(self) -> bool:
        return self.state is ContextState.RUNNING

    @property
    def is_paused(self) -> bool:
        return self.state is ContextState.PAUSED

    @property
    def is_placement_waiting(self) -> bool:
        return self.state is ContextState.PLACEMENT_WAITING

    @property
    def is_aborting(self) -> bool:
        return self.state is ContextState.ABORTING

    @property
    def is_failing(self) -> bool:
        return self.state is ContextState.FAILING

    @property
    def is_draining(self) -> bool:
        return self.state.is_draining

    @property
    def is_aborted(self) -> bool:
        return self.state is ContextState.ABORTED

    @property
    def is_terminal(self) -> bool:
        return self.state.is_terminal

    @property
    def is_active(self) -> bool:
        return self.state.is_active

    @property
    def is_supervising(self) -> bool:
        return self.controller or self.supervised_graphs is None or bool(
            self.supervised_graphs
        )

    @property
    def is_controller(self) -> bool:
        return self.controller

    @property
    def completed_iterations(self) -> int:
        with self._inspection_lock:
            return self._completed_iterations

    def _validate_submission(self, actor: CommandOrigin) -> bool:
        self._transition(ContextState.VALIDATING, actor)
        try:
            self._validate()
        except Exception as error:
            with self._inspection_lock:
                self.failure = error
                self._transition(ContextState.REJECTED, actor)
            return False
        with self._inspection_lock:
            self.settings = self._settings
            self.failure = None
            self._transition(ContextState.VALIDATED, actor)
        return True

    def _queue(self, actor: CommandOrigin) -> None:
        self._transition(ContextState.QUEUED, actor)

    def _await_routing(self, actor: CommandOrigin) -> None:
        self._transition(ContextState.ROUTING, actor)

    def _start(self, actor: CommandOrigin) -> None:
        with self._inspection_lock:
            self._apply_transition(ContextState.RUNNING, actor)
            self.status.start_iteration(actor)
            self._touch_snapshot_locked()
            self._update_progress_context()
            notifications = self._resolve_waiters()
        self._notify_waiters(*notifications)

    def _pause(self, actor: CommandOrigin) -> None:
        self._transition(ContextState.PAUSED, actor)

    def _resume(
        self,
        actor: CommandOrigin,
        *,
        placement_waiting: bool = False,
    ) -> None:
        next_state = (
            ContextState.PLACEMENT_WAITING
            if placement_waiting
            else ContextState.RUNNING
        )
        self._transition(next_state, actor)

    def _wait_for_placement(self, actor: CommandOrigin) -> None:
        if self.state is ContextState.RUNNING:
            self._transition(ContextState.PLACEMENT_WAITING, actor)

    def _resolve_placement(self, actor: CommandOrigin) -> None:
        if self.state is ContextState.PLACEMENT_WAITING:
            self._transition(ContextState.RUNNING, actor)

    def _request_stop(self, actor: CommandOrigin) -> None:
        with self._inspection_lock:
            if self.state not in {
                ContextState.VALIDATED,
                ContextState.ROUTING,
                ContextState.QUEUED,
                ContextState.RUNNING,
                ContextState.PLACEMENT_WAITING,
                ContextState.PAUSED,
            }:
                raise ValueError(
                    f"context {self.context_id!r} cannot be stopped "
                    f"from {self.state.value!r}"
                )

            entry = self.status.request_stop(actor)
            if entry is not None:
                self._touch_snapshot_locked()
                # Publish acceptance before any terminal transition/removal. Stop
                # intent is independent of the current scheduling state.
                self._lifecycle_reporter(self, entry)
            if self.state in {
                ContextState.VALIDATED,
                ContextState.ROUTING,
                ContextState.QUEUED,
            }:
                self._transition(ContextState.FINISHED, actor)

    def _request_abort(self, actor: CommandOrigin) -> None:
        with self._inspection_lock:
            self.failure = None
            self.failed_step = None
            if self.state in {
                ContextState.RUNNING,
                ContextState.PLACEMENT_WAITING,
                ContextState.PAUSED,
            }:
                self._transition(ContextState.ABORTING, actor)
                return
            self._transition(ContextState.ABORTED, actor)

    def _complete_abort(self, actor: CommandOrigin) -> None:
        self._transition(ContextState.ABORTED, actor)

    def _request_failure(
        self,
        actor: CommandOrigin,
        failure: Exception,
        failed_step: StepReference | None = None,
    ) -> None:
        with self._inspection_lock:
            self.failure = failure
            self.failed_step = failed_step
            self._transition(ContextState.FAILING, actor)

    def _complete_failure(self, actor: CommandOrigin) -> None:
        self._transition(ContextState.FAILED, actor)

    def _finish(self, actor: CommandOrigin) -> None:
        with self._inspection_lock:
            self.failure = None
            self.failed_step = None
            self._transition(ContextState.FINISHED, actor)

    def _load_executions(
        self,
        executions: tuple[ExecutionReport, ...],
    ) -> None:
        with self._inspection_lock:
            self._executions = list(executions)
            self._executions_snapshot = executions
            self._touch_snapshot_locked()

    def _load_artifacts(self, artifacts: dict[Artifact, ArtifactResult]) -> None:
        with self._inspection_lock:
            self._artifacts = dict(artifacts)
            self._artifact_results_snapshot = self._encode_artifact_results(
                self._artifacts
            )
            self._touch_snapshot_locked()

    def _complete_iteration(
        self,
        executions: tuple[ExecutionReport, ...],
        checkpoint: dict[Artifact, Data[object]],
    ) -> None:
        with self._inspection_lock:
            self._completed_iterations = self.status.iteration_count
            self._executions.extend(executions)
            self._executions_snapshot = None
            self._checkpoint_data = dict(checkpoint)
            self._artifact_context_snapshot = self._encode_artifact_data(
                self._checkpoint_data
            )
            self._touch_snapshot_locked()

    def _record_value(self, record: ContextRecord) -> ContextRecord:
        with self._inspection_lock:
            committed = self._record_repository.commit(record)
            self._touch_snapshot_locked()
            return committed

    def _request_remote_control(
        self,
        request: ContextRequest,
        duration_seconds: float | None,
        actor: CommandOrigin,
    ) -> ContextSnapshot:
        with self._inspection_lock:
            self.status.request_control(request, duration_seconds, actor)
            self._touch_snapshot_locked()
            return self._snapshot_locked(
                request=request,
                request_duration=duration_seconds,
            )

    def _accept_remote_request(self, snapshot: ContextSnapshot) -> bool:
        """Accept one idempotent request without importing stale state."""
        request = snapshot.request
        if request is None:
            raise ValueError("request snapshot must contain a request")
        with self._inspection_lock:
            if (
                snapshot.generation != self.generation
                or snapshot.engine_id != self.engine_id
            ):
                return False
            if not self.is_local or self.status.state.is_terminal:
                return False
            requested = snapshot.history[-1] if snapshot.history else None
            if (
                not isinstance(requested, ControlRequested)
                or requested.request is not request
                or requested.duration_seconds != snapshot.request_duration
            ):
                raise ValueError(
                    "request snapshot has no matching latest control entry"
                )

            if snapshot.revision <= self._accepted_request_revision:
                return False

            self._accepted_request_revision = snapshot.revision
            self.status.revision = max(
                self.status.revision,
                self._snapshot_revision,
            )
            self.status.request_control(
                request,
                snapshot.request_duration,
                requested.actor,
            )
            self._snapshot_revision = max(
                self._snapshot_revision,
                snapshot.revision,
            )
            self._touch_snapshot_locked()
            return True

    def _change_engine(
        self,
        engine_id: str,
        actor: CommandOrigin,
    ) -> tuple[str, ContextState]:
        with self._inspection_lock:
            previous_engine_id = self.engine_id
            previous_state = self.status.state
            if engine_id == previous_engine_id:
                return previous_engine_id, previous_state

            previous_progress = self.progress
            self.generation += 1
            self.status.change_engine(
                previous_engine_id=previous_engine_id,
                current_engine_id=engine_id,
                generation=self.generation,
                checkpoint_iteration=self._completed_iterations,
                actor=actor,
            )
            self.engine_id = engine_id
            self.failure = None
            self.failed_step = None
            self._report = None
            self._artifacts.clear()
            self._artifact_results_snapshot = ()
            self._finalized = False
            self._remote_progress = None
            self._accepted_request_revision = -1

            if self.status.state is not ContextState.QUEUED:
                self.status.apply_transition(ContextState.QUEUED, actor)
            self.status.iteration_count = self._completed_iterations
            self.status.finished_at = None
            self._published_state = ContextState.QUEUED
            self.artifact_context._instances = dict(self._checkpoint_data)
            self._reset_progress_tracker(previous_progress)
            self._touch_snapshot_locked()
            notifications = self._resolve_waiters()
        self._notify_waiters(*notifications)
        return previous_engine_id, previous_state

    def _apply_remote_snapshot(
        self,
        snapshot: ContextSnapshot,
        *,
        checkpoint: dict[Artifact, Data[object]],
        configs: dict[object, Data[object]],
        artifacts: dict[Artifact, ArtifactResult],
    ) -> tuple[bool, ContextState, int]:
        with self._inspection_lock:
            if snapshot.request is not None:
                raise ValueError("committed snapshot must not contain a request")
            graph_key = (
                self.graph_scope[0]
                if isinstance(self.graph_scope, tuple)
                else None
            )
            if (
                snapshot.graph_key != graph_key
                or snapshot.graph_version != self.graph.version
            ):
                raise ValueError("snapshot graph identity does not match context")
            if snapshot.generation < self.generation:
                return False, self.status.state, self._record_repository.sequence
            if (
                snapshot.generation == self.generation
                and snapshot.revision <= self._snapshot_revision
            ):
                return False, self.status.state, self._record_repository.sequence
            if (
                self.is_local
                and self.status.revision != 0
                and not self.status.state.is_terminal
            ):
                raise RuntimeError(
                    "a committed snapshot cannot replace a locally owned context"
                )

            previous_state = self.status.state
            previous_record_sequence = self._record_repository.sequence
            self.generation = snapshot.generation
            self.engine_id = snapshot.engine_id
            self.status.state = snapshot.state
            self.status.revision = max(
                snapshot.revision,
                max(
                    (entry.revision for entry in snapshot.history),
                    default=0,
                ),
            )
            self.status.iteration_count = snapshot.iteration_count
            self.status.stop_requested = snapshot.stop_requested
            stop = next((entry for entry in snapshot.history if isinstance(entry, StopRequested)), None)
            self.status.stop_requested_by = stop.actor if stop is not None else None
            self.status.stop_requested_at = stop.recorded_at if stop is not None else None
            self.status.created_at = snapshot.created_at
            self.status.updated_at = snapshot.updated_at
            self.status.validated_at = snapshot.validated_at
            self.status.started_at = snapshot.started_at
            self.status.finished_at = snapshot.finished_at
            self._history_budget.restore(snapshot)
            self.status.history = list(snapshot.history)
            self._published_state = snapshot.state
            self._snapshot_revision = snapshot.revision
            self._completed_iterations = snapshot.completed_iterations
            self._remote_progress = snapshot.progress
            self._record_repository.replace(snapshot.records, snapshot.record_sequence)
            self._executions = [] if snapshot.finalized else list(snapshot.reports)
            self._executions_snapshot = snapshot.reports
            self._report = snapshot.report
            self._artifacts = dict(artifacts)
            self._artifact_results_snapshot = snapshot.artifacts
            self._checkpoint_data = dict(checkpoint)
            self._artifact_context_snapshot = snapshot.artifact_context
            self._config_context_snapshot = snapshot.config_context
            self.artifact_context._instances = dict(checkpoint)
            self.config_context._instances = dict(configs)
            self.settings = self._settings
            self._finalized = snapshot.finalized
            if (
                snapshot.finalized
                and self.settings.artifact_policy.release_entry_artifacts
            ):
                self.artifact_context._release()
                self._checkpoint_data.clear()
                self._artifact_context_snapshot = ()
            self.failure = (
                None if snapshot.report is None else snapshot.report.failure
            )
            self.failed_step = (
                None if snapshot.report is None else snapshot.report.failed_step
            )
            if self.is_local and not snapshot.finalized:
                self._remote_progress = None
                self._reset_progress_tracker(snapshot.progress)
            if snapshot.finalized and self._history_capture is not None:
                capture, self._history_capture = self._history_capture, None
                capture.handoff(self, snapshot.report)
            notifications = self._resolve_waiters()
        self._notify_waiters(*notifications)
        return True, previous_state, previous_record_sequence

    def _mark_history_iteration(self, iteration: int) -> None:
        with self._inspection_lock:
            self._history_completed_iterations = max(
                self._history_completed_iterations,
                iteration,
            )

    def _mark_history_finalized(self) -> None:
        with self._inspection_lock:
            self._history_finalized = True

    def _apply_progress(self, update: _ProgressUpdate) -> bool:
        with self._inspection_lock:
            applied = self._progress_tracker.apply(update)
            if applied:
                self._touch_snapshot_locked()
            return applied

    def _timing_evidence(self) -> dict[str, object]:
        """Compact detached selected-profile evidence; no live store access."""
        from .._timing import _TimingKey
        key = self._timing_key
        selected = self._selected_progress_profile
        return {
            "matching": "configuration-aware" if isinstance(key, _TimingKey) else
                        ("legacy" if key is not None else "unavailable"),
            "configuration_key": key.configuration_key if isinstance(key, _TimingKey) else None,
            "compatibility_key": key.compatibility_key if isinstance(key, _TimingKey) else None,
            "selected_run_count": selected.run_count,
            "selected_graph_completion_count": selected.graph_completion_count,
            "selected_graph_mean_seconds": selected.graph_mean_seconds,
            "learning_lineage": "local" if self.is_local and
                self._timing_learning_generation == self.generation else "unestablished_or_remote",
        }

    def _replace_progress_profile(self, profile: _ProgressProfile) -> None:
        with self._inspection_lock:
            self._progress_profile = profile
            self._progress_tracker.replace_profile(profile)
            if self._remote_progress is None:
                self._touch_snapshot_locked()

    @property
    def snapshot(self) -> ContextSnapshot:
        with self._inspection_lock:
            return self._snapshot_locked()

    def _snapshot_locked(
        self,
        *,
        request: ContextRequest | None = None,
        request_duration: float | None = None,
    ) -> ContextSnapshot:
        graph_key = (
            self.graph_scope[0]
            if isinstance(self.graph_scope, tuple)
            else None
        )
        return ContextSnapshot(
            context_id=self.context_id,
            graph_key=graph_key,
            graph_version=self.graph.version,
            engine_id=self.engine_id,
            generation=self.generation,
            revision=self._snapshot_revision,
            state=self.status.state,
            request=request,
            request_duration=request_duration,
            iteration_count=self.status.iteration_count,
            completed_iterations=self._completed_iterations,
            stop_requested=self.status.stop_requested,
            finalized=self._finalized,
            progress=(
                self._remote_progress
                if self._remote_progress is not None
                else self._progress_tracker.snapshot
            ),
            records=self._record_repository.snapshot,
            record_sequence=self._record_repository.sequence,
            reports=self._execution_reports,
            report=self._report,
            artifacts=self._artifact_results_snapshot,
            artifact_context=self._artifact_context_snapshot,
            config_context=self._config_context_snapshot,
            context_settings=self._portable_context_settings(),
            artifacts_serialized=bool(self.graph._serializer_bindings),
            history=tuple(self.status.history),
            created_at=self.status.created_at,
            updated_at=self.status.updated_at,
            validated_at=self.status.validated_at,
            started_at=self.status.started_at,
            finished_at=self.status.finished_at,
        )

    @property
    def _execution_reports(self) -> tuple[ExecutionReport, ...]:
        with self._inspection_lock:
            if self._executions_snapshot is None:
                self._executions_snapshot = tuple(self._executions)
            return self._executions_snapshot

    def _mark_finalized(self) -> None:
        with self._inspection_lock:
            if self._finalized:
                return
            if not self.status.state.is_terminal:
                raise RuntimeError("cannot finalize a nonterminal context")
            finished_at = self.status.finished_at
            if finished_at is None:
                raise RuntimeError("terminal context has no completion timestamp")
            self._report = ContextReport(
                context_id=self.context_id,
                state=self.status.state,
                revision=self.status.revision,
                iteration_count=self.status.iteration_count,
                stop_requested=self.status.stop_requested,
                created_at=self.status.created_at,
                updated_at=self.status.updated_at,
                validated_at=self.status.validated_at,
                started_at=self.status.started_at,
                finished_at=finished_at,
                history=tuple(self.status.history),
                executions=self._execution_reports,
                failure=self.failure,
                failed_step=self.failed_step,
            )
            failures = tuple(
                record.exception
                for execution in self._report.executions
                for attempt in execution.attempts
                for record in attempt.records
                if isinstance(record, FailureRecord)
            )
            if self.failure is not None:
                failures += (self.failure,)
            _detach_failure_tracebacks(failures)
            # The finalized tuple now owns the evidence. Do not retain a second
            # mutable reference array for as long as a client keeps its run.
            self._executions.clear()

            if (
                self.settings is not None
                and self.settings.artifact_policy.release_entry_artifacts
            ):
                self.artifact_context._release()
                self._checkpoint_data.clear()
                self._artifact_context_snapshot = ()
            self.supervised_graphs = ()
            self._finalized = True
            self._published_state = self.status.state
            self._update_progress_context()
            self._touch_snapshot_locked()
            transition = self._terminal_transition()
            capture, self._history_capture = self._history_capture, None
            if capture is not None:
                # The inspection lock guards finalized readiness. Register the
                # handoff before releasing it or resolving any waiters.
                capture.handoff(self, self._report)
            notifications = self._resolve_waiters()
        try:
            self._lifecycle_reporter(self, transition)
        finally:
            self._notify_waiters(*notifications)

    def _wait_ready(self, state: ContextState | None) -> bool:
        with self._inspection_lock:
            return self._matches_wait(
                self.status.state,
                state,
                self._finalized,
            )

    def _wait(
        self,
        state: ContextState | None,
        timeout: int | float | None,
    ) -> None:
        with self._inspection_lock:
            if self._matches_wait(
                self.status.state,
                state,
                self._finalized,
            ):
                return
            waiter_id = next(self._waiter_ids)
            waiter = _SyncStateWaiter(state=state)
            self._sync_waiters[waiter_id] = waiter

        completed = waiter.event.wait(timeout)

        with self._inspection_lock:
            self._sync_waiters.pop(waiter_id, None)

        if completed:
            return
        raise TimeoutError(f"timed out waiting for context {self.context_id!r}")

    async def _wait_async(
        self,
        state: ContextState | None,
        timeout: int | float | None,
    ) -> None:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()

        with self._inspection_lock:
            if self._matches_wait(
                self.status.state,
                state,
                self._finalized,
            ):
                return
            waiter_id = next(self._waiter_ids)
            self._async_waiters[waiter_id] = _AsyncStateWaiter(
                state=state,
                loop=loop,
                future=future,
            )

        try:
            if timeout is None:
                return await future
            return await asyncio.wait_for(future, timeout)
        except TimeoutError:
            raise TimeoutError(
                f"timed out waiting for context {self.context_id!r}"
            ) from None
        finally:
            with self._inspection_lock:
                self._async_waiters.pop(waiter_id, None)

    def _transition(
        self,
        next_state: ContextState,
        actor: CommandOrigin,
    ) -> None:
        with self._inspection_lock:
            try:
                self._apply_transition(next_state, actor)
            finally:
                self._notify_waiters(*self._resolve_waiters())

    def _apply_transition(
        self,
        next_state: ContextState,
        actor: CommandOrigin,
    ) -> None:
        if next_state not in self._allowed_transitions[self.state]:
            raise ValueError(
                f"cannot transition context {self.context_id!r} "
                f"from {self.state.value!r} to {next_state.value!r}"
            )
        self.status.apply_transition(next_state=next_state, actor=actor)
        self._touch_snapshot_locked()
        transition = self.status.history[-1]
        if not isinstance(transition, StateTransition):
            raise RuntimeError("context transition history is inconsistent")
        if not next_state.is_terminal:
            self._update_progress_context()
            self._published_state = next_state
            self._lifecycle_reporter(self, transition)

    def _touch_snapshot_locked(self) -> None:
        self._snapshot_revision = max(
            self._snapshot_revision + 1,
            self.status.revision,
        )

    def _update_progress_context(self) -> None:
        self._progress_tracker.change_context(
            state=self.status.state,
            iteration=self.status.iteration_count,
            started_at=self.status.started_at,
            finished_at=self.status.finished_at,
        )

    def _terminal_transition(self) -> StateTransition:
        for entry in reversed(self.status.history):
            if isinstance(entry, StateTransition) and entry.next_state.is_terminal:
                return entry
        raise RuntimeError("terminal context has no terminal transition")

    def _resolve_waiters(
        self,
    ) -> tuple[
        tuple[_SyncStateWaiter, ...],
        tuple[_AsyncStateWaiter, ...],
    ]:
        if not self._sync_waiters and not self._async_waiters:
            return (), ()

        sync_waiters: list[_SyncStateWaiter] = []
        async_waiters: list[_AsyncStateWaiter] = []

        for waiter_id, waiter in tuple(self._sync_waiters.items()):
            if not self._matches_wait(
                self.status.state,
                waiter.state,
                self._finalized,
            ):
                continue
            self._sync_waiters.pop(waiter_id, None)
            sync_waiters.append(waiter)

        for waiter_id, waiter in tuple(self._async_waiters.items()):
            if not self._matches_wait(
                self.status.state,
                waiter.state,
                self._finalized,
            ):
                continue
            self._async_waiters.pop(waiter_id, None)
            async_waiters.append(waiter)

        return tuple(sync_waiters), tuple(async_waiters)

    @staticmethod
    def _notify_waiters(
        sync_waiters: tuple[_SyncStateWaiter, ...],
        async_waiters: tuple[_AsyncStateWaiter, ...],
    ) -> None:
        for waiter in sync_waiters:
            waiter.event.set()

        for waiter in async_waiters:
            try:
                waiter.loop.call_soon_threadsafe(
                    ContextInstance._complete_async_waiter,
                    waiter.future,
                )
            except RuntimeError:
                pass

    @staticmethod
    def _complete_async_waiter(
        future: asyncio.Future[None],
    ) -> None:
        if not future.done():
            future.set_result(None)

    @staticmethod
    def _matches_wait(
        current_state: ContextState,
        requested_state: ContextState | None,
        finalized: bool,
    ) -> bool:
        if current_state.is_terminal:
            return finalized
        return requested_state is not None and current_state is requested_state

    def _report_value(self) -> ContextReport:
        with self._inspection_lock:
            if self._report is None:
                raise RuntimeError("terminal context report is unavailable")
            return self._report

    def _artifact_result(
        self,
        reference: int | ArtifactDefinition | Artifact,
    ) -> ArtifactResult:
        artifact = self._resolve_artifact(reference)
        with self._inspection_lock:
            try:
                return self._artifacts[artifact]
            except KeyError:
                raise KeyError(
                    f"artifact result is unavailable for context {self.context_id!r}"
                ) from None

    def _resolve_artifact(
        self,
        reference: int | ArtifactDefinition | Artifact,
    ) -> Artifact:
        registry = self.graph._specification.artifacts

        if type(reference) is int:
            for definition in registry.definitions:
                if definition.artifact_id == reference:
                    return registry.source_for(definition)
            raise KeyError(f"unknown artifact ID: {reference!r}")

        if isinstance(reference, ArtifactDefinition):
            for definition in registry.definitions:
                if definition is reference:
                    return registry.source_for(definition)
            raise KeyError(
                "ArtifactDefinition does not belong to the context graph"
            )

        if isinstance(reference, Artifact):
            if reference not in registry.sources:
                raise KeyError("Artifact does not belong to the context graph")
            return reference

        raise TypeError(
            "artifact reference must be int, ArtifactDefinition, or Artifact"
        )

    def _encode_artifact_context(
        self,
        context: ArtifactContext,
    ) -> tuple[tuple[int, Data[object]], ...]:
        return self._encode_artifact_data(dict(context.instances))

    def _encode_artifact_data(
        self,
        values: dict[Artifact, Data[object]],
    ) -> tuple[tuple[int, Data[object]], ...]:
        registry = self.graph._specification.artifacts
        encoded: list[tuple[int, Data[object]]] = []
        for artifact in registry.sources:
            data = values.get(artifact)
            if data is None:
                continue
            value = data.value
            serializer = self.graph._serializer_bindings.get(artifact)
            if serializer is not None and value is not None:
                value = serializer.serialize(value)
                if not isinstance(value, bytes):
                    raise TypeError("artifact serializers must return bytes")
            encoded.append(
                (
                    registry.definition_for(artifact).artifact_id,
                    Data(value=value),
                )
            )
        return tuple(encoded)

    def _encode_config_context(
        self,
        context: ConfigContext,
    ) -> tuple[tuple[int, Data[object]], ...]:
        registry = self.graph._specification.configs
        return tuple(
            (
                registry.definition_for(field).config_id,
                Data(value=data.value),
            )
            for field in registry.sources
            if (data := context.get(field)) is not None
        )

    def _encode_artifact_results(
        self,
        artifacts: dict[Artifact, ArtifactResult],
    ) -> tuple[tuple[int, ArtifactResult], ...]:
        registry = self.graph._specification.artifacts
        encoded: list[tuple[int, ArtifactResult]] = []
        for artifact in registry.sources:
            result = artifacts.get(artifact)
            if result is None:
                continue
            value = result.value
            serializer = self.graph._serializer_bindings.get(artifact)
            if serializer is not None and value is not None:
                value = serializer.serialize(value)
                if not isinstance(value, bytes):
                    raise TypeError("artifact serializers must return bytes")
            encoded.append(
                (
                    registry.definition_for(artifact).artifact_id,
                    ArtifactResult(
                        data=Data(value=value),
                        history=result.history,
                    ),
                )
            )
        return tuple(encoded)

    def _portable_context_settings(self) -> ContextSettings:
        policy = self._settings.artifact_policy
        registry = self.graph._specification.artifacts
        retained_ids = tuple(
            registry.definition_for(artifact).artifact_id
            for artifact in policy.retained_artifacts
        )
        return ContextSettings(
            artifact_policy=ArtifactPolicy(
                retained_artifacts=retained_ids,
                release_entry_artifacts=policy.release_entry_artifacts,
            ),
            retry_policy=self._settings.retry_policy,
            max_iterations=self._settings.max_iterations,
            max_repeats=self._settings.max_repeats,
            record_history_limit=self._settings.record_history_limit,
            record_max_keys=self._settings.record_max_keys,
            record_max_value_bytes=self._settings.record_max_value_bytes,
            record_max_total_bytes=self._settings.record_max_total_bytes,
        )

    def _reset_progress_tracker(self, previous: ProgressSnapshot) -> None:
        self._progress_tracker = _ProgressTracker(
            context_id=self.context_id,
            graph_scope=self.graph_scope,
            graph_version=self.graph.version,
            compiled_steps=self.graph._compiled_graph.steps,
            max_iterations=self._settings.max_iterations,
            profile=self._progress_profile,
            learn_progress=self._settings.instrumentation.learn_progress,
        )
        self._progress_tracker.change_context(
            state=ContextState.QUEUED,
            iteration=self._completed_iterations,
            started_at=self.status.started_at,
            finished_at=None,
        )
        self._progress_tracker.restore_timing(previous)

    def _validate(self) -> None:
        if not isinstance(self.artifact_context, ArtifactContext):
            raise TypeError("artifact_context must be an ArtifactContext instance")

        if not isinstance(self.config_context, ConfigContext):
            raise TypeError("config_context must be a ConfigContext instance")

        if not self.graph.confirmed:
            raise RuntimeError("context graph is not confirmed")
        self.graph._compiled_graph

        artifact_registry = self.graph._specification.artifacts
        config_registry = self.graph._specification.configs

        if not self.artifact_context._is_normalized_for(artifact_registry):
            raise RuntimeError("artifact context is not sealed for the context graph")

        if not self.config_context._is_normalized_for(config_registry):
            raise RuntimeError("config context is not sealed for the context graph")

        artifact_source_ids = {id(source) for source in artifact_registry.sources}
        if any(
            id(source) not in artifact_source_ids
            for source in self.artifact_context.instances
        ):
            raise RuntimeError("artifact context contains a source outside the graph")

        config_source_ids = {id(source) for source in config_registry.sources}
        if any(
            id(source) not in config_source_ids
            for source in self.config_context.instances
        ):
            raise RuntimeError("config context contains a source outside the graph")

        if not self.config_context._validate():
            raise RuntimeError("normalized context is missing required configs")

        if not self.artifact_context._validate():
            raise RuntimeError("normalized context is missing entry artifacts")
