from __future__ import annotations

import threading
from collections.abc import Callable


class EngineGateway:
    def __init__(
        self,
        idled: Callable[[], None],
        failed: Callable[[BaseException], None],
    ) -> None:
        self._idled = idled
        self._failed = failed
        self._condition = threading.Condition()
        self._idled_state = False
        self._shutdown_ready = False
        self._failure: BaseException | None = None
        self._failure_revision = 0

    def notify_idled_state(self) -> None:
        with self._condition:
            self._idled_state = True
        self._idled()

    def notify_failed_state(self, failure: BaseException) -> None:
        if not isinstance(failure, BaseException):
            raise TypeError("failure must be a BaseException")
        with self._condition:
            if failure is self._failure:
                return
            if self._failure is None:
                self._failure = failure
            self._failure_revision += 1
            self._condition.notify_all()
        self._failed(failure)

    def prepare_shutdown(self) -> int:
        with self._condition:
            self._shutdown_ready = False
            return self._failure_revision

    def notify_shutdown_ready(self) -> None:
        with self._condition:
            self._shutdown_ready = True
            self._condition.notify_all()

    def reset_idle_state(self) -> None:
        with self._condition:
            if self._failure is not None:
                return
            self._idled_state = False

    def wait_until_shutdown_ready(
        self,
        timeout: float | None,
        failure_revision: int,
    ) -> bool:
        with self._condition:
            self._condition.wait_for(
                lambda: self._shutdown_ready
                or self._failure_revision > failure_revision,
                timeout,
            )
            return self._shutdown_ready

    @property
    def idled(self) -> bool:
        with self._condition:
            return self._idled_state

    @property
    def failure(self) -> BaseException | None:
        with self._condition:
            return self._failure

    @property
    def failure_revision(self) -> int:
        with self._condition:
            return self._failure_revision

    @property
    def shutdown_ready(self) -> bool:
        with self._condition:
            return self._shutdown_ready
