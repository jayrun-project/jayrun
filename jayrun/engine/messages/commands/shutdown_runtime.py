from ...registry.identities import BaseIdentity
from ..runtime_message import RuntimeMessage


class ShutdownRuntimeCommand(RuntimeMessage):
    def __init__(self, forced: bool, identity: BaseIdentity) -> None:
        super().__init__(identity=identity)
        self._forced = forced

    def execute(self) -> None:
        self.engine_runtime.coordinator.request_shutdown(forced=self._forced)

    @property
    def execute_during_shutdown(self) -> bool:
        return True
