from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..registry.identities import BaseIdentity

if TYPE_CHECKING:
    from ..runtime import EngineRuntime


class RuntimeMessage(ABC):
    def __init__(self, identity: BaseIdentity) -> None:
        self._identity = identity
        self._engine_runtime: EngineRuntime | None = None

    @abstractmethod
    def execute(self) -> None:
        raise NotImplementedError

    @property
    def identity(self) -> BaseIdentity:
        return self._identity

    @property
    def engine_runtime(self) -> EngineRuntime:
        if self._engine_runtime is None:
            raise RuntimeError("message has not been submitted")
        return self._engine_runtime

    @property
    def execute_during_shutdown(self) -> bool:
        return False
