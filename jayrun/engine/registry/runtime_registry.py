from __future__ import annotations

import threading

from ...core.artifact.context import ArtifactContext
from ...core.config.context import ConfigContext
from ..base.runtime_module import RuntimeModule
from ..context.context_outcome import ContextOutcome
from ..context.step_reference import StepReference
from ..interfaces.services.accesses import RuntimeAccess
from ..interfaces.services.runtime import RuntimeService
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
from .context_snapshot import ContextSnapshot
from .context_state import ContextState
from .identities import (
    BaseIdentity,
    ContextIdentity,
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
        self._active_context_ids: set[int] = set()
        self._placement_requests: dict[
            int,
            dict[PlacementRequest, None],
        ] = {}
        self._context_id_generator = ContextIdGenerator()
        self._runtime_service = RuntimeService(
            runtime_messenger=self._engine_runtime.messenger,
        )

    def register(
        self,
        artifacts: ArtifactContext,
        configs: ConfigContext | None = None,
        context_settings: ContextSettings | None = None,
    ) -> int:
        if self._closed:
            raise RuntimeError("runtime registry is closed")
        context_id = self._context_id_generator.generate()
        context = ContextInstance(
            context_id=context_id,
            artifacts=artifacts,
            configs=configs,
            engine_settings=self._engine_runtime.engine_settings,
            context_settings=context_settings,
        )
        with self._contexts_lock:
            self._contexts[context_id] = context

        if context._validate_submission(self.identity):
            context._queue(self.identity)
            self._engine_runtime.messenger.submit(
                ContextRegisteredEvent(
                    context_instance=context,
                    identity=self.identity,
                )
            )
        else:
            context._mark_finalized()
            self._decide_on_failure(context.failure)

        return context_id

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
                    self._complete_context(
                        context_id,
                        was_active=context_id in self._active_context_ids,
                    )
                    context._mark_finalized()
                continue

            was_active = context_id in self._active_context_ids
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
                self._complete_context(context_id, was_active=was_active)
                context._mark_finalized()

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

    def snapshot_context(self, context_id: int) -> ContextSnapshot | None:
        context = self.find_context(context_id)
        return None if context is None else context._snapshot()

    def context_ids(self) -> tuple[int, ...]:
        return tuple(context_id for context_id, _ in self._context_items())

    def delete_context(self, context_id: int) -> bool:
        self._validate_context_id(context_id)
        with self._contexts_lock:
            context = self._contexts.get(context_id)
            if context is None:
                return False
            if not context.is_terminal or not context.finalized:
                raise RuntimeError("only finalized terminal contexts can be deleted")
            del self._contexts[context_id]
            return True

    def prune_contexts(
        self,
        limit: int | None = None,
    ) -> tuple[int, ...]:
        self._validate_prune_limit(limit)
        with self._contexts_lock:
            eligible = [
                (context.finished_at, context_id)
                for context_id, context in self._contexts.items()
                if context.is_terminal and context.finalized
            ]
            eligible.sort(
                key=lambda item: (
                    item[0] is None,
                    item[0],
                    item[1],
                )
            )
            context_ids = tuple(
                context_id
                for _, context_id in (eligible if limit is None else eligible[:limit])
            )
            for context_id in context_ids:
                del self._contexts[context_id]
            return context_ids

    def create_context_recorder(
        self,
    ) -> DebugContextRecorder | ProductionContextRecorder:
        if self._engine_runtime.engine_settings.runtime_mode is RuntimeMode.DEBUG:
            return DebugContextRecorder()
        return ProductionContextRecorder()

    def provide_runtime_access(self, context_id: int) -> RuntimeAccess:
        context = self.get_context(context_id)
        return RuntimeAccess(
            supervising=context.is_supervising,
            store=self.store_runtime_value,
            get_records=self._runtime_service.get_records,
            abort=self._runtime_service.abort,
            stop=self._runtime_service.stop,
            pause=self._runtime_service.pause,
            resume=self._runtime_service.resume,
            get_context=self.snapshot_context,
            context_ids=self.context_ids,
            active_context_ids=self.active_contexts,
            paused_context_ids=self.paused_contexts,
        )

    def store_runtime_value(self, record: ValueRecord) -> None:
        self._runtime_service.store(record)

    def start_context(self, context_id: int, identity: BaseIdentity) -> None:
        context = self.get_context(context_id)
        if context.is_terminal:
            return
        context._start(identity)
        self._active_context_ids.add(context_id)

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
        was_active = context_id in self._active_context_ids
        context._request_stop(identity)
        if context.is_terminal:
            self._complete_context(context_id, was_active=was_active)
            context._mark_finalized()

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
        # Changed: requests are grouped directly by context ID, avoiding a
        # wrapper object and making context-wide cancellation constant-time.
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
        was_active = context_id in self._active_context_ids
        context._request_abort(identity)

        if context.is_aborting:
            self._placement_requests.pop(context_id, None)
            self._engine_runtime.resource_manager.cancel_context_placements(context_id)

        if context.is_aborted:
            self._complete_context(context_id, was_active=was_active)
            context._mark_finalized()

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
        context = self.get_context(context_id)

        if context.is_terminal and context.finalized:
            return

        if context.is_terminal:
            self._complete_context(
                context_id,
                was_active=context_id in self._active_context_ids,
            )
            context._mark_finalized()
            return

        context._load_report(outcome.report)

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

        self._complete_context(context_id)
        context._mark_finalized()
        if outcome.failure is not None:
            self._decide_on_failure(outcome.failure)

    def active_contexts(self) -> tuple[int, ...]:
        return tuple(
            context_id
            for context_id, context in self._context_items()
            if context.is_active
        )

    def paused_contexts(self) -> tuple[int, ...]:
        return self._contexts_by_state(ContextState.PAUSED)

    def draining_contexts(self) -> tuple[int, ...]:
        return tuple(
            context_id
            for context_id, context in self._context_items()
            if context.is_draining
        )

    def placement_waiting_contexts(self) -> tuple[int, ...]:
        return self._contexts_by_state(ContextState.PLACEMENT_WAITING)

    def finished_contexts(self) -> tuple[int, ...]:
        return self._contexts_by_state(ContextState.FINISHED)

    def stopped_contexts(self) -> tuple[int, ...]:
        return self._contexts_by_state(ContextState.STOPPED)

    def failed_contexts(self) -> tuple[int, ...]:
        return self._contexts_by_state(ContextState.FAILED)

    def aborted_contexts(self) -> tuple[int, ...]:
        return self._contexts_by_state(ContextState.ABORTED)

    def _authorize_control(
        self,
        context_id: int,
        identity: BaseIdentity,
    ) -> bool:
        if isinstance(identity, (EngineIdentity, RuntimeModuleIdentity)):
            return True

        if isinstance(identity, (ContextIdentity, StepIdentity)):
            if identity.context_id == context_id:
                return True
            raise PermissionError("a context can only control itself")

        if isinstance(identity, SupervisorIdentity):
            supervisor = self.find_context(identity.context_id)
            if supervisor is None:
                return False
            if supervisor.is_supervising:
                return True
            raise PermissionError("context is not supervising")

        raise PermissionError("identity cannot control contexts")

    def _complete_context(
        self,
        context_id: int,
        was_active: bool = True,
    ) -> None:
        self._placement_requests.pop(context_id, None)
        self._engine_runtime.resource_manager.cancel_context_placements(context_id)
        if not was_active or context_id not in self._active_context_ids:
            return

        self._active_context_ids.remove(context_id)
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
        self._closed = True

    def _decide_on_failure(self, failure: Exception | None) -> None:
        if failure is None:
            return
        if self._engine_runtime.engine_settings.failure_mode is FailureMode.FAIL_FAST:
            self._engine_runtime.gateway.notify_failed_state(failure)

    def _contexts_by_state(self, state: ContextState) -> tuple[int, ...]:
        return tuple(
            context_id
            for context_id, context in self._context_items()
            if context.state is state
        )

    @staticmethod
    def _validate_context_id(context_id: int) -> None:
        if type(context_id) is not int:
            raise TypeError("context_id must be int")

    @staticmethod
    def _validate_prune_limit(limit: int | None) -> None:
        if isinstance(limit, bool) or not isinstance(limit, (int, type(None))):
            raise TypeError("limit must be an int or None")
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")

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
    def _validate_duration(duration: float | None) -> None:
        if not isinstance(duration, (int, float, type(None))):
            raise TypeError("duration must be int, float, or None")
        if duration is not None and duration < 0:
            raise ValueError("duration must be non-negative")
