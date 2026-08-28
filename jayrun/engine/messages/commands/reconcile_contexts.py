from ...registry.identities import BaseIdentity
from ..runtime_message import RuntimeMessage


class ReconcileContextsCommand(RuntimeMessage):
    def __init__(self, identity: BaseIdentity) -> None:
        super().__init__(identity=identity)

    def execute(self) -> None:
        self.engine_runtime.context_scheduler.reconcile()
