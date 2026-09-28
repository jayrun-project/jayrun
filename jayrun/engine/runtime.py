from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._history import _HistoryRecorder

from .context.context_manager import ContextManager
from ..core.graph.graph_registry import GraphRegistry
from .coordinator.coordinator import Coordinator
from .coordinator.runtime_loop import RuntimeLoop
from .execution.executor_manager import ExecutorManager
from .gateway.engine_gateway import EngineGateway
from .messages.runtime_messenger import RuntimeMessenger
from .observation import _ObservationHub
from .progress_history import ProgressHistory
from .registry.runtime_registry import RuntimeRegistry
from .resource.resource_manager import ResourceManager
from .scheduler.context import ContextScheduler
from .settings.engine import EngineSettings
from .settings._instrumentation import _InstrumentationPolicy


@dataclass(slots=True)
class EngineRuntime:
    name: str
    engine_id: str
    engine_settings: EngineSettings
    progress_history: ProgressHistory
    graph_registry: GraphRegistry | None
    gateway: EngineGateway
    history_recorder: _HistoryRecorder | None = None
    context_manager: ContextManager = field(init=False)
    resource_manager: ResourceManager = field(init=False)
    executor_manager: ExecutorManager = field(init=False)
    context_scheduler: ContextScheduler = field(init=False)
    coordinator: Coordinator = field(init=False)
    registry: RuntimeRegistry = field(init=False)

    loop: RuntimeLoop = field(init=False)
    messenger: RuntimeMessenger = field(init=False)
    observations: _ObservationHub = field(init=False)
    instrumentation: _InstrumentationPolicy = field(init=False)
    _initialized: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self.instrumentation = _InstrumentationPolicy.for_mode(self.engine_settings.recording_mode)
        self.observations = _ObservationHub()
        self.registry = RuntimeRegistry(engine_runtime=self)
        self.coordinator = Coordinator(engine_runtime=self)
        self.executor_manager = ExecutorManager(engine_runtime=self)
        self.resource_manager = ResourceManager(engine_runtime=self)
        self.context_manager = ContextManager(engine_runtime=self)
        self.loop = RuntimeLoop(engine_runtime=self)
        self.messenger = RuntimeMessenger(engine_runtime=self)
        self.context_scheduler = ContextScheduler(engine_runtime=self)

    def initialize(self) -> None:
        if self._initialized:
            return
        self.messenger.initialize()
        modules = (
            self.registry,
            self.coordinator,
            self.executor_manager,
            self.resource_manager,
            self.context_manager,
            self.loop,
            self.context_scheduler,
        )
        self.messenger.bootstrap_runtime_modules(modules)
        for module in modules:
            module.initialize()
        self._initialized = True

    async def prepare_emergency_shutdown(self) -> None:
        failures: list[BaseException] = []

        # Emergency preparation bypasses the coordinator because this path is
        # used precisely when normal runtime coordination may be unavailable.
        if self.loop.coordinator_available:
            try:
                await self.loop.quiesce_coordinator()
            except BaseException as failure:
                failures.append(failure)

        try:
            self.registry.request_shutdown(
                forced=True,
                origin=self.registry.origin,
                emit_idle=False,
            )
        except BaseException as failure:
            failures.append(failure)

        try:
            self.executor_manager.cancel_contexts(
                self.registry.draining_contexts()
            )
        except BaseException as failure:
            failures.append(failure)

        try:
            await self.executor_manager._drain()
        except BaseException as failure:
            failures.append(failure)

        # Completed executor sessions remain owned by ExecutorManager until the
        # coordinator acknowledges retrieval. If coordination failed, recover
        # those sessions directly before closing context and resource managers.
        try:
            self.executor_manager.recover_completed_sessions()
        except BaseException as failure:
            failures.append(failure)

        try:
            self.context_manager.recover_terminated_contexts()
        except BaseException as failure:
            failures.append(failure)

        if failures:
            raise BaseExceptionGroup(
                "emergency shutdown preparation failed",
                failures,
            )

    async def close(self, emergency: bool = False) -> None:
        failures: list[BaseException] = []

        # Modules close only after the coordinator's shutdown barrier. Every
        # close is attempted so one cleanup failure cannot skip later modules.
        for close, kwargs in (
            (self.context_scheduler.close, {}),
            (self.executor_manager.shutdown, {"wait": not emergency}),
            (self.context_manager.close, {}),
        ):
            try:
                close(**kwargs)
            except BaseException as failure:
                failures.append(failure)

        try:
            await self.resource_manager.close()
        except BaseException as failure:
            failures.append(failure)

        for close in (
            self.registry.close,
            self.messenger.close,
            self.observations.close,
        ):
            try:
                close()
            except BaseException as failure:
                failures.append(failure)

        try:
            self.progress_history.flush()
        except BaseException as failure:
            failures.append(failure)

        self._initialized = False

        if failures:
            raise BaseExceptionGroup("runtime shutdown failed", failures)
