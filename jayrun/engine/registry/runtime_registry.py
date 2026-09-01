from __future__ import annotations

import math
import threading

from ...core.artifact.context import ArtifactContext
from ...core.config.context import ConfigContext
from ...core.graph.graph_definition import GraphDefinition
from ..base.runtime_module import RuntimeModule
from ..context.context_outcome import ContextOutcome
from ..context.step_reference import StepReference
from ..context_run import ContextRun
from ..interfaces.services.accesses import ContextAccess, RuntimeAccess
from ..interfaces.services.control import ContextControlService
from ..interfaces.services.context import ContextService
from ..interfaces.value_record import ValueRecord
from ..messages.commands.resume_context import ResumeContextCommand
from ..messages.events.context_registered import ContextRegisteredEvent
from ..messages.events.runtime_idle import RuntimeIdleEvent
from ..recorders.context.debug_recorder import DebugContextRecorder
from ..recorders.context.production_recorder import ProductionContextRecorder
from ..resource.placement_request import PlacementRequest
from ..settings.context import ContextSettings
from ..settings.engine import FailureMode, RuntimeMode
from .context_id_generator import ContextIdGenerator
from .context_instance import ContextInstance
from .context_state import ContextState
from .identities import (
    BaseIdentity,
    ContextIdentity,
    ContextRunIdentity,
    EngineIdentity,
    RuntimeModuleIdentity,
    StepIdentity,
    SupervisorIdentity,
)


class RuntimeRegistry(RuntimeModule):
    def initialize(self) -> None:
        self._closed = False
        self._contexts_lock = threading.RLock()
        self._contexts: dict[int, ContextInstance] = {}
        self._context_services: dict[int, ContextService] = {}
        self._context_runs: dict[
            tuple[int, BaseIdentity],
            ContextRun,
        ] = {}
        self._placement_requests: dict[
            int,
            dict[PlacementRequest, None],
        ] = {}
        self._context_id_generator = ContextIdGenerator()
        self._control_service = ContextControlService(
            runtime_messenger=self._engine_runtime.messenger,
        )

    def register(
        self,
        artifacts: ArtifactContext,
        configs: ConfigContext,
        supervises: tuple[GraphDefinition, ...],
        identity: BaseIdentity,
        context_settings: ContextSettings | None = None,
    ) -> ContextRun:
        if self._closed:
            raise RuntimeError("runtime registry is closed")
        context_id = self._context_id_generator.generate()
        context = ContextInstance(
            context_id=context_id,
            artifacts=artifacts,
            configs=configs,
            supervises=supervises,
            engine_settings=self._engine_runtime.engine_settings,
            context_settings=context_settings,
        )
        with self._contexts_lock:
            self._contexts[context_id] = context
            self._context_services[context_id] = ContextService(
                runtime_messenger=self._engine_runtime.messenger,
            )

        run = self.context_run(context_id, ContextRunIdentity(context_id))

        if context._validate_submission(self.identity):
            context._queue(self.identity)
            self._engine_runtime.messenger.submit(
                ContextRegisteredEvent(
                    context_instance=context,
                    identity=self.identity,
                )
            )
        else:
            self._finalize_context(context_id)
            self._decide_on_failure(context.failure)

        return run

    def request_shutdown(
        self,
        forced: bool,
        emit_idle: bool = True,
    ) -> None:
        if not isinstance(forced, bool):
            raise TypeError("forced must be a bool")
        if not isinstance(emit_idle, bool):
            raise TypeError("emit_idle must be a bool")

        # Graceful shutdown stops future iterations and resumes paused contexts
        # so their current iteration can drain. Forced shutdown aborts every
        # context that has not already entered a terminal or draining state.
        for context_id, context in self._context_items():
            if context.is_terminal:
                if not context.finalized:
                    self._finalize_context(context_id)
                continue

            if forced:
                if not context.is_draining:
                    context._request_abort(self.identity)
            elif context.state in {
                ContextState.VALIDATED,
                ContextState.QUEUED,
                ContextState.RUNNING,
                ContextState.PLACEMENT_WAITING,
                ContextState.PAUSED,
            }:
                was_paused = context.is_paused
                context._request_stop(self.identity)
                if was_paused:
                    context._resume(
                        self.identity,
                        placement_waiting=bool(
                            self._placement_requests.get(context_id)
                        ),
                    )

            if context.is_aborting:
                self._placement_requests.pop(context_id, None)
                self._engine_runtime.resource_manager.cancel_context_placements(
                    context_id
                )

            if context.is_terminal:
                self._finalize_context(context_id)

        if emit_idle:
            self._emit_idle_if_needed()

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

    def create_context_recorder(
        self,
    ) -> DebugContextRecorder | ProductionContextRecorder:
        if self._engine_runtime.engine_settings.runtime_mode is RuntimeMode.DEBUG:
            return DebugContextRecorder()
        return ProductionContextRecorder()

    def provide_runtime_access(self, context_id: int) -> RuntimeAccess:
        self.get_context(context_id)
        identity = SupervisorIdentity(context_id=context_id)
        return RuntimeAccess(
            contexts=lambda: self.context_runs(identity),
            active_contexts=lambda: self.context_runs(
                identity,
                active_only=True,
            ),
            paused_contexts=lambda: self.context_runs(
                identity,
                state=ContextState.PAUSED,
            ),
        )

    def provide_context_access(self, context_id: int) -> ContextAccess:
        service = self._get_context_service(context_id)
        return ContextAccess(
            pause=self._control_service.pause,
            abort=self._control_service.abort,
            stop=self._control_service.stop,
            get_records=service.get_records,
            store=service.store,
        )

    def context_run(
        self,
        context_id: int,
        identity: BaseIdentity,
    ) -> ContextRun:
        """Return the stable run authorized for one caller and context."""
        with self._contexts_lock:
            context = self._authorize_run_access(context_id, identity)
            key = (context_id, identity)
            run = self._context_runs.get(key)
            if run is None:
                run = ContextRun(
                    context=context,
                    context_service=self._context_services[context_id],
                    control_service=self._control_service,
                    identity=identity,
                )
                self._context_runs[key] = run
            return run

    def context_runs(
        self,
        identity: BaseIdentity,
        *,
        active_only: bool = False,
        state: ContextState | None = None,
    ) -> tuple[ContextRun, ...]:
        """Return live runs visible to ``identity`` in submission order."""
        if not isinstance(active_only, bool):
            raise TypeError("active_only must be a bool")
        if state is not None and not isinstance(state, ContextState):
            raise TypeError("state must be a ContextState instance or None")
        if active_only and state is not None:
            raise ValueError("active_only and state cannot be combined")

        contexts = self._visible_contexts(identity)
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
                        self._run_identity_for(identity, context),
                    )
                )
            except KeyError:
                continue
        return tuple(runs)

    def start_context(self, context_id: int, identity: BaseIdentity) -> None:
        context = self.find_context(context_id)
        if context is None or context.is_terminal:
            return
        context._start(identity)

    def reiterate_context(self, context_id: int, identity: BaseIdentity) -> bool:
        context = self.get_context(context_id)
        return context._reiterate(identity)

    def stop_context(self, context_id: int, identity: BaseIdentity) -> None:
        if not self._authorize_control(context_id, identity):
            return
        context = self.find_context(context_id)
        if (
            context is None
            or context.is_terminal
            or context.is_draining
            or context.stop_requested
        ):
            return
        if context.state not in {
            ContextState.VALIDATED,
            ContextState.QUEUED,
            ContextState.RUNNING,
            ContextState.PLACEMENT_WAITING,
            ContextState.PAUSED,
        }:
            return
        context._request_stop(identity)
        if context.is_terminal:
            self._finalize_context(context_id)

    def pause_context(
        self,
        context_id: int,
        identity: BaseIdentity,
        duration: float | None = None,
    ) -> None:
        if not self._authorize_control(context_id, identity):
            return
        self._validate_duration(duration)
        context = self.find_context(context_id)
        if context is None or context.is_terminal or context.is_draining:
            return
        if context.is_paused:
            pass
        elif context.state in {
            ContextState.RUNNING,
            ContextState.PLACEMENT_WAITING,
        }:
            context._pause(identity)
        else:
            return

        if duration is not None:
            self._engine_runtime.messenger.submit_after(
                ResumeContextCommand(
                    context_id=context_id,
                    identity=self.identity,
                ),
                delay=duration,
            )

    def resume_context(self, context_id: int, identity: BaseIdentity) -> None:
        if not self._authorize_control(context_id, identity):
            return
        context = self.find_context(context_id)
        if context is None or not context.is_paused:
            return
        context._resume(
            identity,
            placement_waiting=bool(self._placement_requests.get(context_id)),
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
            graph_id=id(context.graph),
            requests=requests,
        )

    def register_placement_request(
        self,
        request: PlacementRequest,
        identity: BaseIdentity,
    ) -> None:
        if not isinstance(request, PlacementRequest):
            raise TypeError("request must be a PlacementRequest instance")
        context = self.get_context(request.context_id)
        if context.is_terminal or context.is_draining:
            raise RuntimeError("terminal context cannot wait for placement")
        requests = self._placement_requests.setdefault(request.context_id, {})
        requests.setdefault(request, None)
        if not context.is_paused:
            context._wait_for_placement(identity)
        self._engine_runtime.context_scheduler.record_placement_requests(
            graph_id=id(context.graph),
            requests=(request,),
        )

    def resolve_placement_requests(
        self,
        requests: tuple[PlacementRequest, ...],
        identity: BaseIdentity,
    ) -> tuple[PlacementRequest, ...]:
        return self._remove_placement_requests(requests, identity)

    def revoke_placement_requests(
        self,
        requests: tuple[PlacementRequest, ...],
        identity: BaseIdentity,
    ) -> tuple[PlacementRequest, ...]:
        return self._remove_placement_requests(requests, identity)

    def _remove_placement_requests(
        self,
        requests: tuple[PlacementRequest, ...],
        identity: BaseIdentity,
    ) -> tuple[PlacementRequest, ...]:
        resolved: list[PlacementRequest] = []
        for request in requests:
            context_requests = self._placement_requests.get(request.context_id)
            if context_requests is None or request not in context_requests:
                continue
            context = self.find_context(request.context_id)
            if context is None or context.is_terminal or context.is_draining:
                continue
            del context_requests[request]
            if not context_requests:
                del self._placement_requests[request.context_id]
                if not context.is_paused:
                    context._resolve_placement(identity)
            resolved.append(request)
        return tuple(resolved)

    @property
    def pending_placement_requests(self) -> tuple[PlacementRequest, ...]:
        return tuple(
            request
            for requests in self._placement_requests.values()
            for request in requests
        )

    def abort_context(self, context_id: int, identity: BaseIdentity) -> None:
        if not self._authorize_control(context_id, identity):
            return
        context = self.find_context(context_id)
        if context is None or context.is_terminal or context.is_draining:
            return
        context._request_abort(identity)

        if context.is_aborting:
            self._placement_requests.pop(context_id, None)
            self._engine_runtime.resource_manager.cancel_context_placements(context_id)

        if context.is_aborted:
            self._finalize_context(context_id)

    def store_context_record(
        self,
        record: ValueRecord,
        identity: BaseIdentity,
    ) -> None:
        if not isinstance(record, ValueRecord):
            raise TypeError("record must be a ValueRecord instance")
        if not self._authorize_control(record.context_id, identity):
            return
        service = self._get_context_service(record.context_id)
        service.record(record)

    def fail_context(
        self,
        context_id: int,
        identity: BaseIdentity,
        failure: Exception,
        failed_step: StepReference | None = None,
    ) -> None:
        context = self.get_context(context_id)
        context._request_failure(
            actor=identity,
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

    def _authorize_control(
        self,
        context_id: int,
        identity: BaseIdentity,
    ) -> bool:
        try:
            self._authorize_run_access(context_id, identity)
        except KeyError:
            return False
        except PermissionError:
            if isinstance(identity, SupervisorIdentity):
                return False
            raise
        return True

    def _authorize_run_access(
        self,
        context_id: int,
        identity: BaseIdentity,
    ) -> ContextInstance:
        self._validate_context_id(context_id)
        if not isinstance(identity, BaseIdentity):
            raise TypeError("identity must be a BaseIdentity instance")

        target = self.find_context(context_id)
        if target is None:
            raise KeyError(f"unknown context_id: {context_id!r}")

        if isinstance(identity, (EngineIdentity, RuntimeModuleIdentity)):
            return target

        if isinstance(identity, (ContextIdentity, ContextRunIdentity, StepIdentity)):
            if identity.context_id == context_id:
                return target
            raise PermissionError("a context can only access itself")

        if isinstance(identity, SupervisorIdentity):
            supervisor = self.find_context(identity.context_id)
            if supervisor is None or supervisor.is_terminal:
                raise PermissionError("supervising context is no longer active")
            if supervisor.context_id == context_id:
                raise PermissionError("a supervising context does not supervise itself")
            if any(
                target.graph is graph
                for graph in supervisor.supervised_graphs
            ):
                return target
            raise PermissionError(
                "target graph was not included in this context's supervises scope"
            )

        raise PermissionError("identity cannot access contexts")

    def _visible_contexts(
        self,
        identity: BaseIdentity,
    ) -> tuple[ContextInstance, ...]:
        if not isinstance(identity, BaseIdentity):
            raise TypeError("identity must be a BaseIdentity instance")

        contexts = tuple(context for _, context in self._context_items())
        if isinstance(identity, (EngineIdentity, RuntimeModuleIdentity)):
            return contexts
        if isinstance(identity, (ContextIdentity, ContextRunIdentity, StepIdentity)):
            return tuple(
                context
                for context in contexts
                if context.context_id == identity.context_id
            )
        if isinstance(identity, SupervisorIdentity):
            supervisor = self.find_context(identity.context_id)
            if supervisor is None or supervisor.is_terminal:
                return ()
            return tuple(
                context
                for context in contexts
                if context.context_id != supervisor.context_id
                and any(
                    context.graph is graph
                    for graph in supervisor.supervised_graphs
                )
            )
        raise PermissionError("identity cannot access contexts")

    @staticmethod
    def _run_identity_for(
        identity: BaseIdentity,
        context: ContextInstance,
    ) -> BaseIdentity:
        if isinstance(identity, (EngineIdentity, RuntimeModuleIdentity)):
            return ContextRunIdentity(context.context_id)
        return identity

    def _get_context_service(self, context_id: int) -> ContextService:
        self.get_context(context_id)
        with self._contexts_lock:
            try:
                return self._context_services[context_id]
            except KeyError:
                raise RuntimeError(
                    f"context storage is unavailable for {context_id!r}"
                ) from None

    def _drop_context_runs(self, context_id: int) -> None:
        for key in tuple(self._context_runs):
            target_id, identity = key
            if target_id == context_id or (
                isinstance(identity, SupervisorIdentity)
                and identity.context_id == context_id
            ):
                run = self._context_runs.pop(key, None)
                if run is not None:
                    run._detach_control()

    def _finalize_context(self, context_id: int) -> None:
        context = self.find_context(context_id)
        if context is None:
            return

        self._placement_requests.pop(context_id, None)
        self._engine_runtime.resource_manager.cancel_context_placements(context_id)
        self._engine_runtime.context_scheduler.release_context(context_id)
        context._mark_finalized()

        with self._contexts_lock:
            if self._contexts.get(context_id) is not context:
                return
            self._contexts.pop(context_id, None)
            service = self._context_services.pop(context_id, None)
            self._drop_context_runs(context_id)

        if service is not None:
            service.close()
        self._emit_idle_if_needed()

    def _emit_idle_if_needed(self) -> None:
        if self.has_nonterminal_contexts:
            return
        self._engine_runtime.messenger.submit(RuntimeIdleEvent(identity=self.identity))

    def close(self) -> None:
        if getattr(self, "_closed", False):
            return
        if not hasattr(self, "_contexts"):
            self._closed = True
            return
        if self.has_nonterminal_contexts:
            raise RuntimeError("cannot close while contexts are nonterminal")
        if self._placement_requests:
            raise RuntimeError("cannot close with pending placement requests")

        for context_id, _ in self._context_items():
            self._finalize_context(context_id)
        for service in self._context_services.values():
            service.close()
        for run in self._context_runs.values():
            run._detach_control()
        self._context_services.clear()
        self._context_runs.clear()
        self._control_service.close()
        self._closed = True
        self._engine_runtime = None

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

    @property
    def has_nonterminal_contexts(self) -> bool:
        return any(not context.is_terminal for _, context in self._context_items())

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
