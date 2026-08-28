from ...registry.identities import BaseIdentity
from ..runtime_message import RuntimeMessage


class StartContextCommand(RuntimeMessage):
    def __init__(self, context_id: int, identity: BaseIdentity) -> None:
        super().__init__(identity=identity)
        self._context_id = context_id

    def execute(self) -> None:
        self.engine_runtime.registry.start_context(
            self._context_id,
            identity=self.identity,
        )

    @property
    def execute_during_shutdown(self) -> bool:
        return True
