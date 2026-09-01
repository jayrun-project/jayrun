from __future__ import annotations

import threading

from ..base.runtime_module import RuntimeModule
from ..context.execution_session import ExecutionSession
from ..messages.commands.retrieve_session import RetrieveSessionCommand
from .async_executor import AsyncExecutor
from .execution_mode import ExecutionMode
from .thread_executor import ThreadExecutor


class ExecutorManager(RuntimeModule):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._closed = True
        self._executors = {}
        self._completed_sessions: dict[int, ExecutionSession] = {}
        self._completed_lock = threading.Lock()
        self._accepting_completions = False

    def initialize(self) -> None:
        self._closed = False
        self._executors = {}
        with self._completed_lock:
            self._completed_sessions = {}
            self._accepting_completions = True

        # Supervising work receives separate capacity so a blocking synchronous
        # wait, or a suspended async operator, cannot consume the capacity needed
        # by the contexts it observes.
        try:
            for supervising in (False, True):
                thread_executor = ThreadExecutor(
                    max_workers=self._engine_runtime.engine_settings.max_workers,
                    completion_reporter=self._queue_completed_session,
                    failure_reporter=self._engine_runtime.gateway.notify_failed_state,
                )
                self._executors[
                    (ExecutionMode.THREAD, supervising)
                ] = thread_executor

                async_executor = AsyncExecutor(
                    max_tasks=self._engine_runtime.engine_settings.max_tasks,
                    completion_reporter=self._queue_completed_session,
                    failure_reporter=self._engine_runtime.gateway.notify_failed_state,
                )
                self._executors[
                    (ExecutionMode.EVENT_LOOP, supervising)
                ] = async_executor
        except BaseException as startup_failure:
            try:
                self.shutdown(wait=False)
            except BaseException as cleanup_failure:
                startup_failure.add_note(
                    f"executor rollback also failed: {cleanup_failure!r}"
                )
            raise

    @property
    def free(self):
        return self._free_for(supervising=False)

    @property
    def supervision_free(self):
        return self._free_for(supervising=True)

    @property
    def capacity(self) -> int:
        return self._capacity_for(supervising=False)

    @property
    def supervision_capacity(self) -> int:
        return self._capacity_for(supervising=True)

    @property
    def occupied(self):
        completed = self._completed_counts()
        occupied: dict[ExecutionMode, int] = {}
        for key, executor in self._executors.items():
            mode, _ = key
            occupied[mode] = (
                occupied.get(mode, 0)
                + executor.occupied
                + completed.get(key, 0)
            )
        return occupied

    def assign(
        self,
        sessions: tuple[ExecutionSession, ...],
    ) -> None:
        if self._closed:
            raise RuntimeError("executor manager is closed")
        for session in sessions:
            executor = self._executors[
                (session.execution_mode, session.supervising)
            ]
            try:
                executor.submit(session)
            except BaseException as failure:
                # Submission failure is executor infrastructure failure, not an
                # operator failure. Report it, but collect the dispatched session
                # so context and resource ownership cannot become stranded.
                self._engine_runtime.gateway.notify_failed_state(failure)
                execution_failure: Exception
                if isinstance(failure, Exception):
                    execution_failure = failure
                else:
                    execution_failure = RuntimeError(
                        "executor submission escaped with a non-Exception failure"
                    )
                    execution_failure.__cause__ = failure
                try:
                    session.collect(execution_failure)
                    self._engine_runtime.context_manager.release(session)
                except BaseException as recovery_failure:
                    self._engine_runtime.gateway.notify_failed_state(
                        recovery_failure
                    )

    def cancel_contexts(self, context_ids: tuple[int, ...]) -> None:
        for executor in self._executors.values():
            executor.cancel_contexts(context_ids)

    def retrieve_session(
        self,
        session: ExecutionSession,
        coordinated: bool = True,
    ) -> None:
        session_key = id(session)
        with self._completed_lock:
            if self._completed_sessions.get(session_key) is not session:
                return
        self._engine_runtime.context_manager.release(
            session,
            coordinated=coordinated,
        )
        with self._completed_lock:
            if self._completed_sessions.get(session_key) is session:
                del self._completed_sessions[session_key]

    def recover_completed_sessions(self) -> None:
        failures: list[BaseException] = []
        with self._completed_lock:
            sessions = tuple(self._completed_sessions.values())
        for session in sessions:
            try:
                self.retrieve_session(session, coordinated=False)
            except BaseException as failure:
                failures.append(failure)
        if failures:
            raise BaseExceptionGroup(
                "completed session recovery failed",
                failures,
            )

    def shutdown(self, wait: bool = True) -> None:
        if self._closed and not self._executors:
            return
        with self._completed_lock:
            self._accepting_completions = False
        failures: list[BaseException] = []
        for supervising in (True, False):
            for mode in (ExecutionMode.EVENT_LOOP, ExecutionMode.THREAD):
                key = (mode, supervising)
                executor = self._executors.get(key)
                if executor is None:
                    continue
                try:
                    if isinstance(executor, ThreadExecutor):
                        executor.shutdown(wait=wait)
                    else:
                        executor.shutdown()
                except BaseException as failure:
                    failures.append(failure)
                else:
                    del self._executors[key]
        self._closed = not self._executors
        if failures:
            raise BaseExceptionGroup("executor shutdown failed", failures)

    def _queue_completed_session(self, session: ExecutionSession) -> None:
        with self._completed_lock:
            if not self._accepting_completions:
                return
            self._completed_sessions[id(session)] = session
        try:
            self._engine_runtime.messenger.submit(
                RetrieveSessionCommand(
                    session=session,
                    identity=self.identity,
                )
            )
        except BaseException as failure:
            self._engine_runtime.gateway.notify_failed_state(failure)

    def _completed_counts(self) -> dict[tuple[ExecutionMode, bool], int]:
        counts: dict[tuple[ExecutionMode, bool], int] = {}
        with self._completed_lock:
            sessions = tuple(self._completed_sessions.values())
        for session in sessions:
            key = (session.execution_mode, session.supervising)
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _free_for(self, supervising: bool) -> dict[ExecutionMode, int]:
        completed = self._completed_counts()
        return {
            mode: max(
                0,
                executor.free
                - completed.get((mode, supervising), 0),
            )
            for (mode, owns_supervision), executor in self._executors.items()
            if owns_supervision is supervising
        }

    def _capacity_for(self, supervising: bool) -> int:
        return sum(
            executor.capacity
            for (_, owns_supervision), executor in self._executors.items()
            if owns_supervision is supervising
        )
