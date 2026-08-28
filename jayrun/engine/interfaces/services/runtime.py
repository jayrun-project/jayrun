from collections.abc import Hashable

from ...messages.commands.abort_context import AbortContextCommand
from ...messages.commands.pause_context import PauseContextCommand
from ...messages.commands.resume_context import ResumeContextCommand
from ...messages.commands.stop_context import StopContextCommand
from ...messages.runtime_messenger import RuntimeMessenger
from ...registry.identities import BaseIdentity
from ..value_record import ValueRecord
from .storage import StoredValueRepository


class RuntimeCapabilityError(Exception):
    pass


class RuntimeService:
    def __init__(self, runtime_messenger: RuntimeMessenger) -> None:
        self._runtime_messenger = runtime_messenger
        self._values = StoredValueRepository()

    def store(self, record: ValueRecord) -> None:
        self._values.store(record)

    def get_records(self, key: Hashable) -> tuple[ValueRecord, ...]:
        return self._values.get_records(key)

    def abort(self, context_id: int, identity: BaseIdentity) -> None:
        self._runtime_messenger.submit(
            AbortContextCommand(context_id=context_id, identity=identity)
        )

    def stop(self, context_id: int, identity: BaseIdentity) -> None:
        self._runtime_messenger.submit(
            StopContextCommand(context_id=context_id, identity=identity)
        )

    def pause(
        self,
        context_id: int,
        identity: BaseIdentity,
        duration_seconds: float | None = None,
    ) -> None:
        self._runtime_messenger.submit(
            PauseContextCommand(
                context_id=context_id,
                duration=duration_seconds,
                identity=identity,
            )
        )

    def resume(self, context_id: int, identity: BaseIdentity) -> None:
        self._runtime_messenger.submit(
            ResumeContextCommand(context_id=context_id, identity=identity)
        )

    def cleanup(self, context_id: int) -> None:
        self._values.remove_context(context_id)
