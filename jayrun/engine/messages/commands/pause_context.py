from time import monotonic

from ...registry.identities import BaseIdentity
from ..runtime_message import RuntimeMessage


class PauseContextCommand(RuntimeMessage):
    def __init__(
        self,
        context_id: int,
        identity: BaseIdentity,
        duration: int | float | None = None,
    ) -> None:
        super().__init__(identity=identity)
        self._context_id = context_id
        self._duration = duration
        self._submitted_at = monotonic()

    def execute(self) -> None:
        duration = self._duration
        if duration is not None:
            duration = max(duration - (monotonic() - self._submitted_at), 0)
        self.engine_runtime.registry.pause_context(
            self._context_id,
            identity=self.identity,
            duration=duration,
        )
