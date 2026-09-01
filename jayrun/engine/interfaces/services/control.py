from ...messages.commands.abort_context import AbortContextCommand
from ...messages.commands.pause_context import PauseContextCommand
from ...messages.commands.resume_context import ResumeContextCommand
from ...messages.commands.stop_context import StopContextCommand
from ...messages.runtime_messenger import RuntimeMessenger
from ...registry.identities import BaseIdentity


class ContextControlService:
    def __init__(self, runtime_messenger: RuntimeMessenger) -> None:
        self._runtime_messenger: RuntimeMessenger | None = runtime_messenger

    def abort(self, context_id: int, identity: BaseIdentity) -> None:
        self._messenger().submit_control(
            AbortContextCommand(context_id=context_id, identity=identity)
        )

    def stop(self, context_id: int, identity: BaseIdentity) -> None:
        self._messenger().submit_control(
            StopContextCommand(context_id=context_id, identity=identity)
        )

    def pause(
        self,
        context_id: int,
        identity: BaseIdentity,
        duration_seconds: int | float | None = None,
    ) -> None:
        self._messenger().submit_control(
            PauseContextCommand(
                context_id=context_id,
                duration=duration_seconds,
                identity=identity,
            )
        )

    def resume(self, context_id: int, identity: BaseIdentity) -> None:
        self._messenger().submit_control(
            ResumeContextCommand(context_id=context_id, identity=identity)
        )

    def close(self) -> None:
        self._runtime_messenger = None

    def _messenger(self) -> RuntimeMessenger:
        if self._runtime_messenger is None:
            raise RuntimeError("context control service is closed")
        return self._runtime_messenger
