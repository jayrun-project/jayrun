from __future__ import annotations

from dataclasses import dataclass

from ..base.runtime_module import RuntimeModule
from ..messages.commands.reconcile_contexts import ReconcileContextsCommand
from ..messages.events.context_admitted import ContextAdmittedEvent
from ..registry.context_instance import ContextInstance
from ..resource.placement import Backend, Device
from ..resource.placement_request import PlacementRequest
from .memory import MemoryPressureMonitor


@dataclass(frozen=True, slots=True)
class _PlacementRequirement:
    device: Device
    backend: Backend
    group_memory_bytes: int
    per_device_memory_bytes: int
    min_devices: int
    max_devices: int
    prefer_max_devices: bool
    exclusive: bool
    device_id: int | None

    @classmethod
    def from_request(
        cls,
        request: PlacementRequest,
    ) -> _PlacementRequirement:
        return cls(
            device=request.device,
            backend=request.backend,
            group_memory_bytes=request.group_memory_bytes,
            per_device_memory_bytes=request.per_device_memory_bytes,
            min_devices=request.min_devices,
            max_devices=request.max_devices,
            prefer_max_devices=request.prefer_max_devices,
            exclusive=request.exclusive,
            device_id=request.device_id,
        )


class ContextScheduler(RuntimeModule):
    _reconciliation_interval = 0.25

    def initialize(self) -> None:
        self._closed = False
        self._queued_contexts: dict[int, ContextInstance] = {}
        self._graph_placement_history: dict[
            int,
            set[_PlacementRequirement],
        ] = {}
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
        graph_id: int,
        requests: tuple[PlacementRequest, ...],
    ) -> None:
        self._validate_graph_id(graph_id)
        self._validate_requests(requests)
        history = self._graph_placement_history.setdefault(graph_id, set())
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

    def close(self) -> None:
        if getattr(self, "_closed", False):
            return
        getattr(self, "_queued_contexts", {}).clear()
        getattr(self, "_graph_placement_history", {}).clear()
        self._reconciliation_scheduled = False
        self._closed = True

    def _admit_queued_contexts(self) -> None:
        for context_id, context in tuple(self._queued_contexts.items()):
            if context.is_terminal:
                del self._queued_contexts[context_id]

        if not self._queued_contexts:
            return
        if self._memory_pressure.sample():
            self._schedule_reconciliation()
            return

        pending_requests = self._engine_runtime.registry.pending_placement_requests
        for context_id, context in tuple(self._queued_contexts.items()):
            if self._has_placement_pressure(context, pending_requests):
                continue
            del self._queued_contexts[context_id]
            self._engine_runtime.messenger.submit(
                ContextAdmittedEvent(
                    context_instance=context,
                    identity=self.identity,
                )
            )

        if self._queued_contexts:
            self._schedule_reconciliation()

    def _has_placement_pressure(
        self,
        context: ContextInstance,
        pending_requests: tuple[PlacementRequest, ...],
    ) -> bool:
        requirements = self._graph_placement_history.get(id(context.graph), ())
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
                ReconcileContextsCommand(identity=self.identity),
                delay=self._reconciliation_interval,
            )
        except BaseException:
            self._reconciliation_scheduled = False
            raise
        if not accepted:
            self._reconciliation_scheduled = False

    @staticmethod
    def _validate_graph_id(graph_id: int) -> None:
        if isinstance(graph_id, bool) or not isinstance(graph_id, int):
            raise TypeError("graph_id must be an int")
        if graph_id < 0:
            raise ValueError("graph_id must be non-negative")

    @staticmethod
    def _validate_requests(requests: tuple[PlacementRequest, ...]) -> None:
        if not isinstance(requests, tuple):
            raise TypeError("requests must be a tuple")
        if any(not isinstance(request, PlacementRequest) for request in requests):
            raise TypeError("requests must contain PlacementRequest instances")
