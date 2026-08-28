from ...registry.identities import BaseIdentity
from ..runtime_message import RuntimeMessage


class RuntimeIdleEvent(RuntimeMessage):
    def __init__(self, identity: BaseIdentity) -> None:
        super().__init__(identity=identity)

    def execute(self) -> None:
        self.engine_runtime.gateway.notify_idled_state()

    @property
    def execute_during_shutdown(self) -> bool:
        return True
