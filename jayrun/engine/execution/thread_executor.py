from __future__ import annotations

import os
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from ..context.execution_session import ExecutionSession


class ThreadExecutor:
    def __init__(
        self,
        max_workers: int | None,
        completion_reporter: Callable[[ExecutionSession], None],
        failure_reporter: Callable[[BaseException], None],
    ) -> None:
        self._completion_reporter = completion_reporter
        self._failure_reporter = failure_reporter
        if max_workers is None:
            max_workers = min(32, (os.cpu_count() or 1) + 4)
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._max_capacity = max_workers + 2

        self._sessions: dict[Future[object], ExecutionSession] = {}
        self._expected_cancellations: set[Future[object]] = set()
        self._lock = threading.Lock()
        self._closed = False

    def submit(
        self,
        session: ExecutionSession,
    ) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("thread executor is closed")
            if self._max_capacity - len(self._sessions) == 0:
                raise RuntimeError("The queue is full!")

        future = self._executor.submit(
            session.step.proxy.execute,
        )

        with self._lock:
            self._sessions[future] = session
        future.add_done_callback(self._future_completed)

    def _future_completed(
        self,
        future: Future[object],
    ) -> None:
        session: ExecutionSession | None = None
        try:
            with self._lock:
                session = self._sessions.pop(future)
                expected_cancellation = future in self._expected_cancellations
                self._expected_cancellations.discard(future)
            if future.cancelled():
                if not expected_cancellation:
                    failure = RuntimeError(
                        "thread execution future was cancelled unexpectedly"
                    )
                    session.collect(failure)
                    self._failure_reporter(failure)
            else:
                self._collect_result(session, future.result)
        except BaseException as failure:
            self._failure_reporter(failure)
        finally:
            if session is not None:
                try:
                    self._completion_reporter(session)
                except BaseException as failure:
                    self._failure_reporter(failure)

    def cancel_contexts(self, context_ids: tuple[int, ...]) -> None:
        context_id_set = set(context_ids)
        with self._lock:
            sessions = tuple(self._sessions.items())
        for future, session in sessions:
            if session.step.context_id in context_id_set:
                with self._lock:
                    self._expected_cancellations.add(future)
                future.cancel()

    def shutdown(self, wait: bool = True) -> None:
        with self._lock:
            if self._closed:
                return
        self._executor.shutdown(
            wait=wait,
            cancel_futures=not wait,
        )
        with self._lock:
            self._closed = True

    def _collect_result(
        self,
        session: ExecutionSession,
        result_getter: Callable[[], object],
    ) -> None:
        try:
            result = result_getter()
        except BaseException as failure:
            if isinstance(failure, Exception):
                session.collect(failure)
            else:
                wrapped = RuntimeError(
                    "thread execution escaped with a non-Exception failure"
                )
                wrapped.__cause__ = failure
                session.collect(wrapped)
            self._failure_reporter(failure)
            return
        session.collect(result)

    @property
    def free(
        self,
    ) -> int:
        with self._lock:
            return self._max_capacity - len(self._sessions)

    @property
    def occupied(
        self,
    ) -> int:
        with self._lock:
            return len(self._sessions)
