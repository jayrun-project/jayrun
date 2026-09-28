from ...messages.capability import _RuntimeCapability
from ...messages.commands.abort_context import AbortContextCommand
from ...messages.commands.pause_context import PauseContextCommand
from ...messages.commands.resume_context import ResumeContextCommand
from ...messages.commands.stop_context import StopContextCommand
from ...messages.commands.transfer_context import TransferContextCommand
from ...messages.origin import CommandOrigin
from ...messages.runtime_messenger import RuntimeMessenger


class ContextControlService:
    def __init__(
        self,
        runtime_messenger: RuntimeMessenger,
        capability: _RuntimeCapability,
        context_id: int,
    ) -> None:
        self._runtime_messenger: RuntimeMessenger | None = runtime_messenger
        self._capability: _RuntimeCapability | None = capability
        self._context_id = context_id

    def abort(self, origin: CommandOrigin | None = None) -> None:
        messenger, capability = self._access()
        messenger.submit_control(
            AbortContextCommand(context_id=self._context_id),
            capability,
            origin=origin,
        )

    def stop(self, origin: CommandOrigin | None = None) -> None:
        messenger, capability = self._access()
        messenger.submit_control(
            StopContextCommand(context_id=self._context_id),
            capability,
            origin=origin,
        )

    def pause(
        self,
        origin: CommandOrigin | None = None,
        duration_seconds: int | float | None = None,
    ) -> None:
        messenger, capability = self._access()
        messenger.submit_control(
            PauseContextCommand(
                context_id=self._context_id,
                duration=duration_seconds,
            ),
            capability,
            origin=origin,
        )

    def resume(self, origin: CommandOrigin | None = None) -> None:
        messenger, capability = self._access()
        messenger.submit_control(
            ResumeContextCommand(context_id=self._context_id),
            capability,
            origin=origin,
        )

    def transfer(
        self,
        engine_id: str,
        origin: CommandOrigin | None = None,
    ) -> None:
        messenger, capability = self._access()
        messenger.submit_control(
            TransferContextCommand(
                context_id=self._context_id,
                engine_id=engine_id,
            ),
            capability,
            origin=origin,
        )

    def close(self) -> None:
        self._runtime_messenger = None
        self._capability = None

    def _access(self) -> tuple[RuntimeMessenger, _RuntimeCapability]:
        if self._runtime_messenger is None or self._capability is None:
            raise RuntimeError("context control service is closed")
        return self._runtime_messenger, self._capability
