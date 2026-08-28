from ..base.runtime_module import RuntimeModule
from ..registry.identities import BaseIdentity
from .runtime_message import RuntimeMessage


class RuntimeMessenger(RuntimeModule):
    def initialize(self) -> None:
        self._closed = False

    def submit(
        self,
        message: RuntimeMessage,
    ) -> None:
        self._validate_submission(message)
        if not self._authorize(message):
            raise PermissionError("runtime message requires a valid identity")
        message._engine_runtime = self._engine_runtime
        self._engine_runtime.loop.submit(message)

    def submit_after(
        self,
        message: RuntimeMessage,
        delay: float,
    ) -> bool:
        if not self._authorize(message):
            raise PermissionError("runtime message requires a valid identity")
        coordinator = self._engine_runtime.coordinator
        if (
            getattr(self, "_closed", False)
            or coordinator.is_stopping
            or coordinator.is_stopped
            or not self._engine_runtime.loop.coordinator_available
        ):
            return False
        message._engine_runtime = self._engine_runtime
        return self._engine_runtime.loop.submit_after(
            message=message,
            delay=delay,
        )

    def close(self) -> None:
        if getattr(self, "_closed", False):
            return
        self._closed = True

    def _validate_submission(self, message: RuntimeMessage) -> None:
        if self._closed:
            raise RuntimeError("runtime messenger is closed")
        coordinator = self._engine_runtime.coordinator
        if coordinator.is_stopped:
            raise RuntimeError("runtime coordinator is stopped")
        if coordinator.is_stopping and not message.execute_during_shutdown:
            raise RuntimeError("runtime is shutting down")
        if not self._engine_runtime.loop.coordinator_available:
            raise RuntimeError("runtime coordinator is unavailable")

    def _authorize(self, message: RuntimeMessage) -> bool:
        return isinstance(message.identity, BaseIdentity)
