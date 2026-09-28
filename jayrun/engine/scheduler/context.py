from __future__ import annotations

from dataclasses import dataclass
from weakref import WeakKeyDictionary

from ...core.graph.graph_definition import GraphDefinition

from ..base.runtime_module import RuntimeModule
from ..messages.commands.reconcile_contexts import ReconcileContextsCommand
from ..messages.events.context_admitted import ContextAdmittedEvent
from ..registry.context_instance import ContextInstance
from ..resource.placement import Backend, Device
from ..resource.placement_request import PlacementRequest
from .memory import MemoryPressureMonitor


@dataclass(frozen=True, slots=True)
class _PlacementRequirement:
    # These are precisely the capacity-sharing dimensions used below. Memory
    # sizes/device counts affect allocation, not this conservative scheduling
    # hint. Keeping them here accumulated equivalent hints without limit.
    device: Device
    backend: Backend
    device_id: int | None

    @classmethod
    def from_request(
        cls,
        request: PlacementRequest,
    ) -> _PlacementRequirement:
        return cls(
            device=request.device,
            backend=request.backend,
            device_id=request.device_id,
        )


class ContextScheduler(RuntimeModule):
    _reconciliation_interval = 0.25

    def initialize(self) -> None:
        self._closed = False
        self._queued_contexts: dict[int, ContextInstance] = {}
        self._admitted_contexts: dict[int, ContextInstance] = {}
        self._graph_placement_history: WeakKeyDictionary[
            GraphDefinition,
            set[_PlacementRequirement],
        ] = WeakKeyDictionary()
        self._reconciliation_scheduled = False
        cpu_device = next(
            runtime_device
            for runtime_device in self._engine_runtime.engine_settings.runtime_devices
            if runtime_device.device is Device.CPU
        )
        self._memory_pressure = MemoryPressureMonitor(
            memory_limit_gb=cpu_device.memory_limit_gb,
        )

    def admit_context(self, context_instance: ContextInstance) -> None:
        if self._closed:
            raise RuntimeError("context scheduler is closed")
        if not isinstance(context_instance, ContextInstance):
            raise TypeError("context_instance must be a ContextInstance")
        if context_instance.is_terminal:
            return
        if not context_instance.is_queued:
            raise RuntimeError("only a queued context can be admitted")
        self._queued_contexts.setdefault(
            context_instance.context_id,
            context_instance,
        )
        self._admit_queued_contexts()

    def record_placement_requests(
        self,
        graph: GraphDefinition,
        requests: tuple[PlacementRequest, ...],
    ) -> None:
        self._validate_graph(graph)
        self._validate_requests(requests)
        history = self._graph_placement_history.setdefault(graph, set())
        history.update(
            _PlacementRequirement.from_request(request)
            for request in requests
        )
        if self._queued_contexts:
            self._admit_queued_contexts()

    def reconcile(self) -> None:
        if self._closed:
            return
        self._reconciliation_scheduled = False
        self._admit_queued_contexts()

    def release_context(self, context_id: int) -> None:
        self._queued_contexts.pop(context_id, None)
        self._admitted_contexts.pop(context_id, None)
        coordinator = self._engine_runtime.coordinator
        if self._closed or coordinator.is_stopping or coordinator.is_stopped:
            return
        if self._queued_contexts:
            self._admit_queued_contexts()

    @property
    def memory_pressured(self) -> bool:
        """Return the current hysteretic process and system-memory pressure."""
        return self._memory_pressure.sample()

    def close(self) -> None:
        if getattr(self, "_closed", False):
            return
        getattr(self, "_queued_contexts", {}).clear()
        getattr(self, "_admitted_contexts", {}).clear()
        getattr(self, "_graph_placement_history", {}).clear()
        self._reconciliation_scheduled = False
        self._closed = True

    def _admit_queued_contexts(self) -> None:
        if not self._queued_contexts:
            return
        ordinary_slots = self._available_slots(supervising=False)
        supervision_slots = self._available_slots(supervising=True)
        if ordinary_slots == 0 and supervision_slots == 0:
            self._schedule_reconciliation()
            return
        if self.memory_pressured:
            self._schedule_reconciliation()
            return

        pending_requests = self._engine_runtime.registry.pending_placement_requests
        for context_id, context in tuple(self._queued_contexts.items()):
            if context.is_terminal:
                del self._queued_contexts[context_id]
                continue
            supervising = context.is_supervising
            if supervising:
                if supervision_slots == 0:
                    continue
            elif ordinary_slots == 0:
                continue
            if self._has_placement_pressure(context, pending_requests):
                continue
            del self._queued_contexts[context_id]
            self._admitted_contexts[context_id] = context
            if supervising:
                supervision_slots -= 1
            else:
                ordinary_slots -= 1
            self._engine_runtime.messenger.submit(
                ContextAdmittedEvent(
                    context_id=context_id,
                ),
                self.capability,
            )
            if ordinary_slots == 0 and supervision_slots == 0:
                break

        if self._queued_contexts:
            self._schedule_reconciliation()

    def _available_slots(self, supervising: bool) -> int:
        capacity = (
            self._engine_runtime.executor_manager.supervision_capacity
            if supervising
            else self._engine_runtime.executor_manager.capacity
        )
        admitted = sum(
            context.is_supervising is supervising
            and not context.is_paused
            and not context.is_placement_waiting
            for context in self._admitted_contexts.values()
        )
        return max(0, capacity - admitted)

    def _has_placement_pressure(
        self,
        context: ContextInstance,
        pending_requests: tuple[PlacementRequest, ...],
    ) -> bool:
        requirements = self._graph_placement_history.get(context.graph, ())
        return any(
            self._shares_capacity(requirement, pending_request)
            for requirement in requirements
            for pending_request in pending_requests
        )

    def _shares_capacity(
        self,
        requirement: _PlacementRequirement,
        pending_request: PlacementRequest,
    ) -> bool:
        if requirement.device is not pending_request.device:
            return False
        for runtime_device in self._engine_runtime.engine_settings.runtime_devices:
            if runtime_device.device is not requirement.device:
                continue
            if requirement.backend not in runtime_device.backends:
                continue
            if pending_request.backend not in runtime_device.backends:
                continue
            if requirement.device_id not in {None, runtime_device.device_id}:
                continue
            if pending_request.device_id not in {None, runtime_device.device_id}:
                continue
            return True
        return False

    def _schedule_reconciliation(self) -> None:
        if self._reconciliation_scheduled:
            return
        self._reconciliation_scheduled = True
        try:
            accepted = self._engine_runtime.messenger.submit_after(
                ReconcileContextsCommand(),
                self.capability,
                delay=self._reconciliation_interval,
            )
        except BaseException:
            self._reconciliation_scheduled = False
            raise
        if not accepted:
            self._reconciliation_scheduled = False

    @staticmethod
    def _validate_graph(graph: GraphDefinition) -> None:
        if not isinstance(graph, GraphDefinition):
            raise TypeError("graph must be a GraphDefinition")

    @staticmethod
    def _validate_requests(requests: tuple[PlacementRequest, ...]) -> None:
        if not isinstance(requests, tuple):
            raise TypeError("requests must be a tuple")
        if any(not isinstance(request, PlacementRequest) for request in requests):
            raise TypeError("requests must contain PlacementRequest instances")
