from ...context.context_outcome import ContextOutcome
from ...registry.identities import BaseIdentity
from ..runtime_message import RuntimeMessage


class ContextTerminatedEvent(RuntimeMessage):
    def __init__(
        self,
        context_id: int,
        outcome: ContextOutcome,
        identity: BaseIdentity,
    ) -> None:
        super().__init__(identity=identity)
        self._context_id = context_id
        self._outcome = outcome

    def execute(self) -> None:
        self.engine_runtime.registry.terminate_context(
            context_id=self._context_id,
            outcome=self._outcome,
        )

    @property
    def execute_during_shutdown(self) -> bool:
        return True
