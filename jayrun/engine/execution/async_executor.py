from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable

from ..context.execution_session import ExecutionSession


class AsyncExecutor:
    def __init__(
        self,
        max_tasks: int | None,
        completion_reporter: Callable[[ExecutionSession], None],
        failure_reporter: Callable[[BaseException], None],
    ) -> None:

        self._completion_reporter = completion_reporter
        self._failure_reporter = failure_reporter
        if max_tasks is None:
            max_tasks = 1000

        self._max_capacity = max_tasks
        self._sessions: dict[asyncio.Task[object], ExecutionSession] = {}
        self._expected_cancellations: set[asyncio.Task[object]] = set()
        self._lock = threading.Lock()
        self._closed = False

    def submit(
        self,
        session: ExecutionSession,
    ) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("async executor is closed")
            if self._max_capacity - len(self._sessions) == 0:
                raise RuntimeError("The queue is full!")

        task = asyncio.create_task(
            session.step.proxy.execute(),
        )

        with self._lock:
            self._sessions[task] = session
        task.add_done_callback(self._task_completed)

    def _task_completed(
        self,
        task: asyncio.Task[object],
    ) -> None:
        session: ExecutionSession | None = None
        try:
            with self._lock:
                session = self._sessions.pop(task)
                expected_cancellation = task in self._expected_cancellations
                self._expected_cancellations.discard(task)
            if task.cancelled():
                if not expected_cancellation:
                    failure = RuntimeError(
                        "async execution task was cancelled unexpectedly"
                    )
                    session.collect(failure)
                    self._failure_reporter(failure)
            else:
                self._collect_result(session, task.result)
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
        for task, session in sessions:
            if session.step.context_id in context_id_set:
                with self._lock:
                    self._expected_cancellations.add(task)
                task.cancel()

    def shutdown(
        self,
    ) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            tasks = tuple(self._sessions)
            self._expected_cancellations.update(tasks)
        for task in tasks:
            task.cancel()

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
                    "async execution escaped with a non-Exception failure"
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
