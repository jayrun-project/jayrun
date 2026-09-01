from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from itertools import count
from typing import ClassVar

from ...core.artifact.base import Artifact
from ...core.artifact.context import ArtifactContext
from ...core.config.context import ConfigContext
from ...core.graph.definition.artifact import ArtifactDefinition
from ...core.graph.graph_definition import GraphDefinition
from ..artifact.result import ArtifactResult
from ..context.step_reference import StepReference
from ..recorders.context.report import ContextReport
from ..recorders.execution.records import ExecutionReport
from ..settings.combined_context import CombinedContextSettings
from ..settings.context import ContextSettings
from ..settings.engine import EngineSettings
from .context_state import ContextState
from .context_status import ContextStatus
from .identities import BaseIdentity


@dataclass(slots=True)
class _SyncStateWaiter:
    state: ContextState | None
    event: threading.Event = field(default_factory=threading.Event)


@dataclass(slots=True)
class _AsyncStateWaiter:
    state: ContextState | None
    loop: asyncio.AbstractEventLoop
    future: asyncio.Future[None]


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
                ContextState.QUEUED,
                ContextState.RUNNING,
                ContextState.STOPPED,
                ContextState.ABORTED,
            }
        ),
        ContextState.QUEUED: frozenset(
            {
                ContextState.RUNNING,
                ContextState.STOPPED,
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
        artifacts: ArtifactContext,
        configs: ConfigContext,
        supervises: tuple[GraphDefinition, ...],
        engine_settings: EngineSettings,
        context_settings: ContextSettings | None,
    ) -> None:
        self._inspection_lock = threading.RLock()
        self._waiter_ids = count()
        self._sync_waiters: dict[int, _SyncStateWaiter] = {}
        self._async_waiters: dict[int, _AsyncStateWaiter] = {}
        self._finalized = False
        self.context_id = context_id
        self.graph = artifacts.graph
        self.supervised_graphs = supervises
        self.artifact_context = artifacts._fork()
        self.config_context = configs._fork()

        self._submitted_artifact_context = artifacts._fork()
        self._submitted_artifact_context._release_target = None
        self._submitted_artifact_context._seal()
        self._submitted_config_context = configs._fork()
        self._submitted_config_context._seal()

        self.status = ContextStatus()
        self._published_state = ContextState.SUBMITTED
        self._executions: tuple[ExecutionReport, ...] = ()
        self._report: ContextReport | None = None
        self._artifacts: dict[Artifact, ArtifactResult] = {}
        self.failure: Exception | None = None
        self.failed_step: StepReference | None = None
        self.settings: CombinedContextSettings | None = None
        self._engine_settings = engine_settings
        self._context_settings = context_settings

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
        return self._submitted_artifact_context

    @property
    def submitted_config_context(self) -> ConfigContext:
        return self._submitted_config_context

    @property
    def finalized(self) -> bool:
        with self._inspection_lock:
            return self._finalized

    @property
    def iteration_count(self) -> int:
        with self._inspection_lock:
            return self.status.iteration_count

    @property
    def stop_requested(self) -> bool:
        with self._inspection_lock:
            return self.status.stop_requested

    @property
    def can_dispatch(self) -> bool:
        return self.state in {
            ContextState.RUNNING,
            ContextState.PLACEMENT_WAITING,
        }

    @property
    def can_reiterate(self) -> bool:
        if self.stop_requested or not self.is_running:
            return False
        if self.settings.max_iterations is None:
            return True
        return self.iteration_count < self.settings.max_iterations

    def _reiterate(self, actor: BaseIdentity) -> bool:
        with self._inspection_lock:
            if not self.can_reiterate:
                return False
            self.status.start_iteration(actor)
            return True

    @property
    def has_been_validated(self) -> bool:
        with self._inspection_lock:
            return self.status.has_been_validated

    @property
    def is_queued(self) -> bool:
        return self.state is ContextState.QUEUED

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
        return bool(self.supervised_graphs)

    def _validate_submission(self, actor: BaseIdentity) -> bool:
        self._transition(ContextState.VALIDATING, actor)
        try:
            settings = CombinedContextSettings.from_settings(
                engine_settings=self._engine_settings,
                context_settings=self._context_settings,
                artifact_registry=self.graph._specification.artifacts,
            )
            self._validate()
        except Exception as error:
            with self._inspection_lock:
                self.failure = error
                self._transition(ContextState.REJECTED, actor)
            return False
        with self._inspection_lock:
            self.settings = settings
            self.failure = None
            self._transition(ContextState.VALIDATED, actor)
        return True

    def _queue(self, actor: BaseIdentity) -> None:
        self._transition(ContextState.QUEUED, actor)

    def _start(self, actor: BaseIdentity) -> None:
        with self._inspection_lock:
            self._apply_transition(ContextState.RUNNING, actor)
            self.status.start_iteration(actor)
            notifications = self._resolve_waiters()
        self._notify_waiters(*notifications)

    def _pause(self, actor: BaseIdentity) -> None:
        self._transition(ContextState.PAUSED, actor)

    def _resume(
        self,
        actor: BaseIdentity,
        *,
        placement_waiting: bool = False,
    ) -> None:
        next_state = (
            ContextState.PLACEMENT_WAITING
            if placement_waiting
            else ContextState.RUNNING
        )
        self._transition(next_state, actor)

    def _wait_for_placement(self, actor: BaseIdentity) -> None:
        if self.state is ContextState.RUNNING:
            self._transition(ContextState.PLACEMENT_WAITING, actor)

    def _resolve_placement(self, actor: BaseIdentity) -> None:
        if self.state is ContextState.PLACEMENT_WAITING:
            self._transition(ContextState.RUNNING, actor)

    def _request_stop(self, actor: BaseIdentity) -> None:
        with self._inspection_lock:
            if self.state not in {
                ContextState.VALIDATED,
                ContextState.QUEUED,
                ContextState.RUNNING,
                ContextState.PLACEMENT_WAITING,
                ContextState.PAUSED,
            }:
                raise ValueError(
                    f"context {self.context_id!r} cannot be stopped "
                    f"from {self.state.value!r}"
                )

            self.status.request_stop(actor)
            if self.state in {ContextState.VALIDATED, ContextState.QUEUED}:
                self._transition(ContextState.STOPPED, actor)

    def _request_abort(self, actor: BaseIdentity) -> None:
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

    def _complete_abort(self, actor: BaseIdentity) -> None:
        self._transition(ContextState.ABORTED, actor)

    def _request_failure(
        self,
        actor: BaseIdentity,
        failure: Exception,
        failed_step: StepReference | None = None,
    ) -> None:
        with self._inspection_lock:
            self.failure = failure
            self.failed_step = failed_step
            self._transition(ContextState.FAILING, actor)

    def _complete_failure(self, actor: BaseIdentity) -> None:
        self._transition(ContextState.FAILED, actor)

    def _finish(self, actor: BaseIdentity) -> None:
        with self._inspection_lock:
            self.failure = None
            self.failed_step = None
            next_state = (
                ContextState.STOPPED
                if self.stop_requested
                else ContextState.FINISHED
            )
            self._transition(next_state, actor)

    def _load_executions(
        self,
        executions: tuple[ExecutionReport, ...],
    ) -> None:
        with self._inspection_lock:
            self._executions = executions

    def _load_artifacts(self, artifacts: dict[Artifact, ArtifactResult]) -> None:
        with self._inspection_lock:
            self._artifacts = dict(artifacts)

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
                executions=self._executions,
                failure=self.failure,
                failed_step=self.failed_step,
            )

            # The execution-only forks can still point back to the caller's
            # mutable submission context. Once execution is over, retain only
            # the sealed submission views exposed by ContextRun. This keeps a
            # completed run self-contained without unnecessarily retaining the
            # engine's working contexts or their release targets.
            self.artifact_context._release_target = None
            if (
                self.settings is not None
                and self.settings.artifact_policy.release_entry_artifacts
            ):
                self._submitted_artifact_context._clear_entries()
            self.artifact_context = self._submitted_artifact_context
            self.config_context = self._submitted_config_context
            self.supervised_graphs = ()
            self._finalized = True
            self._published_state = self.status.state
            notifications = self._resolve_waiters()
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
        actor: BaseIdentity,
    ) -> None:
        with self._inspection_lock:
            self._apply_transition(next_state, actor)
            notifications = self._resolve_waiters()
        self._notify_waiters(*notifications)

    def _apply_transition(
        self,
        next_state: ContextState,
        actor: BaseIdentity,
    ) -> None:
        if next_state not in self._allowed_transitions[self.state]:
            raise ValueError(
                f"cannot transition context {self.context_id!r} "
                f"from {self.state.value!r} to {next_state.value!r}"
            )
        self.status.apply_transition(next_state=next_state, actor=actor)
        if not next_state.is_terminal:
            self._published_state = next_state

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

    def _validate(self) -> None:
        if not isinstance(self.artifact_context, ArtifactContext):
            raise TypeError("artifact_context must be an ArtifactContext instance")

        if not isinstance(self.config_context, ConfigContext):
            raise TypeError("config_context must be a ConfigContext instance")

        if self.artifact_context.graph is not self.config_context.graph:
            raise ValueError(
                "ArtifactContext and ConfigContext must belong to the same graph"
            )

        self.graph.compiled_graph

        if not self.config_context.validate():
            raise ValueError("some required operator configs are not set")

        if not self.artifact_context.validate():
            raise ValueError("some entry artifacts are not set")
