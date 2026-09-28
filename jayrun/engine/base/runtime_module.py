from __future__ import annotations

from typing import TYPE_CHECKING

from ..messages.capability import _RuntimeCapability
from ..messages.origin import RuntimeModuleOrigin

if TYPE_CHECKING:
    from ..runtime import EngineRuntime


class RuntimeModule:
    def __init__(self, engine_runtime: EngineRuntime, **kwargs):
        super().__init__(**kwargs)
        self._engine_runtime = engine_runtime
        self._capability: _RuntimeCapability | None = None
        self._origin = RuntimeModuleOrigin(name=type(self).__name__)

    def initialize(self) -> None:
        pass

    @property
    def capability(self) -> _RuntimeCapability:
        if self._capability is None:
            raise RuntimeError("runtime module capability is unavailable")
        return self._capability

    @property
    def origin(self) -> RuntimeModuleOrigin:
        return self._origin

    def _bind_capability(self, capability: _RuntimeCapability) -> None:
        if self._capability is not None:
            raise RuntimeError("runtime module capability is already bound")
        self._capability = capability
