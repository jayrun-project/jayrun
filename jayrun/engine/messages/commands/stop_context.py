from ...registry.identities import BaseIdentity
from ..runtime_message import RuntimeMessage


class StopContextCommand(RuntimeMessage):
    def __init__(self, context_id: int, identity: BaseIdentity) -> None:
        super().__init__(identity=identity)
        self._context_id = context_id

    def execute(self) -> None:
        self.engine_runtime.registry.stop_context(
            self._context_id,
            identity=self.identity,
        )
