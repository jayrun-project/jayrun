from __future__ import annotations

import math
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...persistence import DatabaseReader
    from ..progress_history import _TimingScope
    from .._history import _ContextCapture

from ...core.artifact.base import Artifact
from ...core.artifact.context import ArtifactContext
from ...core.config.context import ConfigContext
from ...core.context.runtime_data import Data
from ...core.graph.graph_definition import GraphDefinition
from ...core.graph.inspection.registry import GraphIdentity
from ..artifact.result import ArtifactResult
from ..base.runtime_module import RuntimeModule
from ..context.context_outcome import ContextOutcome
from ..context.step_reference import StepReference
from ..context_run import ContextRun
from ..interfaces.services.accesses import ContextAccess, RuntimeAccess
from ..interfaces.services.control import ContextControlService
from ..interfaces.services.context import ContextService
from ..interfaces.context_record import ContextRecord
from ..interfaces.services.storage import ContextRecordRepository
from ..messages.capability import _RuntimeCapability
from ..limits import OwnershipCapacityError, ContextHistoryLimitError
from ..history_budget import _HistoryBudget
from ..messages.commands.pause_context import PauseContextCommand
from ..messages.commands.stop_context import StopContextCommand
from ..messages.commands.abort_context import AbortContextCommand
from ..messages.commands.transfer_context import TransferContextCommand
from ..messages.commands.resume_context import ResumeContextCommand
from ..messages.commands.apply_snapshot import ApplySnapshotCommand, _SnapshotRejectedError
from ..messages.commands.shutdown_runtime import ShutdownRuntimeCommand
from ..messages.events.context_registered import ContextRegisteredEvent
from ..messages.events.runtime_idle import RuntimeIdleEvent
from ..messages.origin import CommandOrigin
from ..observation import (
    ContextControlRequested,
    ContextObserver,
    ContextStateChanged,
    ContextStopRequested,
    ContextTransferred,
    ContextValueStored,
)
from ..pressure import PressureSnapshot
from ..progress import ProgressSnapshot, _ProgressUpdate
from ..recorders.context.recorder import ContextRecorder
from ..recorders.context.report import ContextReport
from ..recorders.execution.records import (
    ExecutionReport,
    FailureRecord,
    LogRecord,
    MetricRecord,
    TimerRecord,
)
from ..resource.placement_request import PlacementRequest
from ..settings.combined_context import CombinedContextSettings
from ..settings.context import ContextSettings
from ..settings.engine import FailureMode, RoutingMode
from ..snapshot import ContextSnapshot
from ..terminal_history import TerminalCursor, TerminalHistoryPage, _TerminalHistory
from ..submission import (
    _NormalizedSubmission,
    _SupervisionScope,
    _normalize_submission,
)
from .context_id_generator import ContextIdGenerator
from .context_instance import ContextInstance
from .context_state import ContextRequest, ContextState
from .context_status import (
    ControlRequested,
    IterationStarted,
    EngineChanged,
    StateTransition,
    StopRequested,
)


class RuntimeRegistry(RuntimeModule):
    _REMOTE_PRESSURE_LIMIT = 256

    def initialize(self) -> None:
        self._closed = False
        self._shutdown_requested = False
        self._shutdown_forced = False
        self._lifecycle_lock = threading.RLock()
        self._contexts_lock = threading.RLock()
        self._remote_pressure_lock = threading.Lock()
        self._remote_pressures: OrderedDict[str, PressureSnapshot] = OrderedDict()
        self._contexts: dict[int, ContextInstance] = {}
        self._retired_contexts: dict[int, tuple[int, _GraphScope]] = {}
        self._ownership_slots: set[int] = set()
        self._ownership_pending: dict[int, int] = {}
        self._context_services: dict[int, ContextService] = {}
        self._context_capabilities: dict[int, _RuntimeCapability] = {}
        self._runtime_events: dict[int, ContextObserver] = {}
        self._context_runs: dict[
            tuple[int, _RuntimeCapability],
            ContextRun,
        ] = {}
        self._placement_lock = threading.RLock()
        self._placement_requests: dict[
            int,
            dict[PlacementRequest, None],
        ] = {}
        self._context_id_generator = ContextIdGenerator()
        settings = self._engine_runtime.engine_settings
        self._history_readers: dict[int, DatabaseReader] = {}
        self._terminal_history = _TerminalHistory(
            self._engine_runtime.engine_id, settings.terminal_history_limit,
            settings.terminal_history_max_bytes,
        )

    def register(
        self,
        submission: _NormalizedSubmission,
        supervises: _SupervisionScope,
        capability: _RuntimeCapability,
        settings: CombinedContextSettings,
        controller: bool = False,
        context_id: int | None = None,
        history_capture: _ContextCapture | None = None,
        timing_key: _TimingScope = None,
        history_reader: DatabaseReader | None = None,
    ) -> ContextRun:
        with self._lifecycle_lock:
            if self._shutdown_requested:
                raise RuntimeError("runtime is shutting down")
            return self._register(
                submission=submission,
                supervises=supervises,
                capability=capability,
                settings=settings,
                controller=controller,
                context_id=context_id,
                history_capture=history_capture,
                timing_key=timing_key,
                history_reader=history_reader,
            )

    def _register(
        self,
        submission: _NormalizedSubmission,
        supervises: _SupervisionScope,
        capability: _RuntimeCapability,
        settings: CombinedContextSettings,
        controller: bool = False,
        context_id: int | None = None,
        history_capture: _ContextCapture | None = None,
        timing_key: _TimingScope = None,
        history_reader: DatabaseReader | None = None,
    ) -> ContextRun:
        if self._closed:
            raise RuntimeError("runtime registry is closed")
        if context_id is None:
            context_id = self._context_id_generator.generate()
            while (
                self.find_context(context_id) is not None
                or context_id in self._retired_contexts
            ):
                context_id = self._context_id_generator.generate()
        else:
            self._validate_context_id(context_id)
            if (
                self.find_context(context_id) is not None
                or context_id in self._retired_contexts
            ):
                raise ValueError(f"context {context_id!r} is already registered")
        progress_profile = self._engine_runtime.progress_history.profile_for(
            timing_key,
            len(submission.graph._compiled_graph.steps),
        )
        context = ContextInstance(
            context_id=context_id,
            submission=submission,
            supervises=supervises,
            settings=settings,
            progress_profile=progress_profile,
            lifecycle_reporter=self._publish_lifecycle_entry,
            engine_id=self._engine_runtime.engine_id,
            local_engine_id=self._engine_runtime.engine_id,
            controller=controller,
            history_limit=self._engine_runtime.engine_settings.context_history_admission_limit,
            history_capture=history_capture,
            timing_key=timing_key,
        )
        if history_capture is not None:
            history_capture.claim()
        service = ContextService(
            runtime_messenger=self._engine_runtime.messenger,
            records=context._record_repository,
        )
        with self._contexts_lock:
            self._contexts[context_id] = context
            self._context_services[context_id] = service
        context_capability: _RuntimeCapability | None = None
        try:
            self._publish_initial_state(context)
            valid = context._validate_submission(self.origin)
            if valid:
                context_capability = (
                    self._engine_runtime.messenger.register_context(
                        context_id=context_id,
                        graph_scope=submission.graph_scope,
                        supervised_graphs=supervises,
                        controller=controller,
                    )
                )
                with self._contexts_lock:
                    self._context_capabilities[context_id] = context_capability
                    if history_reader is not None:
                        self._history_readers[context_id] = history_reader
                run = self.context_run(context_id, capability)
                if not context.is_supervising:
                    if (
                        self._engine_runtime.engine_settings.routing_mode
                        is RoutingMode.CONTROLLED
                    ):
                        context._await_routing(self.origin)
                    else:
                        context._queue(self.origin)
                        self._submit_context_registration(context)
                else:
                    self._submit_context_registration(context)
            else:
                run = self.context_run(context_id, capability)
                self._finalize_context(context_id)
                self._decide_on_failure(context.failure)
        except BaseException:
            self._rollback_registration(context_id, context_capability)
            raise

        return run

    def request_shutdown(
        self,
        forced: bool,
        origin: CommandOrigin,
        emit_idle: bool = True,
    ) -> None:
        if not isinstance(forced, bool):
            raise TypeError("forced must be a bool")
        if not isinstance(emit_idle, bool):
            raise TypeError("emit_idle must be a bool")
        with self._lifecycle_lock:
            self._request_shutdown(forced, origin, emit_idle)

    def _request_shutdown(
        self,
        forced: bool,
        origin: CommandOrigin,
        emit_idle: bool = True,
    ) -> None:
        self._shutdown_requested = True
        self._shutdown_forced = self._shutdown_forced or forced

        # Ordinary work drains first so a local controller can keep transporting
        # remote requests and snapshots. Authority contexts are stopped after
        # every ordinary context has finalized. Forced shutdown aborts both
        # groups immediately.
        for context_id, context in self._context_items():
            if not forced and context.is_supervising:
                continue
            self._request_context_shutdown(
                context_id,
                context,
                forced=forced,
                origin=origin,
            )

        if not forced:
            self.finish_authority_shutdown_if_ready(origin)

        if emit_idle:
            self._emit_idle_if_needed()

    def finish_authority_shutdown_if_ready(
        self,
        origin: CommandOrigin,
    ) -> None:
        """Stop authority contexts once all ordinary work is finalized."""
        if (
            not self._shutdown_requested
            or self._shutdown_forced
            or any(
                not context.is_supervising and not context.finalized
                for _, context in self._context_items()
            )
        ):
            return
        for context_id, context in self._context_items():
            if not context.is_supervising:
                continue
            self._request_context_shutdown(
                context_id,
                context,
                forced=False,
                origin=origin,
            )

    def _request_context_shutdown(
        self,
        context_id: int,
        context: ContextInstance,
        *,
        forced: bool,
        origin: CommandOrigin,
    ) -> None:
        if context.is_terminal:
            if context.finalized:
                return
            if context.is_local or forced:
                self._finalize_context(context_id)
            return

        if not context.is_local:
            if forced:
                self.transfer_context(
                    context_id,
                    self._engine_runtime.engine_id,
                    origin,
                    reclaim=True,
                )
                context = self.find_context(context_id)
                if context is None or not context.is_local:
                    return
            else:
                self._publish_control_request(
                    context,
                    ContextRequest.STOP,
                    None,
                    origin,
                )
                return

        if forced:
            if not context.is_draining:
                context._request_abort(origin)
        elif context.state in {
            ContextState.VALIDATED,
            ContextState.ROUTING,
            ContextState.QUEUED,
            ContextState.RUNNING,
            ContextState.PLACEMENT_WAITING,
            ContextState.PAUSED,
        }:
            was_paused = context.is_paused
            context._request_stop(origin)
            if was_paused:
                context._resume(
                    origin,
                    placement_waiting=bool(
                        self._pending_placements_for(context_id)
                    ),
                )

        if context.is_supervising:
            # Set the cooperative lifetime boundary before waking an
            # event-driven authority blocked on its queue.
            self._engine_runtime.observations.close_owner(context_id)

        if context.is_aborting:
            self._discard_placements(context_id)
            self._engine_runtime.resource_manager.cancel_context_placements(
                context_id
            )

        if context.is_terminal:
            self._finalize_context(context_id)

    def get_context(self, context_id: int) -> ContextInstance:
        self._validate_context_id(context_id)
        with self._contexts_lock:
            try:
                return self._contexts[context_id]
            except KeyError:
                raise KeyError(f"unknown context_id: {context_id!r}") from None

    def find_context(self, context_id: int) -> ContextInstance | None:
        self._validate_context_id(context_id)
        with self._contexts_lock:
            return self._contexts.get(context_id)

    def context_ids(self) -> tuple[int, ...]:
        return tuple(context_id for context_id, _ in self._context_items())

    def terminal_history(self, capability: _RuntimeCapability,
                         after: TerminalCursor | None, limit: int) -> TerminalHistoryPage:
        # A cursor is position, never permission. Recheck the live grant on every read.
        self._engine_runtime.messenger.authorize_terminal_history(capability)
        return self._terminal_history.read(after, limit)

    def create_context_recorder(self) -> ContextRecorder:
        return ContextRecorder._for_policy(self._engine_runtime.instrumentation)

    def provide_runtime_access(self, context_id: int) -> RuntimeAccess:
        context = self.get_context(context_id)
        capability = self._context_capabilities[context_id]
        return RuntimeAccess(
            name=self._engine_runtime.name,
            engine_id=self._engine_runtime.engine_id,
            alive=lambda: context.runtime_alive,
            history=lambda: self._runtime_history(context_id, capability),
            contexts=lambda: self.context_runs(capability),
            active_contexts=lambda: self.context_runs(
                capability,
                active_only=True,
            ),
            paused_contexts=lambda: self.context_runs(
                capability,
                state=ContextState.PAUSED,
            ),
            events=lambda: self._runtime_events_for(context_id),
            pressure=lambda: self.pressure(capability),
            pressures=lambda: self.pressures(capability),
            terminal_history=lambda after, limit: self.terminal_history(capability, after, limit),
            apply=lambda snapshot: self._engine_runtime.messenger.submit_control(
                ApplySnapshotCommand(snapshot=snapshot),
                capability,
            ),
            submit=lambda graph_key, artifacts, configs, **options: (
                self.submit_from_context(
                    context_id,
                    graph_key,
                    artifacts,
                    configs,
                    **options,
                )
            ),
            shutdown=lambda forced: self._engine_runtime.messenger.submit(
                ShutdownRuntimeCommand(forced=forced),
                capability,
            ),
        )

    def _runtime_history(self, context_id: int, capability: _RuntimeCapability) -> DatabaseReader | None:
        def authorized() -> None:
            self._engine_runtime.messenger.authorize_controller(capability)
            context = self.find_context(context_id)
            if context is None or not context.runtime_alive:
                raise PermissionError("controller historical access has ended")

        authorized()
        with self._contexts_lock:
            reader = self._history_readers.get(context_id)
        # No implicit grant from engine-wide live control or a matching graph ID.
        return None if reader is None else reader._with_guard(authorized)

    def _runtime_events_for(self, context_id: int) -> ContextObserver:
        context = self.get_context(context_id)
        if not context.is_supervising:
            raise PermissionError("runtime events require supervising authority")
        with self._contexts_lock:
            observer = self._runtime_events.get(context_id)
            if observer is None:
                observer = self._engine_runtime.observations.observer(
                    owner_context_id=context_id,
                    graph_scope=context.supervised_graphs,
                )
                self._runtime_events[context_id] = observer
            return observer

    def provide_context_access(self, context_id: int) -> ContextAccess:
        service = self._get_context_service(context_id)
        capability = self._context_capabilities[context_id]
        generation = self.get_context(context_id).generation
        control_service = ContextControlService(
            runtime_messenger=self._engine_runtime.messenger,
            capability=capability,
            context_id=context_id,
        )
        return ContextAccess(
            pause=control_service.pause,
            abort=control_service.abort,
            stop=control_service.stop,
            records=service.records,
            record=lambda record, origin: service.record(
                record,
                capability,
                origin,
                generation,
            ),
        )

    def context_run(
        self,
        context_id: int,
        capability: _RuntimeCapability,
    ) -> ContextRun:
        """Return the stable run authorized for one capability and context."""
        with self._contexts_lock:
            context = self.get_context(context_id)
            self._engine_runtime.messenger.authorize_context_access(
                capability,
                context_id,
            )
            key = (context_id, capability)
            run = self._context_runs.get(key)
            if run is None:
                run = ContextRun(
                    context=context,
                    context_service=self._context_services[context_id],
                    control_service=ContextControlService(
                        runtime_messenger=self._engine_runtime.messenger,
                        capability=capability,
                        context_id=context_id,
                    ),
                )
                self._context_runs[key] = run
            return run

    def submit_from_context(
        self,
        caller_context_id: int,
        graph_key: GraphIdentity,
        artifacts: ArtifactContext | None = None,
        configs: ConfigContext | None = None,
        *,
        context_settings: ContextSettings | None = None,
    ) -> ContextRun:
        if getattr(self._engine_runtime, "history_recorder", None) is not None:
            return self._submit_with_history(caller_context_id, graph_key, artifacts, configs,
                                             context_settings=context_settings)
        with self._lifecycle_lock:
            if self._shutdown_requested:
                raise RuntimeError("runtime is shutting down")
            return self._submit_from_context(
                caller_context_id,
                graph_key,
                artifacts,
                configs,
                context_settings=context_settings,
            )

    def _submit_with_history(
        self, caller_context_id: int, graph_key: GraphIdentity,
        artifacts: ArtifactContext | None, configs: ConfigContext | None,
        *, context_settings: ContextSettings | None,
    ) -> ContextRun:
        runtime = self._engine_runtime
        with self._lifecycle_lock:
            if self._shutdown_requested:
                raise RuntimeError("runtime is shutting down")
            caller = self.get_context(caller_context_id)
            capability = self._context_capabilities[caller_context_id]
            runtime.messenger.authorize_controller(capability)
            if not caller.is_controller:
                raise PermissionError("runtime submission requires a Controller")
            if runtime.graph_registry is None:
                raise RuntimeError("runtime submission requires a graph registry")
        submission = _normalize_submission(graph=graph_key, artifacts=artifacts, configs=configs,
                                            graph_registry=runtime.graph_registry)
        settings = CombinedContextSettings.from_settings(runtime.engine_settings, context_settings,
                                                        submission.graph._specification.artifacts)
        timing_key = runtime.progress_history.timing_key(submission, settings)
        capture = runtime.history_recorder.prepare(submission, settings, context_settings,
                                                  source="controller_submission")
        try:
            with self._lifecycle_lock:
                if self._shutdown_requested:
                    raise RuntimeError("runtime is shutting down")
                # No capability is gained by crossing the capture boundary.
                runtime.messenger.authorize_controller(capability)
                if self._context_capabilities.get(caller_context_id) is not capability:
                    raise PermissionError("controller authority ended during diagnostic capture")
                if capture is not None:
                    capture.check_binding(submission.graph)
                runtime.gateway.reset_idle_state()
                runtime.gateway.notify_active_state()
                submission.graph._seal()
                try:
                    run = self.register(submission, (), capability, settings, history_capture=capture, timing_key=timing_key)
                except BaseException as failure:
                    runtime.gateway.notify_failed_state(failure)
                    raise
                if artifacts is not None:
                    artifacts._clear_entries(submission.graph._specification.artifacts)
                return run
        finally:
            if capture is not None:
                capture.discard()

    def _submit_from_context(
        self,
        caller_context_id: int,
        graph_key: GraphIdentity,
        artifacts: ArtifactContext | None = None,
        configs: ConfigContext | None = None,
        *,
        context_settings: ContextSettings | None = None,
    ) -> ContextRun:
        """Register ordinary graph-key work authorized by a controller.

        Runtime submission deliberately cannot create authority-bearing
        contexts. It follows this engine's routing mode exactly like
        :meth:`jayrun.Engine.submit`.
        """
        caller = self.get_context(caller_context_id)
        capability = self._context_capabilities[caller_context_id]
        self._engine_runtime.messenger.authorize_controller(capability)
        if not caller.is_controller:
            raise PermissionError("runtime submission requires a Controller")
        graph_registry = self._engine_runtime.graph_registry
        if graph_registry is None:
            raise RuntimeError("runtime submission requires a graph registry")
        submission = _normalize_submission(
            graph=graph_key,
            artifacts=artifacts,
            configs=configs,
            graph_registry=graph_registry,
        )
        settings = CombinedContextSettings.from_settings(
            engine_settings=self._engine_runtime.engine_settings,
            context_settings=context_settings,
            artifact_registry=submission.graph._specification.artifacts,
        )
        self._engine_runtime.gateway.reset_idle_state()
        self._engine_runtime.gateway.notify_active_state()
        submission.graph._seal()
        try:
            run = self.register(
                submission=submission,
                supervises=(),
                controller=False,
                capability=capability,
                settings=settings,
                timing_key=self._engine_runtime.progress_history.timing_key(submission, settings),
            )
        except BaseException as failure:
            self._engine_runtime.gateway.notify_failed_state(failure)
            raise
        if artifacts is not None:
            artifacts._clear_entries(submission.graph._specification.artifacts)
        return run

    def context_runs(
        self,
        capability: _RuntimeCapability,
        *,
        active_only: bool = False,
        state: ContextState | None = None,
    ) -> tuple[ContextRun, ...]:
        """Return live runs visible to ``capability`` in submission order."""
        if not isinstance(active_only, bool):
            raise TypeError("active_only must be a bool")
        if state is not None and not isinstance(state, ContextState):
            raise TypeError("state must be a ContextState instance or None")
        if active_only and state is not None:
            raise ValueError("active_only and state cannot be combined")

        context_ids = self.context_ids()
        if not context_ids:
            return ()
        visible_ids = self._engine_runtime.messenger.visible_context_ids(
            capability,
            context_ids,
        )
        contexts = tuple(
            context
            for context_id in visible_ids
            if (context := self.find_context(context_id)) is not None
        )
        if active_only:
            contexts = tuple(context for context in contexts if context.is_active)
        elif state is not None:
            contexts = tuple(context for context in contexts if context.state is state)

        runs: list[ContextRun] = []
        for context in contexts:
            try:
                runs.append(
                    self.context_run(
                        context.context_id,
                        capability,
                    )
                )
            except KeyError:
                continue
        return tuple(runs)

    def start_context(self, context_id: int, origin: CommandOrigin) -> None:
        context = self.find_context(context_id)
        if (
            context is None
            or context.is_terminal
            or not context.is_local
        ):
            return
        # A reclaimed/imported queued checkpoint can already carry Stop. Do not
        # restart an iteration merely because ownership returned to this engine.
        if context.stop_requested:
            context._finish(origin)
            self._finalize_context(context_id)
            return
        context._start(origin)

    def complete_iteration(
        self,
        context_id: int,
        origin: CommandOrigin,
        executions: tuple[ExecutionReport, ...],
        checkpoint: dict[Artifact, Data[object]],
    ) -> bool:
        context = self.get_context(context_id)
        context._complete_iteration(executions, checkpoint)
        settings = context.settings
        if settings is None:
            raise RuntimeError("context settings are unavailable")
        if settings.max_iterations is None:
            step_count = len(context.graph._compiled_graph.steps)
            scope = self._learning_scope(context)
            profile = self._engine_runtime.progress_history.commit_iteration(
                scope,
                executions,
                step_count,
                context.iteration_count,
            )
            if scope is not None:
                context._replace_progress_profile(profile)
            context._mark_history_iteration(context.iteration_count)
        if context.can_reiterate and context._history_budget.exhausted:
            self.fail_context(context_id, origin, context._history_budget.error())
            return False
        return context._reiterate(origin)

    def stop_context(self, context_id: int, origin: CommandOrigin) -> None:
        context = self.find_context(context_id)
        if (
            context is None
            or context.is_terminal
            or context.is_draining
            or context.stop_requested
        ):
            return
        if not context.is_local:
            self._publish_control_request(
                context,
                ContextRequest.STOP,
                None,
                origin,
            )
            return
        if context.state not in {
            ContextState.VALIDATED,
            ContextState.ROUTING,
            ContextState.QUEUED,
            ContextState.RUNNING,
            ContextState.PLACEMENT_WAITING,
            ContextState.PAUSED,
        }:
            return
        was_paused = context.is_paused
        context._request_stop(origin)
        if was_paused:
            context._resume(
                origin,
                placement_waiting=bool(
                    self._pending_placements_for(context_id)
                ),
            )
        if context.is_terminal:
            self._finalize_context(context_id)

    def pause_context(
        self,
        context_id: int,
        origin: CommandOrigin,
        duration: float | None = None,
    ) -> None:
        self._validate_duration(duration)
        context = self.find_context(context_id)
        if context is None or context.is_terminal or context.is_draining:
            return
        if not context.is_local:
            self._publish_control_request(
                context,
                ContextRequest.PAUSE,
                duration,
                origin,
            )
            return
        if context.is_paused:
            pass
        elif context.state in {
            ContextState.RUNNING,
            ContextState.PLACEMENT_WAITING,
        }:
            context._pause(origin)
        else:
            return

        if duration is not None:
            self._engine_runtime.messenger.submit_after(
                ResumeContextCommand(
                    context_id=context_id,
                ),
                self.capability,
                delay=duration,
            )

    def resume_context(self, context_id: int, origin: CommandOrigin) -> None:
        context = self.find_context(context_id)
        if context is None or not context.is_paused:
            return
        if not context.is_local:
            self._publish_control_request(
                context,
                ContextRequest.RESUME,
                None,
                origin,
            )
            return
        context._resume(
            origin,
            placement_waiting=bool(self._pending_placements_for(context_id)),
        )

    def record_placement_requests(
        self,
        requests: tuple[PlacementRequest, ...],
    ) -> None:
        if not isinstance(requests, tuple):
            raise TypeError("requests must be a tuple")
        if any(not isinstance(request, PlacementRequest) for request in requests):
            raise TypeError("requests must contain PlacementRequest instances")
        if not requests:
            return
        context_ids = {request.context_id for request in requests}
        if len(context_ids) != 1:
            raise ValueError("placement requests must belong to one context")
        context = self.get_context(next(iter(context_ids)))
        self._engine_runtime.context_scheduler.record_placement_requests(
            graph=context.graph,
            requests=requests,
        )

    def register_placement_request(
        self,
        request: PlacementRequest,
        origin: CommandOrigin,
    ) -> None:
        if not isinstance(request, PlacementRequest):
            raise TypeError("request must be a PlacementRequest instance")
        context = self.get_context(request.context_id)
        if context.is_terminal or context.is_draining:
            raise RuntimeError("terminal context cannot wait for placement")
        with self._placement_lock:
            requests = self._placement_requests.setdefault(request.context_id, {})
            requests.setdefault(request, None)
        if not context.is_paused:
            context._wait_for_placement(origin)
        self._engine_runtime.context_scheduler.record_placement_requests(
            graph=context.graph,
            requests=(request,),
        )

    def resolve_placement_requests(
        self,
        requests: tuple[PlacementRequest, ...],
        origin: CommandOrigin,
    ) -> tuple[PlacementRequest, ...]:
        return self._remove_placement_requests(requests, origin)

    def revoke_placement_requests(
        self,
        requests: tuple[PlacementRequest, ...],
        origin: CommandOrigin,
    ) -> tuple[PlacementRequest, ...]:
        return self._remove_placement_requests(requests, origin)

    def _remove_placement_requests(
        self,
        requests: tuple[PlacementRequest, ...],
        origin: CommandOrigin,
    ) -> tuple[PlacementRequest, ...]:
        resolved: list[PlacementRequest] = []
        for request in requests:
            context = self.find_context(request.context_id)
            if context is None or context.is_terminal or context.is_draining:
                continue
            with self._placement_lock:
                context_requests = self._placement_requests.get(request.context_id)
                if context_requests is None or request not in context_requests:
                    continue
                del context_requests[request]
                last_request = not context_requests
                if last_request:
                    del self._placement_requests[request.context_id]
            if last_request and not context.is_paused:
                context._resolve_placement(origin)
            resolved.append(request)
        return tuple(resolved)

    @property
    def pending_placement_requests(self) -> tuple[PlacementRequest, ...]:
        with self._placement_lock:
            return tuple(
                request
                for requests in self._placement_requests.values()
                for request in requests
            )

    def admit_history_command(self, message: object) -> None:
        """Bound caller-driven history even while a context is paused/nonlocal.

        This counts admission, not successful execution, so rejected queue attempts
        may conservatively use budget. Local Stop/Abort always remain available.
        """
        if isinstance(message, ApplySnapshotCommand):
            if not isinstance(message.snapshot, ContextSnapshot) or message.snapshot.request is None:
                return
            context_id = message.snapshot.context_id
        elif isinstance(message, (PauseContextCommand, ResumeContextCommand,
                                  TransferContextCommand, StopContextCommand, AbortContextCommand)):
            context_id = message.context_id
        else:
            return
        context = self.find_context(context_id)
        if context is None or context.is_terminal or context.is_draining:
            return
        if context.is_local and (isinstance(message, (StopContextCommand, AbortContextCommand))
                or (isinstance(message, ApplySnapshotCommand) and message.snapshot.request in {ContextRequest.STOP, ContextRequest.ABORT})):
            return
        context._history_budget.consume()

    def reserve_ownership(self, message: object) -> int | None:
        """Reserve one unique-ID slot for an authenticated, about-to-queue command.

        Per-message reference counts let independent duplicate submissions release
        only their own pending reservation. No graph, payload or capability is stored.
        """
        with self._lifecycle_lock:
            context_id = None
            if isinstance(message, TransferContextCommand):
                context = self.find_context(message.context_id)
                if (context is not None and not context.is_terminal and not context.is_supervising
                        and not context.stop_requested and message.engine_id != context.engine_id
                        and (not context.is_local or context.is_queued or context.is_routing)):
                    context_id = message.context_id
            elif (isinstance(message, ApplySnapshotCommand)
                  and isinstance(message.snapshot, ContextSnapshot)
                  and message.snapshot.request is None):
                snapshot = message.snapshot
                context = self.find_context(snapshot.context_id)
                retired = self._retired_contexts.get(snapshot.context_id)
                if retired is not None and snapshot.generation <= retired[0]:
                    return None
                if context is not None and (snapshot.generation, snapshot.revision) <= (context.generation, context._snapshot_revision):
                    return None
                context_id = snapshot.context_id
            if context_id is None or context_id in self._ownership_slots:
                return None
            self._check_ownership_capacity(context_id)
            self._ownership_pending[context_id] = self._ownership_pending.get(context_id, 0) + 1
            return context_id

    def release_ownership_reservation(self, context_id: int | None) -> None:
        if context_id is None:
            return
        with self._lifecycle_lock:
            count = self._ownership_pending.get(context_id, 0)
            if count <= 1:
                self._ownership_pending.pop(context_id, None)
            else:
                self._ownership_pending[context_id] = count - 1

    def _check_ownership_capacity(self, context_id: int) -> None:
        if context_id in self._ownership_slots or context_id in self._ownership_pending:
            return
        limit = self._engine_runtime.engine_settings.remote_context_id_limit
        if limit is not None and len(self._ownership_slots) + sum(key not in self._ownership_slots for key in self._ownership_pending) >= limit:
            raise OwnershipCapacityError(
                f"remote ownership capacity {limit} exhausted for this engine incarnation; safety fences cannot be evicted"
            )

    def transfer_context(self, context_id: int, engine_id: str, origin: CommandOrigin,
                         *, reclaim: bool = False) -> None:
        with self._lifecycle_lock:
            self._transfer_context(context_id, engine_id, origin, reclaim=reclaim)

    def _transfer_context(
        self,
        context_id: int,
        engine_id: str,
        origin: CommandOrigin,
        *,
        reclaim: bool = False,
    ) -> None:
        if not isinstance(engine_id, str):
            raise TypeError("engine_id must be a string")
        if not engine_id.strip():
            raise ValueError("engine_id must not be empty")
        if engine_id.strip() == "self":
            raise ValueError(
                "engine_id must be an engine.engine_id value, not 'self'"
            )
        context = self.find_context(context_id)
        if (
            context is None
            or context.is_terminal
            or (context.is_draining and not reclaim)
        ):
            return
        if context.is_supervising:
            return
        if context.stop_requested and not reclaim:
            return

        if engine_id == context.engine_id:
            if context.is_local and context.is_routing:
                context._queue(origin)
                self._submit_context_registration(context)
            return

        if context.is_local and context.state not in {
            ContextState.ROUTING,
            ContextState.QUEUED,
        }:
            return
        if engine_id != self._engine_runtime.engine_id and (
            not isinstance(context.graph_scope, tuple)
            or not context.graph._has_complete_boundary_serializers
        ):
            return

        self._check_ownership_capacity(context_id)
        self._discard_placements(context_id)
        self._engine_runtime.resource_manager.cancel_context_placements(context_id)
        self._engine_runtime.context_scheduler.release_context(context_id)
        self._engine_runtime.context_manager.release_queued(context_id)
        previous_engine_id, _ = context._change_engine(engine_id, origin)
        self._ownership_slots.add(context_id)
        snapshot = context.snapshot
        self._engine_runtime.observations.publish(
            ContextTransferred(
                context_id=context_id,
                graph_key=self._graph_key(context),
                graph_version=context.graph.version,
                previous_engine_id=previous_engine_id,
                current_engine_id=engine_id,
                generation=context.generation,
                occurred_at=snapshot.updated_at,
                snapshot=snapshot,
            ),
            context.graph_scope,
        )
        if context.is_local:
            self._submit_context_registration(context)

    def validate_snapshot(self, snapshot: ContextSnapshot | PressureSnapshot) -> ContextSnapshot | PressureSnapshot:
        """Validate portable structure and graph-bound payload references."""
        if isinstance(snapshot, PressureSnapshot):
            self._validate_pressure(snapshot)
            return snapshot
        if not isinstance(snapshot, ContextSnapshot):
            raise TypeError("snapshot must be a ContextSnapshot or PressureSnapshot instance")
        existing = self.find_context(snapshot.context_id)
        retired = self._retired_contexts.get(snapshot.context_id)
        if (
            self._engine_runtime.coordinator.is_stopping
            and snapshot.request is not None
        ):
            raise _SnapshotRejectedError(
                "control requests cannot be applied while the runtime is shutting down"
            )
        if (
            self._engine_runtime.coordinator.is_stopping
            and existing is None
            and (
                retired is None
                or snapshot.generation > retired[0]
            )
        ):
            raise _SnapshotRejectedError(
                "a new context cannot be applied while the runtime is shutting down"
            )
        if (snapshot.request is None and existing is None and retired is None
                and snapshot.generation == 0
                and snapshot.engine_id == self._engine_runtime.engine_id):
            # Generation zero belongs to this incarnation's local submission.
            # If it is no longer live, importing its old queued image could run
            # it a second time. A new assignment requires a generation advance;
            # no unbounded set of every finished local ID is needed.
            raise _SnapshotRejectedError(
                "an untracked own-incarnation generation-zero snapshot cannot be restored"
            )
        if snapshot.request is not None:
            self._validate_snapshot_history(snapshot)
            if existing is not None:
                self._validate_snapshot_identity(snapshot, existing)
            return snapshot

        if (
            snapshot.engine_id == self._engine_runtime.engine_id
            and not snapshot.finalized
            and snapshot.state is not ContextState.QUEUED
            and (existing is None or not existing.is_local)
        ):
            raise ValueError("a snapshot assigned to this engine must be queued")

        graph, _, _, _ = self._decode_snapshot(snapshot)
        if existing is None:
            if (
                snapshot.engine_id == self._engine_runtime.engine_id
                and not snapshot.finalized
                and snapshot.state is not ContextState.QUEUED
            ):
                raise ValueError(
                    "a snapshot assigned to this engine must be queued"
                )
        else:
            self._validate_snapshot_against_context(snapshot, existing)
        if graph.version != snapshot.graph_version:
            raise ValueError("snapshot graph version is inconsistent")
        return snapshot

    def apply_snapshot(self, snapshot: ContextSnapshot | PressureSnapshot, origin: CommandOrigin,
                       *, history_capture: _ContextCapture | None = None) -> None:
        with self._lifecycle_lock:
            if isinstance(snapshot, ContextSnapshot):
                self._apply_snapshot(snapshot, origin, history_capture=history_capture)
            elif isinstance(snapshot, PressureSnapshot):
                self._validate_pressure(snapshot)
                self._record_pressure(snapshot)
            else:
                raise TypeError("snapshot must be a ContextSnapshot or PressureSnapshot instance")

    def _apply_snapshot(
        self,
        snapshot: ContextSnapshot,
        origin: CommandOrigin,
        *, history_capture: _ContextCapture | None = None,
    ) -> None:
        """Apply a validated request or committed remote context snapshot."""
        if not isinstance(snapshot, ContextSnapshot):
            raise TypeError("snapshot must be a ContextSnapshot instance")
        context = self.find_context(snapshot.context_id)
        if context is None and self._engine_runtime.coordinator.is_stopping:
            return
        if snapshot.request is not None:
            if context is None:
                return
            self._validate_snapshot_identity(snapshot, context)
            if not context._accept_remote_request(snapshot):
                return
            if snapshot.request is ContextRequest.PAUSE:
                self.pause_context(
                    snapshot.context_id,
                    origin,
                    duration=snapshot.request_duration,
                )
            elif snapshot.request is ContextRequest.RESUME:
                self.resume_context(snapshot.context_id, origin)
            elif snapshot.request is ContextRequest.STOP:
                self.stop_context(snapshot.context_id, origin)
            elif snapshot.request is ContextRequest.ABORT:
                self.abort_context(snapshot.context_id, origin)
            return

        retired = self._retired_contexts.get(snapshot.context_id)
        if (context is None and retired is None and snapshot.generation == 0
                and snapshot.engine_id == self._engine_runtime.engine_id):
            return  # The original local owner may have finalized since admission.
        graph, submission, settings, artifacts = self._decode_snapshot(snapshot)
        if retired is not None:
            retired_generation, retired_graph_scope = retired
            if snapshot.generation <= retired_generation:
                return
            snapshot_graph_scope = (
                snapshot.graph_key,
                snapshot.graph_version,
            )
            if snapshot_graph_scope != retired_graph_scope:
                raise ValueError(
                    "a newer context generation cannot change its graph identity"
                )
        if context is not None and (snapshot.generation, snapshot.revision) <= (context.generation, context._snapshot_revision):
            return
        self._check_ownership_capacity(snapshot.context_id)
        created = context is None
        capability: _RuntimeCapability | None = None
        if created:
            if (
                snapshot.engine_id == self._engine_runtime.engine_id
                and snapshot.state is not ContextState.QUEUED
            ):
                raise ValueError(
                    "a snapshot assigned to this engine must be queued"
                )
            timing_key = self._engine_runtime.progress_history.timing_key(submission, settings)
            profile = self._engine_runtime.progress_history.profile_for(
                timing_key,
                len(graph._compiled_graph.steps),
            )
            context = ContextInstance(
                context_id=snapshot.context_id,
                submission=submission,
                supervises=(),
                settings=settings,
                progress_profile=profile,
                lifecycle_reporter=self._publish_lifecycle_entry,
                engine_id=snapshot.engine_id,
                local_engine_id=self._engine_runtime.engine_id,
                history_limit=self._engine_runtime.engine_settings.context_history_admission_limit,
                history_capture=history_capture if not snapshot.finalized else None,
                timing_key=timing_key,
            )
            service = ContextService(
                runtime_messenger=self._engine_runtime.messenger,
                records=context._record_repository,
            )
        else:
            self._validate_snapshot_against_context(snapshot, context)
            service = self._get_context_service(snapshot.context_id)

        previous_engine_id = context.engine_id
        previous_generation = context.generation
        previously_stopped = context.stop_requested
        checkpoint = dict(submission.artifacts.instances)
        configs = dict(submission.configs.instances)
        try:
            if created and history_capture is not None:
                history_capture.claim(generation=snapshot.generation)
            applied, previous_state, previous_record_sequence = context._apply_remote_snapshot(
                snapshot, checkpoint=checkpoint, configs=configs, artifacts=artifacts,
            )
        except BaseException:
            if created:
                if history_capture is not None:
                    history_capture.discard(force=True)
                service.close()
            raise
        if not applied:
            if created:
                if history_capture is not None:
                    history_capture.discard(force=True)
                service.close()
            return

        if created:
            try:
                capability = self._engine_runtime.messenger.register_context(
                    context_id=snapshot.context_id,
                    graph_scope=submission.graph_scope,
                    supervised_graphs=(),
                )
                with self._contexts_lock:
                    if snapshot.context_id in self._contexts:
                        raise ValueError(
                            f"context {snapshot.context_id!r} is already registered"
                        )
                    if snapshot.finalized and history_capture is not None:
                        # A new, already-final snapshot has no public run until
                        # this insertion. Register history before exposing it;
                        # failed capability/duplicate registration writes nothing.
                        with context._inspection_lock:
                            history_capture.handoff(context, snapshot.report)
                    self._contexts[snapshot.context_id] = context
                    self._context_services[snapshot.context_id] = service
                    self._context_capabilities[snapshot.context_id] = capability
                    self._retired_contexts.pop(snapshot.context_id, None)
            except BaseException:
                if capability is not None:
                    self._engine_runtime.messenger.unregister_context(
                        snapshot.context_id,
                        capability,
                    )
                if history_capture is not None:
                    history_capture.discard(force=True, gap=True)
                service.close()
                raise

        self._ownership_slots.add(snapshot.context_id)
        # A fresh unstarted assignment has no inherited timing samples.
        # Carried reports lack per-report lineage in the unchanged wire contract.
        context._timing_learning_generation = (
            snapshot.generation if context.is_local and snapshot.started_at is None
            and not snapshot.reports and snapshot.completed_iterations == 0 else None)
        self._learn_from_snapshot(context, snapshot)
        local_snapshot = context.snapshot
        if snapshot.stop_requested and not previously_stopped:
            entry = next(entry for entry in snapshot.history if isinstance(entry, StopRequested))
            self._publish_lifecycle_entry(context, entry)
        if created or previous_state is not snapshot.state:
            self._publish_synchronized_state(
                context,
                previous_state=None if created else previous_state,
                snapshot=local_snapshot,
            )
        if (
            previous_engine_id != context.engine_id
            or previous_generation != context.generation
        ):
            self._engine_runtime.observations.publish(
                ContextTransferred(
                    context_id=context.context_id,
                    graph_key=self._graph_key(context),
                    graph_version=context.graph.version,
                    previous_engine_id=previous_engine_id,
                    current_engine_id=context.engine_id,
                    generation=context.generation,
                    occurred_at=local_snapshot.updated_at,
                    snapshot=local_snapshot,
                ),
                context.graph_scope,
            )
        for record in snapshot.records:
            if record.sequence <= previous_record_sequence:
                continue
            record_index = record.sequence
            self._publish_stored_record(
                context,
                record,
                record_index,
                local_snapshot,
            )

        if snapshot.finalized:
            self._finalize_context(snapshot.context_id)
        else:
            self._engine_runtime.gateway.reset_idle_state()
            self._engine_runtime.gateway.notify_active_state()
            if context.is_local:
                self._submit_context_registration(context)

    def _decode_snapshot(
        self,
        snapshot: ContextSnapshot,
    ) -> tuple[
        GraphDefinition,
        _NormalizedSubmission,
        CombinedContextSettings,
        dict[Artifact, ArtifactResult],
    ]:
        graph = self._validate_snapshot_payload(snapshot)
        artifact_registry = graph._specification.artifacts
        config_registry = graph._specification.configs
        artifacts_by_id = {
            definition.artifact_id: artifact_registry.source_for(definition)
            for definition in artifact_registry.definitions
        }
        configs_by_id = {
            definition.config_id: config_registry.source_for(definition)
            for definition in config_registry.definitions
        }

        artifact_values: dict[Artifact, object] = {}
        for artifact_id, data in snapshot.artifact_context:
            artifact = artifacts_by_id[artifact_id]
            artifact_values[artifact] = self._decode_artifact_value(
                graph,
                artifact,
                data.value,
            )
        if snapshot.finalized:
            for artifact in graph._compiled_graph.entry_artifacts:
                artifact_values.setdefault(artifact, None)
        config_values = {
            configs_by_id[config_id]: data.value
            for config_id, data in snapshot.config_context
        }

        artifact_context = ArtifactContext()
        artifact_context.set(artifact_values)
        config_context = ConfigContext()
        config_context.set(config_values)
        graph_registry = self._engine_runtime.graph_registry
        if graph_registry is None:
            raise _SnapshotRejectedError("snapshot application requires a graph registry")
        submission = _normalize_submission(
            graph=(snapshot.graph_key, snapshot.graph_version),
            artifacts=artifact_context,
            configs=config_context,
            graph_registry=graph_registry,
        )
        if snapshot.finalized and not snapshot.artifact_context:
            submission.artifacts._instances.clear()
        settings = CombinedContextSettings.from_settings(
            engine_settings=self._engine_runtime.engine_settings,
            context_settings=snapshot.context_settings,
            artifact_registry=artifact_registry,
        )
        results: dict[Artifact, ArtifactResult] = {}
        for artifact_id, result in snapshot.artifacts:
            artifact = artifacts_by_id[artifact_id]
            results[artifact] = ArtifactResult(
                data=Data(
                    value=self._decode_artifact_value(
                        graph,
                        artifact,
                        result.value,
                    )
                ),
                history=result.history,
            )
        return graph, submission, settings, results

    def _validate_snapshot_payload(
        self,
        snapshot: ContextSnapshot,
    ) -> GraphDefinition:
        if snapshot.graph_key is None:
            raise ValueError("committed snapshots require a registered graph key")
        graph_registry = self._engine_runtime.graph_registry
        if graph_registry is None:
            raise _SnapshotRejectedError("snapshot application requires a graph registry")
        graph = graph_registry[(snapshot.graph_key, snapshot.graph_version)]
        if (
            not graph._has_complete_boundary_serializers
            or (
                bool(graph._serializer_bindings)
                and not snapshot.artifacts_serialized
            )
        ):
            raise ValueError(
                "committed remote snapshots require graph boundary serializers"
            )

        artifact_registry = graph._specification.artifacts
        config_registry = graph._specification.configs
        artifacts_by_id = {
            definition.artifact_id: artifact_registry.source_for(definition)
            for definition in artifact_registry.definitions
        }
        config_ids = {
            definition.config_id for definition in config_registry.definitions
        }
        self._validate_snapshot_pairs(
            snapshot.artifact_context,
            "artifact_context",
            artifacts_by_id,
            Data,
        )
        checkpoint_ids = {
            artifact_id for artifact_id, _ in snapshot.artifact_context
        }
        required_checkpoint_ids = {
            artifact_registry.definition_for(artifact).artifact_id
            for artifact in graph._compiled_graph.entry_artifacts
        }
        if (
            not snapshot.finalized
            and not required_checkpoint_ids.issubset(checkpoint_ids)
        ):
            raise ValueError("snapshot is missing a safe entry checkpoint")
        self._validate_snapshot_pairs(
            snapshot.artifacts,
            "artifacts",
            artifacts_by_id,
            ArtifactResult,
        )
        self._validate_snapshot_pairs(
            snapshot.config_context,
            "config_context",
            config_ids,
            Data,
        )
        for artifact_id, data in snapshot.artifact_context:
            self._validate_encoded_artifact(
                graph,
                artifacts_by_id[artifact_id],
                data.value,
            )
        for artifact_id, result in snapshot.artifacts:
            self._validate_encoded_artifact(
                graph,
                artifacts_by_id[artifact_id],
                result.value,
            )

        record_settings = CombinedContextSettings.from_settings(
            self._engine_runtime.engine_settings, snapshot.context_settings,
            graph._specification.artifacts,
        )
        ContextRecordRepository(record_settings, snapshot.context_id).validate_snapshot(
            snapshot.records, snapshot.record_sequence,
        )
        if any(record.step_index >= len(graph._compiled_graph.steps)
               or record.generation > snapshot.generation for record in snapshot.records):
            raise ValueError("snapshot record provenance is invalid")
        if not isinstance(snapshot.reports, tuple) or any(
            not isinstance(report, ExecutionReport)
            or report.context_id != snapshot.context_id
            for report in snapshot.reports
        ):
            raise ValueError("snapshot execution reports are invalid")
        if not isinstance(snapshot.progress, ProgressSnapshot):
            raise TypeError("snapshot progress must be a ProgressSnapshot")
        progress = snapshot.progress
        if (
            progress.context_id != snapshot.context_id
            or progress.graph_key != snapshot.graph_key
            or progress.graph_version != snapshot.graph_version
            or progress.context_state is not snapshot.state
            or progress.iteration != snapshot.iteration_count
            or len(progress.steps) != len(graph._compiled_graph.steps)
            or any(
                step.step_index != index
                for index, step in enumerate(progress.steps)
            )
        ):
            raise ValueError("snapshot progress does not match its context")
        if snapshot.report is not None:
            report = snapshot.report
            if (
                not isinstance(report, ContextReport)
                or report.context_id != snapshot.context_id
                or report.state is not snapshot.state
                or report.stop_requested is not snapshot.stop_requested
                or report.revision > snapshot.revision
                or not self._execution_reports_match(
                    report.executions,
                    snapshot.reports,
                )
                or report.history != snapshot.history
            ):
                raise ValueError("terminal report does not match its snapshot")
        history_types = (
            StateTransition,
            StopRequested,
            IterationStarted,
            ControlRequested,
            EngineChanged,
        )
        if not isinstance(snapshot.history, tuple) or any(
            not isinstance(entry, history_types)
            or entry.revision > snapshot.revision
            for entry in snapshot.history
        ):
            raise ValueError("snapshot lifecycle history is invalid")
        self._validate_snapshot_history(snapshot)

        step_count = len(graph._compiled_graph.steps)
        history = self._engine_runtime.progress_history
        if snapshot.context_settings.max_iterations is None:
            for iteration in range(1, snapshot.completed_iterations + 1):
                reports = tuple(
                    report
                    for report in snapshot.reports
                    if report.iteration == iteration
                )
                observations = history._observations(
                    reports,
                    step_count,
                    iteration,
                )
                if {item.step_index for item in observations} != set(
                    range(step_count)
                ):
                    raise ValueError(
                        "completed iteration reports must cover every graph step"
                    )
        elif snapshot.finalized and snapshot.started_at is not None:
            history._observations(snapshot.reports, step_count)
        history_limit = self._engine_runtime.engine_settings.context_history_admission_limit
        if history_limit is not None:
            # Final evidence may contain completion/cleanup for the accepted graph.
            # This allowance never makes an oversized queued snapshot executable.
            tail = _HistoryBudget.terminal_allowance(step_count, len(graph.artifacts)) if snapshot.finalized else 0
            if _HistoryBudget.cost(snapshot) > history_limit + tail:
                raise ContextHistoryLimitError("received full history exceeds this engine context_history_admission_limit")
        return graph

    @staticmethod
    def _validate_snapshot_history(snapshot: ContextSnapshot) -> None:
        """Validate the deterministic lifecycle encoded by a snapshot."""
        state = ContextState.SUBMITTED
        iteration = 0
        generation = 0
        engine_id: str | None = None
        stop_requested = False
        previous_revision = 0
        reassignment_pending = False

        for entry in snapshot.history:
            if (
                type(entry.revision) is not int
                or entry.revision <= previous_revision
                or entry.revision > snapshot.revision
                or not isinstance(entry.actor, CommandOrigin)
            ):
                raise ValueError("snapshot lifecycle revisions are inconsistent")
            previous_revision = entry.revision

            if reassignment_pending and not isinstance(entry, StateTransition):
                raise ValueError("snapshot ownership transition is incomplete")

            if isinstance(entry, StateTransition):
                if entry.previous_state is not state:
                    raise ValueError("snapshot state history is not contiguous")
                if (
                    entry.next_state is ContextState.FINISHED
                    and state in {
                        ContextState.VALIDATED,
                        ContextState.ROUTING,
                        ContextState.QUEUED,
                    }
                    and not stop_requested
                ):
                    raise ValueError("snapshot finish before execution requires stop acceptance")
                if reassignment_pending:
                    if entry.next_state is not ContextState.QUEUED:
                        raise ValueError(
                            "snapshot ownership change must return to queued"
                        )
                    reassignment_pending = False
                elif entry.next_state not in ContextInstance._allowed_transitions[
                    state
                ]:
                    raise ValueError("snapshot contains an invalid state transition")
                state = entry.next_state
                continue

            if isinstance(entry, IterationStarted):
                if stop_requested:
                    raise ValueError("snapshot iteration started after stop acceptance")
                if state is not ContextState.RUNNING:
                    raise ValueError("snapshot iteration started outside running")
                iteration += 1
                if entry.iteration != iteration:
                    raise ValueError("snapshot iteration history is inconsistent")
                continue

            if isinstance(entry, StopRequested):
                if stop_requested or state not in {
                    ContextState.VALIDATED,
                    ContextState.ROUTING,
                    ContextState.QUEUED,
                    ContextState.RUNNING,
                    ContextState.PLACEMENT_WAITING,
                    ContextState.PAUSED,
                }:
                    raise ValueError("snapshot stop history is inconsistent")
                stop_requested = True
                continue

            if isinstance(entry, ControlRequested):
                if state.is_terminal or not isinstance(
                    entry.request,
                    ContextRequest,
                ):
                    raise ValueError("snapshot control history is inconsistent")
                RuntimeRegistry._validate_duration(entry.duration_seconds)
                if (
                    entry.duration_seconds is not None
                    and entry.request is not ContextRequest.PAUSE
                ):
                    raise ValueError("only a pause request may have a duration")
                continue

            if isinstance(entry, EngineChanged):
                if state.is_terminal:
                    raise ValueError("snapshot ownership history is inconsistent")
                if (
                    type(entry.generation) is not int
                    or entry.generation != generation + 1
                    or type(entry.checkpoint_iteration) is not int
                    or entry.checkpoint_iteration < 0
                    or entry.checkpoint_iteration > iteration
                    or not isinstance(entry.previous_engine_id, str)
                    or not entry.previous_engine_id.strip()
                    or not isinstance(entry.current_engine_id, str)
                    or not entry.current_engine_id.strip()
                    or entry.previous_engine_id == entry.current_engine_id
                ):
                    raise ValueError("snapshot engine_id history is inconsistent")
                if engine_id is None:
                    engine_id = entry.previous_engine_id
                if entry.previous_engine_id != engine_id:
                    raise ValueError("snapshot engine_id history is not contiguous")
                engine_id = entry.current_engine_id
                generation = entry.generation
                iteration = entry.checkpoint_iteration
                reassignment_pending = state is not ContextState.QUEUED
                continue

            raise ValueError("snapshot lifecycle history is invalid")

        if reassignment_pending:
            raise ValueError("snapshot ownership transition is incomplete")
        if (
            state is not snapshot.state
            or iteration != snapshot.iteration_count
            or generation != snapshot.generation
            or stop_requested is not snapshot.stop_requested
            or (engine_id is not None and engine_id != snapshot.engine_id)
        ):
            raise ValueError("snapshot lifecycle summary is inconsistent")
        validated = any(
            isinstance(entry, StateTransition)
            and entry.next_state is ContextState.VALIDATED
            for entry in snapshot.history
        )
        started = any(
            isinstance(entry, StateTransition)
            and entry.next_state is ContextState.RUNNING
            for entry in snapshot.history
        )
        if validated != (snapshot.validated_at is not None):
            raise ValueError("snapshot validation timestamp is inconsistent")
        if started != (snapshot.started_at is not None):
            raise ValueError("snapshot start timestamp is inconsistent")
        if state.is_terminal != (snapshot.finished_at is not None):
            raise ValueError("snapshot completion timestamp is inconsistent")
        if snapshot.request is not None:
            requested = snapshot.history[-1] if snapshot.history else None
            if (
                state.is_terminal
                or not isinstance(requested, ControlRequested)
                or requested.request is not snapshot.request
                or requested.duration_seconds != snapshot.request_duration
            ):
                raise ValueError("request snapshot has no matching control entry")

    @staticmethod
    def _validate_snapshot_pairs(
        pairs: object,
        name: str,
        known: object,
        value_type: type,
    ) -> None:
        if not isinstance(pairs, tuple):
            raise TypeError(f"snapshot {name} must be a tuple")
        identifiers: set[int] = set()
        for pair in pairs:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise TypeError(f"snapshot {name} entries must be pairs")
            identifier, value = pair
            if type(identifier) is not int or identifier not in known:
                raise ValueError(f"snapshot {name} has an unknown ID")
            if identifier in identifiers:
                raise ValueError(f"snapshot {name} has a duplicate ID")
            if not isinstance(value, value_type):
                raise TypeError(
                    f"snapshot {name} contains an invalid value"
                )
            identifiers.add(identifier)

    @staticmethod
    def _validate_encoded_artifact(graph, artifact: Artifact, value: object) -> None:
        if value is None:
            return
        serializer = graph._serializer_bindings.get(artifact)
        if serializer is None:
            raise ValueError(
                "a non-empty portable artifact has no boundary serializer"
            )
        if not isinstance(value, bytes):
            raise TypeError("serialized artifact payloads must be bytes")

    @staticmethod
    def _decode_artifact_value(graph, artifact: Artifact, value: object) -> object:
        if value is None:
            return None
        serializer = graph._serializer_bindings.get(artifact)
        if serializer is None:
            raise ValueError("portable artifact has no serializer")
        return serializer.deserialize(value)

    @staticmethod
    def _validate_snapshot_identity(
        snapshot: ContextSnapshot,
        context: ContextInstance,
    ) -> None:
        graph_key = (
            context.graph_scope[0]
            if isinstance(context.graph_scope, tuple)
            else None
        )
        if (
            snapshot.context_id != context.context_id
            or snapshot.graph_key != graph_key
            or snapshot.graph_version != context.graph.version
        ):
            raise ValueError("snapshot identity does not match its context")

    def _validate_snapshot_against_context(
        self,
        snapshot: ContextSnapshot,
        context: ContextInstance,
    ) -> None:
        self._validate_snapshot_identity(snapshot, context)
        current = context.snapshot
        if snapshot.generation < current.generation or (
            snapshot.generation == current.generation
            and snapshot.revision <= current.revision
        ):
            return
        if (
            not context.is_local
            and snapshot.engine_id == self._engine_runtime.engine_id
            and not snapshot.finalized
            and snapshot.state is not ContextState.QUEUED
        ):
            raise ValueError(
                "a snapshot assigned to this engine must be queued"
            )
        if context._portable_context_settings() != snapshot.context_settings:
            raise ValueError("snapshot context settings do not match context")
        if (
            context.is_local
            and not context.is_terminal
            and current.revision != 0
        ):
            raise _SnapshotRejectedError(
                "a committed snapshot cannot replace a locally owned context"
            )
        if current.stop_requested:
            accepted_stop = next(entry for entry in current.history if isinstance(entry, StopRequested))
            if not snapshot.stop_requested or accepted_stop not in snapshot.history:
                raise ValueError("snapshot would replace committed stop acceptance")
        if not self._context_records_extend(snapshot, current):
            raise ValueError("snapshot would replace committed records")
        if snapshot.generation == current.generation and (
            not self._execution_reports_extend(
                snapshot.reports,
                current.reports,
            )
        ):
            raise ValueError("snapshot would replace committed records or reports")

    @staticmethod
    def _context_records_extend(incoming: ContextSnapshot, current: ContextSnapshot) -> bool:
        if incoming.record_sequence < current.record_sequence:
            return False
        by_sequence = {record.sequence: record for record in incoming.records}
        previous_by_sequence = {record.sequence: record for record in current.records}
        by_key: dict[str, list[int]] = {}
        for record in incoming.records:
            by_key.setdefault(record.key, []).append(record.sequence)
        limit = incoming.context_settings.record_history_limit
        for record in current.records:
            replacement = by_sequence.get(record.sequence)
            if replacement is not None:
                if replacement != record:
                    return False
            else:
                later = by_key.get(record.key, ())
                if limit is None or len(later) < limit or later[-limit] <= record.sequence:
                    return False
        return all(record.sequence > current.record_sequence or
                   record == previous_by_sequence.get(record.sequence)
                   for record in incoming.records)

    @classmethod
    def _execution_reports_extend(
        cls,
        incoming: tuple[ExecutionReport, ...],
        current: tuple[ExecutionReport, ...],
    ) -> bool:
        return len(incoming) >= len(current) and cls._execution_reports_match(
            incoming[: len(current)],
            current,
        )

    @classmethod
    def _execution_reports_match(
        cls,
        left: tuple[ExecutionReport, ...],
        right: tuple[ExecutionReport, ...],
    ) -> bool:
        return len(left) == len(right) and all(
            cls._execution_report_marker(item)
            == cls._execution_report_marker(other)
            for item, other in zip(left, right)
        )

    @staticmethod
    def _execution_report_marker(report: ExecutionReport) -> tuple[object, ...]:
        attempts = tuple(
            (
                attempt.execution,
                attempt.attempt,
                tuple(
                    RuntimeRegistry._execution_record_marker(record)
                    for record in attempt.records
                ),
            )
            for attempt in report.attempts
        )
        return (
            report.step_index,
            report.step_kind,
            report.step_name,
            report.layout_position,
            report.context_id,
            report.iteration,
            attempts,
            report.execution_count,
            report.outcome,
            report.skip_reason,
            report.duration_seconds,
        )

    @staticmethod
    def _execution_record_marker(record: object) -> tuple[object, ...]:
        common = (type(record), record.origin, record.execution)
        if isinstance(record, TimerRecord):
            return (*common, record.name, record.elapsed_time)
        if isinstance(record, MetricRecord):
            return (*common, record.name, record.value)
        if isinstance(record, LogRecord):
            return (*common, record.message)
        if isinstance(record, FailureRecord):
            exception = record.exception
            return (*common, type(exception), str(exception))
        return (*common, repr(record))

    @staticmethod
    def _portable_value_equal(left: object, right: object) -> bool:
        if left is right:
            return True
        if type(left) is not type(right):
            return False
        try:
            result = left == right
        except Exception:
            return False
        for _ in range(2):
            try:
                return bool(result)
            except (TypeError, ValueError):
                reduce_all = getattr(result, "all", None)
                if not callable(reduce_all):
                    return False
                try:
                    result = reduce_all()
                except Exception:
                    return False
        return False

    def _learn_from_snapshot(
        self,
        context: ContextInstance,
        snapshot: ContextSnapshot,
    ) -> None:
        history = self._engine_runtime.progress_history
        if snapshot.reports and not context._timing_remote_reported:
            with history._lock:
                history._remote_excluded += 1
            context._timing_remote_reported = True

    def abort_context(self, context_id: int, origin: CommandOrigin) -> None:
        context = self.find_context(context_id)
        if context is None or context.is_terminal or context.is_draining:
            return
        if not context.is_local:
            self._publish_control_request(
                context,
                ContextRequest.ABORT,
                None,
                origin,
            )
            return
        context._request_abort(origin)

        if context.is_aborting:
            self._discard_placements(context_id)
            self._engine_runtime.resource_manager.cancel_context_placements(context_id)

        if context.is_aborted:
            self._finalize_context(context_id)

    def store_context_record(
        self,
        record: ContextRecord,
        origin: CommandOrigin,
    ) -> None:
        if not isinstance(record, ContextRecord):
            raise TypeError("record must be a ContextRecord instance")
        if self.find_context(record.context_id) is None:
            return
        context = self.get_context(record.context_id)
        if not context.is_local or record.generation != context.generation or context.finalized:
            context._record_repository.discard(record)
            return
        record = context._record_value(record)
        if self._engine_runtime.observations.interested(context.context_id, context.graph_scope):
            self._publish_stored_record(context, record, record.sequence, context.snapshot)

    def report_progress(self, update: _ProgressUpdate) -> bool:
        if not isinstance(update, _ProgressUpdate):
            raise TypeError("update must be a progress update")
        context = self.find_context(update.context_id)
        if context is None or context.is_terminal:
            return False
        return context._apply_progress(update)

    def pressure(self, capability: _RuntimeCapability) -> PressureSnapshot:
        context_ids = self.context_ids()
        visible_ids = self._engine_runtime.messenger.visible_context_ids(
            capability,
            context_ids,
        )
        contexts = tuple(
            context
            for context_id in visible_ids
            if (context := self.find_context(context_id)) is not None
        )
        visible = set(visible_ids)
        pending_placements = sum(
            request.context_id in visible
            for request in self.pending_placement_requests
        )
        executor = self._engine_runtime.executor_manager
        return PressureSnapshot(
            sampled_at=datetime.now(timezone.utc),
            memory_pressured=self._engine_runtime.context_scheduler.memory_pressured,
            routing_contexts=sum(
                context.is_local and context.is_routing for context in contexts
            ),
            queued_contexts=sum(
                context.is_local and context.is_queued for context in contexts
            ),
            running_contexts=sum(
                context.is_local and context.is_running for context in contexts
            ),
            paused_contexts=sum(
                context.is_local and context.is_paused for context in contexts
            ),
            placement_waiting_contexts=sum(
                context.is_local and context.is_placement_waiting
                for context in contexts
            ),
            pending_placements=pending_placements,
            task_capacity=executor.capacity,
            occupied_tasks=sum(executor.occupied.values()),
            supervision_capacity=executor.supervision_capacity,
            engine_id=self._engine_runtime.engine_id,
        )

    def _validate_pressure(self, snapshot: PressureSnapshot) -> None:
        if (self._closed or self._shutdown_requested
                or self._engine_runtime.coordinator.is_stopping
                or self._engine_runtime.coordinator.is_stopped):
            raise _SnapshotRejectedError("runtime is not accepting pressure snapshots")
        if not isinstance(snapshot.engine_id, str):
            raise TypeError("engine_id must be a string")
        if not snapshot.engine_id.strip() or snapshot.engine_id.strip() == "self":
            raise ValueError("engine_id must identify an engine incarnation")
        if not isinstance(snapshot.sampled_at, datetime):
            raise TypeError("sampled_at must be a datetime")
        offset = snapshot.sampled_at.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("sampled_at must be timezone-aware UTC")
        if type(snapshot.memory_pressured) is not bool:
            raise TypeError("memory_pressured must be a bool")
        for name in (
            "routing_contexts", "queued_contexts", "running_contexts",
            "paused_contexts", "placement_waiting_contexts", "pending_placements",
            "task_capacity", "occupied_tasks", "supervision_capacity",
        ):
            value = getattr(snapshot, name)
            if type(value) is not int:
                raise TypeError(f"{name} must be an int")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")

    def _record_pressure(self, snapshot: PressureSnapshot) -> None:
        if snapshot.engine_id == self._engine_runtime.engine_id:
            return
        with self._remote_pressure_lock:
            if snapshot.engine_id in self._remote_pressures:
                self._remote_pressures[snapshot.engine_id] = snapshot
                self._remote_pressures.move_to_end(snapshot.engine_id)
            else:
                if len(self._remote_pressures) >= self._REMOTE_PRESSURE_LIMIT:
                    self._remote_pressures.popitem(last=False)
                self._remote_pressures[snapshot.engine_id] = snapshot

    def pressures(self, capability: _RuntimeCapability) -> tuple[PressureSnapshot, ...]:
        local = self.pressure(capability)
        with self._remote_pressure_lock:
            remote = tuple(
                self._remote_pressures[engine_id]
                for engine_id in sorted(self._remote_pressures)
            )
        return (local, *remote)

    def fail_context(
        self,
        context_id: int,
        origin: CommandOrigin,
        failure: Exception,
        failed_step: StepReference | None = None,
    ) -> None:
        context = self.get_context(context_id)
        context._request_failure(
            actor=origin,
            failure=failure,
            failed_step=failed_step,
        )
        self._decide_on_failure(failure)

    def terminate_context(
        self,
        context_id: int,
        outcome: ContextOutcome,
    ) -> None:
        context = self.find_context(context_id)
        if context is None:
            return

        if context.is_terminal and context.finalized:
            return

        if context.is_terminal:
            self._finalize_context(context_id)
            return

        context._load_executions(outcome.executions)

        if outcome.artifacts is not None:
            context._load_artifacts(outcome.artifacts)

        if context.is_aborting:
            context._complete_abort(outcome.actor)
        elif context.is_failing:
            context._complete_failure(outcome.actor)
        elif outcome.failure is None:
            context._finish(outcome.actor)
        else:
            context._request_failure(
                actor=outcome.actor,
                failure=outcome.failure,
                failed_step=outcome.failed_step,
            )
            context._complete_failure(outcome.actor)

        self._finalize_context(context_id)
        if outcome.failure is not None:
            self._decide_on_failure(outcome.failure)

    def draining_contexts(self) -> tuple[int, ...]:
        return tuple(
            context_id
            for context_id, context in self._context_items()
            if context.is_draining
        )

    def _get_context_service(self, context_id: int) -> ContextService:
        self.get_context(context_id)
        with self._contexts_lock:
            try:
                return self._context_services[context_id]
            except KeyError:
                raise RuntimeError(
                    f"context storage is unavailable for {context_id!r}"
                ) from None

    def _drop_context_runs(
        self,
        context_id: int,
        owner_capability: _RuntimeCapability | None,
    ) -> None:
        for key in tuple(self._context_runs):
            target_id, capability = key
            if target_id == context_id or capability is owner_capability:
                run = self._context_runs.pop(key, None)
                if run is not None:
                    run._detach_control()

    def _rollback_registration(
        self,
        context_id: int,
        capability: _RuntimeCapability | None,
    ) -> None:
        with self._contexts_lock:
            context = self._contexts.pop(context_id, None)
            if context is not None and context._history_capture is not None:
                context._history_capture.discard(force=True, gap=True)
                context._history_capture = None
            service = self._context_services.pop(context_id, None)
            self._history_readers.pop(context_id, None)
            registered = self._context_capabilities.pop(context_id, None)
            self._runtime_events.pop(context_id, None)
            self._drop_context_runs(context_id, registered or capability)
        self._close_context_access(context_id, service, registered or capability)

    def _close_context_access(
        self, context_id: int, service: ContextService | None,
        capability: _RuntimeCapability | None,
    ) -> None:
        failures: list[BaseException] = []
        for close in (
            lambda: service.close() if service is not None else None,
            lambda: self._engine_runtime.observations.close_owner(context_id),
            lambda: self._engine_runtime.messenger.unregister_context(context_id, capability)
                    if capability is not None else None,
        ):
            try:
                close()
            except BaseException as failure:
                failures.append(failure)
        if failures:
            raise BaseExceptionGroup("context access cleanup failed", failures)

    def _learning_scope(self, context: ContextInstance) -> _TimingScope:
        if not context.is_local or context._timing_learning_generation != context.generation:
            return None
        return context._timing_key

    def _finalize_context(self, context_id: int) -> None:
        with self._lifecycle_lock:
            self._finalize_context_locked(context_id)

    def _finalize_context_locked(self, context_id: int) -> None:
        context = self.find_context(context_id)
        if context is None:
            return

        self._discard_placements(context_id)
        self._engine_runtime.resource_manager.cancel_context_placements(context_id)
        self._engine_runtime.context_scheduler.release_context(context_id)
        settings = context.settings
        if (
            settings is not None
            and settings.max_iterations is not None
            and context.status.started_at is not None
            and not context._history_finalized
        ):
            step_count = len(context.graph._compiled_graph.steps)
            scope = self._learning_scope(context)
            complete = (scope is not None and context.is_local
                        and context.state is ContextState.FINISHED and not context.stop_requested
                        and context._completed_iterations == settings.max_iterations)
            profile = self._engine_runtime.progress_history.commit_context(
                scope,
                context._execution_reports,
                step_count,
                graph_seconds=context.progress.elapsed_seconds if complete else None,
            )
            if scope is not None:
                context._replace_progress_profile(profile)
            context._mark_history_finalized()
        context._mark_finalized()

        with self._contexts_lock:
            if self._contexts.get(context_id) is not context:
                return
            self._terminal_history.publish(context)
            self._contexts.pop(context_id, None)
            if context.generation > 0 or context_id in self._ownership_slots:
                self._ownership_slots.add(context_id)
                self._retired_contexts[context_id] = (
                    context.generation,
                    context.graph_scope,
                )
            service = self._context_services.pop(context_id, None)
            self._history_readers.pop(context_id, None)
            capability = self._context_capabilities.pop(context_id, None)
            self._runtime_events.pop(context_id, None)
            self._drop_context_runs(context_id, capability)

        self._close_context_access(context_id, service, capability)
        self._emit_idle_if_needed()

    def _emit_idle_if_needed(self) -> None:
        if self.has_unfinalized_contexts:
            return
        if not self._engine_runtime.loop.coordinator_available:
            return
        self._engine_runtime.messenger.submit(
            RuntimeIdleEvent(),
            self.capability,
        )

    def close(self) -> None:
        if getattr(self, "_closed", False):
            return
        if not hasattr(self, "_contexts"):
            self._closed = True
            return
        if self.has_unfinalized_contexts:
            raise RuntimeError("cannot close while contexts are unfinalized")
        with self._placement_lock:
            has_pending_placements = bool(self._placement_requests)
        if has_pending_placements:
            raise RuntimeError("cannot close with pending placement requests")

        for context_id, _ in self._context_items():
            self._finalize_context(context_id)
        for service in self._context_services.values():
            service.close()
        for run in self._context_runs.values():
            run._detach_control()
        self._context_services.clear()
        self._context_capabilities.clear()
        self._runtime_events.clear()
        self._context_runs.clear()
        self._retired_contexts.clear()
        self._ownership_slots.clear()
        self._ownership_pending.clear()
        with self._remote_pressure_lock:
            self._remote_pressures.clear()
        self._terminal_history.close()
        self._closed = True
        self._engine_runtime = None

    def _publish_initial_state(self, context: ContextInstance) -> None:
        if not self._engine_runtime.observations.interested(context.context_id, context.graph_scope):
            return
        snapshot = context.snapshot
        self._engine_runtime.observations.publish(
            ContextStateChanged(
                context_id=context.context_id,
                graph_key=self._graph_key(context),
                graph_version=context.graph.version,
                previous_state=None,
                current_state=ContextState.SUBMITTED,
                revision=0,
                occurred_at=context.status.created_at,
                snapshot=snapshot,
            ),
            context.graph_scope,
        )

    def _publish_lifecycle_entry(
        self,
        context: ContextInstance,
        transition: StateTransition | StopRequested,
    ) -> None:
        if not self._engine_runtime.observations.interested(context.context_id, context.graph_scope):
            return
        snapshot = context.snapshot
        if isinstance(transition, StopRequested):
            self._engine_runtime.observations.publish(
                ContextStopRequested(
                    context_id=context.context_id,
                    graph_key=self._graph_key(context),
                    graph_version=context.graph.version,
                    actor=transition.actor,
                    revision=transition.revision,
                    occurred_at=transition.recorded_at,
                    snapshot=snapshot,
                ),
                context.graph_scope,
            )
            return
        self._engine_runtime.observations.publish(
            ContextStateChanged(
                context_id=context.context_id,
                graph_key=self._graph_key(context),
                graph_version=context.graph.version,
                previous_state=transition.previous_state,
                current_state=transition.next_state,
                revision=transition.revision,
                occurred_at=transition.recorded_at,
                snapshot=snapshot,
            ),
            context.graph_scope,
        )

    def _publish_synchronized_state(
        self,
        context: ContextInstance,
        *,
        previous_state: ContextState | None,
        snapshot: ContextSnapshot,
    ) -> None:
        self._engine_runtime.observations.publish(
            ContextStateChanged(
                context_id=context.context_id,
                graph_key=self._graph_key(context),
                graph_version=context.graph.version,
                previous_state=previous_state,
                current_state=snapshot.state,
                revision=snapshot.revision,
                occurred_at=snapshot.updated_at,
                snapshot=snapshot,
            ),
            context.graph_scope,
        )

    def _publish_stored_record(
        self,
        context: ContextInstance,
        record: ContextRecord,
        record_index: int,
        snapshot: ContextSnapshot,
    ) -> None:
        self._engine_runtime.observations.publish(
            ContextValueStored(
                context_id=context.context_id,
                graph_key=self._graph_key(context),
                graph_version=context.graph.version,
                key=record.key,
                record_index=record_index,
                step_name=record.step_name,
                iteration=record.iteration,
                execution=record.execution,
                occurred_at=record.recorded_at,
                snapshot=snapshot,
            ),
            context.graph_scope,
        )

    def _publish_control_request(
        self,
        context: ContextInstance,
        request: ContextRequest,
        duration: float | None,
        origin: CommandOrigin,
    ) -> None:
        snapshot = context._request_remote_control(
            request,
            duration,
            origin,
        )
        self._engine_runtime.observations.publish(
            ContextControlRequested(
                context_id=context.context_id,
                graph_key=self._graph_key(context),
                graph_version=context.graph.version,
                request=request,
                occurred_at=snapshot.updated_at,
                snapshot=snapshot,
            ),
            context.graph_scope,
        )

    def _submit_context_registration(
        self,
        context: ContextInstance,
    ) -> None:
        self._engine_runtime.messenger.submit(
            ContextRegisteredEvent(
                context_id=context.context_id,
                supervising=context.is_supervising,
            ),
            self.capability,
        )

    @staticmethod
    def _graph_key(context: ContextInstance) -> str | None:
        return (
            context.graph_scope[0]
            if isinstance(context.graph_scope, tuple)
            else None
        )

    def _decide_on_failure(self, failure: Exception | None) -> None:
        if failure is None:
            return
        if self._engine_runtime.engine_settings.failure_mode is FailureMode.FAIL_FAST:
            self._engine_runtime.gateway.notify_failed_state(failure)

    @staticmethod
    def _validate_context_id(context_id: int) -> None:
        if type(context_id) is not int:
            raise TypeError("context_id must be int")

    def _context_items(self) -> tuple[tuple[int, ContextInstance], ...]:
        lock = getattr(self, "_contexts_lock", None)
        contexts = getattr(self, "_contexts", {})
        if lock is None:
            return tuple(contexts.items())
        with lock:
            return tuple(contexts.items())

    def _pending_placements_for(
        self,
        context_id: int,
    ) -> tuple[PlacementRequest, ...]:
        with self._placement_lock:
            return tuple(self._placement_requests.get(context_id, ()))

    def _discard_placements(self, context_id: int) -> None:
        with self._placement_lock:
            self._placement_requests.pop(context_id, None)

    @property
    def has_nonterminal_contexts(self) -> bool:
        return any(not context.is_terminal for _, context in self._context_items())

    @property
    def has_unfinalized_contexts(self) -> bool:
        lock = getattr(self, "_contexts_lock", None)
        if lock is None:
            return any(not context.finalized for _, context in self._context_items())
        with lock:
            return any(not context.finalized for context in getattr(self, "_contexts", {}).values())

    @staticmethod
    def _validate_duration(duration: int | float | None) -> None:
        if isinstance(duration, bool) or not isinstance(
            duration,
            (int, float, type(None)),
        ):
            raise TypeError("duration must be int, float, or None")
        if duration is not None and (
            duration < 0 or not math.isfinite(duration)
        ):
            raise ValueError("duration must be finite and non-negative")
