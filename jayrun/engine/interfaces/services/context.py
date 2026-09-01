from collections.abc import Hashable

from ...messages.commands.store_value import StoreValueCommand
from ...messages.runtime_messenger import RuntimeMessenger
from ...registry.identities import BaseIdentity
from ..value_record import ValueRecord
from .storage import StoredValueRepository


class ContextService:
    def __init__(self, runtime_messenger: RuntimeMessenger) -> None:
        self._runtime_messenger: RuntimeMessenger | None = runtime_messenger
        self._values = StoredValueRepository()

    def store(self, record: ValueRecord, identity: BaseIdentity) -> None:
        self._messenger().submit(
            StoreValueCommand(record=record, identity=identity)
        )

    def record(self, record: ValueRecord) -> None:
        self._values.store(record)

    def get_records(self, key: Hashable) -> tuple[ValueRecord, ...]:
        return self._values.get_records(key)

    def close(self) -> None:
        self._runtime_messenger = None

    def _messenger(self) -> RuntimeMessenger:
        if self._runtime_messenger is None:
            raise RuntimeError("context control service is closed")
        return self._runtime_messenger
