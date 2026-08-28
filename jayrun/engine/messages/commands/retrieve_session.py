from ...context.execution_session import ExecutionSession
from ...registry.identities import BaseIdentity
from ..runtime_message import RuntimeMessage


class RetrieveSessionCommand(RuntimeMessage):
    def __init__(
        self,
        session: ExecutionSession,
        identity: BaseIdentity,
    ) -> None:
        super().__init__(identity=identity)
        self._session = session

    def execute(self) -> None:
        self.engine_runtime.executor_manager.retrieve_session(self._session)

    @property
    def execute_during_shutdown(self) -> bool:
        return True
