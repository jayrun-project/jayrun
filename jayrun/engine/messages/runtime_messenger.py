from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from enum import Enum

from ...core.graph.graph_definition import GraphDefinition
from ..base.runtime_module import RuntimeModule
from ..pressure import PressureSnapshot
from ..snapshot import ContextSnapshot
from ..submission import _GraphScope, _SupervisionScope
from .capability import _RuntimeCapability
from .commands.abort_context import AbortContextCommand
from .commands.apply_snapshot import ApplySnapshotCommand
from .commands.pause_context import PauseContextCommand
from .commands.reconcile_contexts import ReconcileContextsCommand
from .commands.resume_context import ResumeContextCommand
from .commands.retrieve_session import RetrieveSessionCommand
from .commands.shutdown_runtime import ShutdownRuntimeCommand
from .commands.start_context import StartContextCommand
from .commands.stop_context import StopContextCommand
from .commands.transfer_context import TransferContextCommand
from .commands.record_context import RecordContextCommand
from .events.context_admitted import ContextAdmittedEvent
from .events.context_registered import ContextRegisteredEvent
from .events.context_terminated import ContextTerminatedEvent
from .events.runtime_idle import RuntimeIdleEvent
from .origin import (
    CommandOrigin,
    ContextOrigin,
    EngineOrigin,
    RuntimeModuleOrigin,
    StepOrigin,
)
from .runtime_message import (
    RuntimeMessage,
    RuntimeMessagePriority,
    _AcceptedRuntimeMessage,
)


class _PrincipalKind(Enum):
    ENGINE = "engine"
    MODULE = "module"
    CONTEXT = "context"


@dataclass(frozen=True, slots=True)
class _AuthorizationGrant:
    kind: _PrincipalKind
    origin: CommandOrigin
    allowed_messages: frozenset[type[RuntimeMessage]]
    context_id: int | None = None
    supervised_graphs: _SupervisionScope = ()
    controller: bool = False


@dataclass(frozen=True, slots=True)
class _MessagePolicy:
    priority: RuntimeMessagePriority = RuntimeMessagePriority.ACTIVE
    accepted_during_shutdown: bool = False


_CONTROL_MESSAGES = frozenset(
    {
        AbortContextCommand,
        PauseContextCommand,
        ResumeContextCommand,
        StopContextCommand,
        TransferContextCommand,
        ApplySnapshotCommand,
    }
)
_CONTEXT_MESSAGES = _CONTROL_MESSAGES | {RecordContextCommand}
_ENGINE_MESSAGES = _CONTROL_MESSAGES | {ShutdownRuntimeCommand}
_CONTROLLER_MESSAGES = _CONTEXT_MESSAGES | {ShutdownRuntimeCommand}
_MODULE_MESSAGES: dict[str, frozenset[type[RuntimeMessage]]] = {
    "Coordinator": frozenset(),
    "ContextManager": frozenset({StartContextCommand, ContextTerminatedEvent}),
    "ContextScheduler": frozenset(
        {ContextAdmittedEvent, ReconcileContextsCommand}
    ),
    "ExecutorManager": frozenset({RetrieveSessionCommand}),
    "ResourceManager": frozenset({ReconcileContextsCommand}),
    "RuntimeRegistry": frozenset(
        {ContextRegisteredEvent, ResumeContextCommand, RuntimeIdleEvent}
    ),
    "RuntimeLoop": frozenset(),
}
_ACCEPTED_DURING_SHUTDOWN = frozenset(
    {
        ApplySnapshotCommand,
        ContextAdmittedEvent,
        ContextRegisteredEvent,
        ContextTerminatedEvent,
        RetrieveSessionCommand,
        RuntimeIdleEvent,
        ShutdownRuntimeCommand,
        StartContextCommand,
        RecordContextCommand,
    }
)
_KNOWN_MESSAGES = frozenset(
    {
        *_ENGINE_MESSAGES,
        *_CONTEXT_MESSAGES,
        *_ACCEPTED_DURING_SHUTDOWN,
        ReconcileContextsCommand,
    }
)


class RuntimeMessenger(RuntimeModule):
    def initialize(self) -> None:
        self._closed = False
        self._authorization_lock = threading.RLock()
        self._grants: dict[_RuntimeCapability, _AuthorizationGrant] = {}
        self._context_capabilities: dict[int, _RuntimeCapability] = {}
        self._context_graph_scopes: dict[int, _GraphScope] = {}
        self._runtime_modules_bootstrapped = False
        self._engine_capability = self._issue(
            _AuthorizationGrant(
                kind=_PrincipalKind.ENGINE,
                origin=EngineOrigin(),
                allowed_messages=_ENGINE_MESSAGES,
            )
        )

    @property
    def engine_capability(self) -> _RuntimeCapability:
        capability = getattr(self, "_engine_capability", None)
        if capability is None:
            raise RuntimeError("engine capability is unavailable")
        return capability

    def bootstrap_runtime_modules(
        self,
        modules: tuple[RuntimeModule, ...],
    ) -> None:
        if not isinstance(modules, tuple):
            raise TypeError("modules must be a tuple")
        if any(not isinstance(module, RuntimeModule) for module in modules):
            raise TypeError("modules must contain RuntimeModule instances")
        names = tuple(type(module).__name__ for module in modules)
        if len(set(names)) != len(names):
            raise ValueError("runtime modules must have unique types")
        unknown = tuple(name for name in names if name not in _MODULE_MESSAGES)
        if unknown:
            raise ValueError(f"runtime modules are not authorized: {unknown!r}")

        with self._authorization_lock:
            if self._runtime_modules_bootstrapped:
                raise RuntimeError("runtime modules are already bootstrapped")
            for module, name in zip(modules, names, strict=True):
                module._bind_capability(
                    self._issue_locked(
                        _AuthorizationGrant(
                            kind=_PrincipalKind.MODULE,
                            origin=RuntimeModuleOrigin(name=name),
                            allowed_messages=_MODULE_MESSAGES.get(
                                name,
                                frozenset(),
                            ),
                        )
                    )
                )
            self._runtime_modules_bootstrapped = True

    def register_context(
        self,
        context_id: int,
        graph_scope: _GraphScope,
        supervised_graphs: _SupervisionScope,
        controller: bool = False,
    ) -> _RuntimeCapability:
        if type(context_id) is not int:
            raise TypeError("context_id must be int")
        if not isinstance(controller, bool):
            raise TypeError("controller must be a bool")
        self._validate_graph_scope(graph_scope)
        with self._authorization_lock:
            if context_id in self._context_capabilities:
                raise ValueError(f"context {context_id!r} is already authorized")
            capability = self._issue_locked(
                _AuthorizationGrant(
                    kind=_PrincipalKind.CONTEXT,
                    origin=ContextOrigin(context_id=context_id),
                    allowed_messages=(
                        _CONTROLLER_MESSAGES
                        if controller
                        else _CONTEXT_MESSAGES
                    ),
                    context_id=context_id,
                    supervised_graphs=supervised_graphs,
                    controller=controller,
                )
            )
            self._context_capabilities[context_id] = capability
            self._context_graph_scopes[context_id] = graph_scope
            return capability

    def unregister_context(
        self,
        context_id: int,
        capability: _RuntimeCapability,
    ) -> None:
        with self._authorization_lock:
            if self._context_capabilities.get(context_id) is not capability:
                return
            self._context_capabilities.pop(context_id, None)
            self._context_graph_scopes.pop(context_id, None)
            self._grants.pop(capability, None)

    def _prepare_history(self, accepted: _AcceptedRuntimeMessage,
                         capability: _RuntimeCapability, origin: CommandOrigin | None) -> _AcceptedRuntimeMessage:
        recorder = getattr(self._engine_runtime, "history_recorder", None)
        message = accepted.message
        if (recorder is None or not isinstance(message, ApplySnapshotCommand)
                or not isinstance(message.snapshot, ContextSnapshot)
                or message.snapshot.request is not None
                or self._engine_runtime.registry.find_context(message.snapshot.context_id) is not None):
            return accepted
        capture = recorder.prepare_snapshot(message.snapshot, self._engine_runtime.graph_registry)
        try:
            # Long application codecs do not freeze a capability grant. Recheck
            # before queue admission; already queued messages keep existing rules.
            return replace(self._accept(message, capability, origin), history_capture=capture)
        except BaseException:
            if capture is not None:
                capture.discard()
            raise

    def submit(
        self, message: RuntimeMessage, capability: _RuntimeCapability, *,
        origin: CommandOrigin | None = None,
    ) -> None:
        accepted = self._accept(message, capability, origin)
        self._validate_submission(accepted)
        if isinstance(message, ApplySnapshotCommand) and getattr(self._engine_runtime, "history_recorder", None) is not None:
            self._engine_runtime.registry.validate_snapshot(message.snapshot)
            accepted = self._prepare_history(accepted, capability, origin)
        registry = self._engine_runtime.registry
        reservation = None
        queued = False
        try:
            registry.admit_history_command(message)
            reservation = registry.reserve_ownership(message)
            accepted = replace(accepted, ownership_reservation=reservation)
            self._engine_runtime.loop.submit(accepted)
            queued = True
        finally:
            if not queued:
                registry.release_ownership_reservation(reservation)
                if accepted.history_capture is not None:
                    accepted.history_capture.discard()

    def submit_control(
        self, message: RuntimeMessage, capability: _RuntimeCapability, *,
        origin: CommandOrigin | None = None,
    ) -> bool:
        accepted = self._accept(message, capability, origin)
        registry = self._engine_runtime.registry
        if isinstance(message, ApplySnapshotCommand):
            registry.validate_snapshot(message.snapshot)
        coordinator = self._engine_runtime.coordinator
        def unavailable() -> bool:
            return (getattr(self, "_closed", False) or coordinator.is_stopped
                    or (coordinator.is_stopping and not accepted.accepted_during_shutdown)
                    or not self._engine_runtime.loop.coordinator_available)
        if unavailable():
            return False
        if isinstance(message, ApplySnapshotCommand) and getattr(self._engine_runtime, "history_recorder", None) is not None:
            accepted = self._prepare_history(accepted, capability, origin)
        reservation = None
        queued = False
        try:
            if unavailable():
                return False
            registry.admit_history_command(message)
            reservation = registry.reserve_ownership(message)
            accepted = replace(accepted, ownership_reservation=reservation)
            self._engine_runtime.loop.submit(accepted)
            queued = True
            return True
        except RuntimeError:
            if unavailable():
                return False
            raise
        finally:
            if not queued:
                registry.release_ownership_reservation(reservation)
                if accepted.history_capture is not None:
                    accepted.history_capture.discard()

    def submit_after(
        self,
        message: RuntimeMessage,
        capability: _RuntimeCapability,
        delay: float,
        *,
        origin: CommandOrigin | None = None,
    ) -> bool:
        accepted = self._accept(message, capability, origin)
        coordinator = self._engine_runtime.coordinator
        if (
            getattr(self, "_closed", False)
            or coordinator.is_stopping
            or coordinator.is_stopped
            or not self._engine_runtime.loop.coordinator_available
        ):
            return False
        return self._engine_runtime.loop.submit_after(
            message=accepted,
            delay=delay,
        )

    def visible_context_ids(
        self,
        capability: _RuntimeCapability,
        context_ids: tuple[int, ...],
    ) -> tuple[int, ...]:
        with self._authorization_lock:
            grant = self._grant_for_locked(capability)
            if grant.kind is _PrincipalKind.ENGINE:
                return context_ids
            if grant.kind is not _PrincipalKind.CONTEXT:
                raise PermissionError("runtime module cannot observe context runs")
            supervised_graphs = grant.supervised_graphs
            if supervised_graphs == ():
                return ()
            return tuple(
                context_id
                for context_id in context_ids
                if context_id != grant.context_id
                and self._graph_is_supervised(
                    self._context_graph_scopes.get(context_id),
                    supervised_graphs,
                )
            )

    def authorize_context_access(
        self,
        capability: _RuntimeCapability,
        context_id: int,
    ) -> None:
        with self._authorization_lock:
            grant = self._grant_for_locked(capability)
            if grant.kind is _PrincipalKind.ENGINE:
                return
            if grant.kind is not _PrincipalKind.CONTEXT:
                raise PermissionError("runtime module cannot expose context runs")
            if context_id == grant.context_id:
                return
            if self._graph_is_supervised(
                self._context_graph_scopes.get(context_id),
                grant.supervised_graphs,
            ):
                return
            raise PermissionError("target context is outside this capability scope")

    def authorize_terminal_history(self, capability: _RuntimeCapability) -> None:
        """Global commit cursors are visible only to the owner or a Controller."""
        with self._authorization_lock:
            grant = self._grant_for_locked(capability)
            if grant.kind is _PrincipalKind.ENGINE:
                return
            if grant.kind is _PrincipalKind.CONTEXT and grant.controller:
                return
            raise PermissionError("terminal history requires engine-owner or Controller authority")

    def authorize_controller(self, capability: _RuntimeCapability) -> None:
        with self._authorization_lock:
            grant = self._grant_for_locked(capability)
            if grant.kind is not _PrincipalKind.CONTEXT or not grant.controller:
                raise PermissionError("runtime submission requires a Controller")

    def close(self) -> None:
        if getattr(self, "_closed", False):
            return
        self._closed = True
        with self._authorization_lock:
            self._grants.clear()
            self._context_capabilities.clear()
            self._context_graph_scopes.clear()
            self._engine_capability = None

    def _accept(
        self,
        message: RuntimeMessage,
        capability: _RuntimeCapability,
        origin: CommandOrigin | None,
    ) -> _AcceptedRuntimeMessage:
        if not isinstance(message, RuntimeMessage):
            raise TypeError("message must be a RuntimeMessage instance")
        policy = self._policy_for(message)
        with self._authorization_lock:
            grant = self._grant_for_locked(capability)
            if type(message) not in grant.allowed_messages:
                raise PermissionError(
                    f"{type(message).__name__} is outside this capability"
                )
            accepted_origin = self._validated_origin(grant, origin)
            self._authorize_target_locked(grant, message)
        return _AcceptedRuntimeMessage(
            message=message,
            origin=accepted_origin,
            priority=policy.priority,
            accepted_during_shutdown=policy.accepted_during_shutdown,
        )

    def _authorize_target_locked(
        self,
        grant: _AuthorizationGrant,
        message: RuntimeMessage,
    ) -> None:
        if grant.kind is not _PrincipalKind.CONTEXT:
            return
        if isinstance(message, ApplySnapshotCommand) and isinstance(message.snapshot, PressureSnapshot):
            if grant.supervised_graphs is not None:
                raise PermissionError("pressure snapshots require unrestricted supervision authority")
            return
        context_id = self._target_context_id(message)
        if context_id is None:
            return
        if isinstance(message, RecordContextCommand):
            if context_id != grant.context_id:
                raise PermissionError("a context can only store its own values")
            return
        if isinstance(message, ApplySnapshotCommand):
            snapshot = message.snapshot
            target_scope: _GraphScope | None = (
                (snapshot.graph_key, snapshot.graph_version)
                if snapshot.graph_key is not None
                else self._context_graph_scopes.get(snapshot.context_id)
            )
            if snapshot.context_id == grant.context_id:
                return
            if self._graph_is_supervised(
                target_scope,
                grant.supervised_graphs,
            ):
                return
            raise PermissionError("snapshot target is outside this capability scope")
        if context_id == grant.context_id:
            return
        if self._graph_is_supervised(
            self._context_graph_scopes.get(context_id),
            grant.supervised_graphs,
        ):
            return
        raise PermissionError("target context is outside this capability scope")

    def _issue(self, grant: _AuthorizationGrant) -> _RuntimeCapability:
        with self._authorization_lock:
            return self._issue_locked(grant)

    def _issue_locked(self, grant: _AuthorizationGrant) -> _RuntimeCapability:
        if getattr(self, "_closed", False):
            raise RuntimeError("runtime messenger is closed")
        capability = _RuntimeCapability()
        self._grants[capability] = grant
        return capability

    def _grant_for_locked(
        self,
        capability: _RuntimeCapability,
    ) -> _AuthorizationGrant:
        if not isinstance(capability, _RuntimeCapability):
            raise TypeError("capability must be a runtime capability")
        try:
            return self._grants[capability]
        except KeyError:
            raise PermissionError("runtime capability is not active") from None

    @staticmethod
    def _validated_origin(
        grant: _AuthorizationGrant,
        origin: CommandOrigin | None,
    ) -> CommandOrigin:
        if origin is None:
            return grant.origin
        if (
            grant.kind is _PrincipalKind.CONTEXT
            and isinstance(origin, StepOrigin)
            and origin.context_id == grant.context_id
        ):
            return origin
        raise PermissionError("command origin does not belong to this capability")

    def _validate_submission(self, message: _AcceptedRuntimeMessage) -> None:
        if self._closed:
            raise RuntimeError("runtime messenger is closed")
        coordinator = self._engine_runtime.coordinator
        if coordinator.is_stopped:
            raise RuntimeError("runtime coordinator is stopped")
        if coordinator.is_stopping and not message.accepted_during_shutdown:
            raise RuntimeError("runtime is shutting down")
        if not self._engine_runtime.loop.coordinator_available:
            raise RuntimeError("runtime coordinator is unavailable")

    @staticmethod
    def _policy_for(message: RuntimeMessage) -> _MessagePolicy:
        message_type = type(message)
        if message_type not in _KNOWN_MESSAGES:
            raise TypeError(f"unsupported runtime message: {message_type.__name__}")
        priority = (
            RuntimeMessagePriority.SUBMISSION
            if isinstance(message, ContextRegisteredEvent)
            and not message.supervising
            else RuntimeMessagePriority.ACTIVE
        )
        return _MessagePolicy(
            priority=priority,
            accepted_during_shutdown=(
                message_type in _ACCEPTED_DURING_SHUTDOWN
            ),
        )

    @staticmethod
    def _target_context_id(message: RuntimeMessage) -> int | None:
        if isinstance(message, RecordContextCommand):
            return message.record.context_id
        if isinstance(
            message,
            (
                AbortContextCommand,
                PauseContextCommand,
                ResumeContextCommand,
                StopContextCommand,
                TransferContextCommand,
            ),
        ):
            return message.context_id
        if isinstance(message, ApplySnapshotCommand) and isinstance(message.snapshot, ContextSnapshot):
            return message.snapshot.context_id
        return None

    @staticmethod
    def _graph_is_supervised(
        graph: _GraphScope | None,
        supervised_graphs: _SupervisionScope,
    ) -> bool:
        if graph is None or supervised_graphs == ():
            return False
        if supervised_graphs is None:
            return True
        return any(
            graph == supervised
            if isinstance(graph, tuple) and isinstance(supervised, tuple)
            else graph is supervised
            for supervised in supervised_graphs
        )

    @staticmethod
    def _validate_graph_scope(graph_scope: _GraphScope) -> None:
        if isinstance(graph_scope, GraphDefinition):
            return
        if (
            isinstance(graph_scope, tuple)
            and len(graph_scope) == 2
            and all(isinstance(item, str) for item in graph_scope)
        ):
            return
        raise TypeError(
            "graph_scope must be a GraphDefinition or (key, version) tuple"
        )
