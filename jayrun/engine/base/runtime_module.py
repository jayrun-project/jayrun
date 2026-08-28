from __future__ import annotations

from typing import TYPE_CHECKING

from ..registry.identities import RuntimeModuleIdentity

if TYPE_CHECKING:
    from ..runtime import EngineRuntime


class RuntimeModule:
    def __init__(self, engine_runtime: EngineRuntime, **kwargs):
        super().__init__(**kwargs)
        self._engine_runtime = engine_runtime

    def initialize(self) -> None:
        pass

    @property
    def identity(self) -> RuntimeModuleIdentity:
        return RuntimeModuleIdentity(name=type(self).__name__)
