from ...interfaces.value_record import ValueRecord
from ...registry.identities import BaseIdentity
from ..runtime_message import RuntimeMessage


class StoreValueCommand(RuntimeMessage):
    def __init__(self, record: ValueRecord, identity: BaseIdentity) -> None:
        super().__init__(identity=identity)
        self._record = record

    def execute(self) -> None:
        self.engine_runtime.registry.store_context_record(
            self._record,
            self.identity,
        )

    @property
    def execute_during_shutdown(self) -> bool:
        return True
