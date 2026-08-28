from __future__ import annotations

from ..base.runtime_module import RuntimeModule
from ..execution.execution_mode import ExecutionMode
from ..interfaces.services.accesses import ContextAccess
from ..interfaces.services.context import ContextService
from ..messages.commands.start_context import StartContextCommand
from ..registry.context_instance import ContextInstance
from ..resource.placement_request import PlacementRequest
from .execution_context import ExecutionContext
from .execution_session import ExecutionSession


class ContextManager(RuntimeModule):
    name = "context manager"

    def initialize(self) -> None:
        self._closed = False
        self._contexts: dict[int, ExecutionContext] = {}

    def register(self, context_instance: ContextInstance) -> None:
        if self._closed:
            raise RuntimeError("context manager is closed")
        context_id = context_instance.context_id
        if context_instance.is_terminal:
            return
        if context_id in self._contexts:
            raise ValueError(f"context {context_id!r} is already registered")

        context_recorder = self._engine_runtime.registry.create_context_recorder()
        runtime_access = self._engine_runtime.registry.provide_runtime_access(
            context_id
        )
        context_service = ContextService(
            runtime_messenger=self._engine_runtime.messenger
        )
        context_access = ContextAccess(
            pause=context_service.pause,
            abort=context_service.abort,
            stop=context_service.stop,
            get_records=context_service.get_records,
            store=context_service.store,
        )
        execution_context = ExecutionContext(
            context_instance=context_instance,
            recorder=context_recorder,
            resource_manager=self._engine_runtime.resource_manager,
            runtime_access=runtime_access,
            context_access=context_access,
            runtime_registry=self._engine_runtime.registry,
        )
        try:
            execution_context.initialize()
            self._contexts[context_id] = execution_context
            self._engine_runtime.messenger.submit(
                StartContextCommand(
                    context_id=context_id,
                    identity=self.identity,
                )
            )
        except BaseException as failure:
            self._contexts.pop(context_id, None)
            try:
                execution_context._rollback_initialization()
            except BaseException as cleanup_failure:
                failure.add_note(
                    f"context registration rollback also failed: {cleanup_failure!r}"
                )
            raise

    def acquire(
        self,
        capacities: dict[ExecutionMode, int],
    ) -> tuple[ExecutionSession, ...]:
        sessions: list[ExecutionSession] = []
        remaining = capacities.copy()

        contexts = tuple(self._contexts.values())
        supervisors = tuple(context for context in contexts if context.is_supervising)
        ordinary = tuple(context for context in contexts if not context.is_supervising)

        try:
            for context in (*supervisors, *ordinary):
                context.finalize_if_drained()
                if context.terminated:
                    self._close_context(context)
                    continue

                for mode, capacity in tuple(remaining.items()):
                    for _ in range(capacity):
                        session = context.dispatch_next(mode)
                        if session is None:
                            break
                        sessions.append(session)
                        remaining[mode] -= 1

                if all(capacity == 0 for capacity in remaining.values()):
                    break
        except BaseException as failure:
            for session in reversed(sessions):
                context = self._contexts.get(session.step.context_id)
                if context is None:
                    continue
                try:
                    context._cancel_unsubmitted_session(session)
                except BaseException as cleanup_failure:
                    failure.add_note(
                        f"unsubmitted session cleanup also failed: {cleanup_failure!r}"
                    )
            raise

        return tuple(sessions)

    def release(
        self,
        session: ExecutionSession,
        coordinated: bool = True,
    ) -> None:
        if not isinstance(coordinated, bool):
            raise TypeError("coordinated must be a bool")
        context_id = session.step.context_id
        context = self._contexts.get(context_id)
        if context is None:
            if session.report is not None and session._report_recorded:
                return
            raise KeyError(f"unknown execution context: {context_id!r}")

        context.collect(session)
        if context.terminated:
            self._close_context(context, coordinated=coordinated)

    def resolve_placements(
        self,
        requests: tuple[PlacementRequest, ...],
    ) -> tuple[PlacementRequest, ...]:
        rejected: list[PlacementRequest] = []
        for request in requests:
            context = self._contexts.get(request.context_id)
            if context is None or not context.resolve_placement(request):
                rejected.append(request)
        # Changed: ContextManager validates the exact live session before a
        # registry-approved placement grant can make it dispatchable again.
        return tuple(rejected)

    def revoke_placements(
        self,
        requests: tuple[PlacementRequest, ...],
    ) -> tuple[PlacementRequest, ...]:
        rejected: list[PlacementRequest] = []
        for request in requests:
            context = self._contexts.get(request.context_id)
            if context is None or not context.revoke_placement(request):
                rejected.append(request)
        return tuple(rejected)

    def recover_terminated_contexts(self) -> None:
        failures: list[BaseException] = []
        for context in tuple(getattr(self, "_contexts", {}).values()):
            try:
                context.finalize_if_drained()
            except BaseException as failure:
                failures.append(failure)
            if not context.terminated:
                continue
            try:
                self._close_context(context, coordinated=False)
            except BaseException as failure:
                failures.append(failure)
        if failures:
            raise BaseExceptionGroup(
                "terminated context recovery failed",
                failures,
            )

    def _close_context(
        self,
        context: ExecutionContext,
        coordinated: bool = True,
    ) -> None:
        context_id = context.context_id
        self._engine_runtime.registry.terminate_context(
            context_id=context_id,
            outcome=context.outcome,
        )
        self._contexts.pop(context_id, None)

    def close(self) -> None:
        if getattr(self, "_closed", False):
            return
        if getattr(self, "_contexts", None):
            raise RuntimeError("cannot close while execution contexts are active")
        self._closed = True

    @property
    def empty(self) -> bool:
        return not getattr(self, "_contexts", None)
