from dataclasses import replace

from ...messages.capability import _RuntimeCapability
from ...messages.commands.record_context import RecordContextCommand
from ...messages.origin import CommandOrigin
from ...messages.runtime_messenger import RuntimeMessenger
from ..context_record import ContextRecord
from .storage import ContextRecordRepository


class ContextService:
    def __init__(self, runtime_messenger: RuntimeMessenger,
                 records: ContextRecordRepository) -> None:
        self._runtime_messenger: RuntimeMessenger | None = runtime_messenger
        self._records = records

    def record(self, record: ContextRecord, capability: _RuntimeCapability,
               origin: CommandOrigin, generation: int) -> None:
        record = replace(record, generation=generation)
        messenger = self._messenger()
        self._records.enqueue(record, lambda: messenger.submit(
            RecordContextCommand(record=record), capability, origin=origin,
        ))

    def records(self, key: str) -> tuple[ContextRecord, ...]:
        return self._records.records(key)

    def close(self) -> None:
        self._runtime_messenger = None
        self._records.close()

    def _messenger(self) -> RuntimeMessenger:
        if self._runtime_messenger is None:
            raise RuntimeError("context control service is closed")
        return self._runtime_messenger
