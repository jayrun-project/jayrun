from ...registry.context_instance import ContextInstance
from ...registry.identities import BaseIdentity
from ..runtime_message import RuntimeMessage, RuntimeMessagePriority


class ContextRegisteredEvent(RuntimeMessage):
    def __init__(
        self,
        context_instance: ContextInstance,
        identity: BaseIdentity,
    ) -> None:
        super().__init__(identity=identity)
        self._context_instance = context_instance

    def execute(self) -> None:
        self.engine_runtime.context_scheduler.admit_context(
            self._context_instance
        )

    @property
    def execute_during_shutdown(self) -> bool:
        return True

    @property
    def priority(self) -> RuntimeMessagePriority:
        return (
            RuntimeMessagePriority.ACTIVE
            if self._context_instance.is_supervising
            else RuntimeMessagePriority.SUBMISSION
        )
