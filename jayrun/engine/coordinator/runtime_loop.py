from __future__ import annotations

import asyncio
import math
import threading
from asyncio import AbstractEventLoop
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from typing import TypeVar

from ..base.runtime_module import RuntimeModule
from ..messages.runtime_message import RuntimeMessage

T = TypeVar("T")


class RuntimeLoop(RuntimeModule):
    _EXTERNAL_START_TIMEOUT = 5.0

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._loop: AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._coordinator_task: asyncio.Task[None] | None = None
        self._coordinator_stop_expected = False
        self._owns_loop = False
        self._closing = False
        self._accepting_scheduled_messages = True
        self._scheduled_handles: set[asyncio.TimerHandle] = set()
        self._scheduled_lock = threading.Lock()
        self._started_event = threading.Event()
        self._closed_event = threading.Event()
        self._startup_failure: BaseException | None = None

    def start(self, loop: AbstractEventLoop | None = None) -> None:
        if loop is not None and not isinstance(loop, AbstractEventLoop):
            raise TypeError("loop must be an AbstractEventLoop or None")
        if self._loop is not None:
            return
        with self._scheduled_lock:
            self._accepting_scheduled_messages = True
        if loop is None:
            self._start_internal()
        else:
            self._start_external(loop)

    def _start_external(self, loop: AbstractEventLoop) -> None:
        if loop.is_closed():
            raise RuntimeError("event loop is closed")
        if not loop.is_running():
            raise RuntimeError("external event loop must already be running")
        self._loop = loop
        self._owns_loop = False
        self._closing = False
        self._coordinator_stop_expected = False
        started = threading.Event()
        cancelled = threading.Event()
        failures: list[BaseException] = []

        def create_coordinator() -> None:
            try:
                if cancelled.is_set():
                    return
                self._coordinator_task = loop.create_task(
                    self._engine_runtime.coordinator.run()
                )
                self._coordinator_task.add_done_callback(
                    self._handle_coordinator_done
                )
            except BaseException as failure:
                failures.append(failure)
            finally:
                started.set()

        if self._is_current_loop_thread():
            create_coordinator()
        else:
            try:
                loop.call_soon_threadsafe(create_coordinator)
            except BaseException:
                self._loop = None
                raise
            if not started.wait(self._EXTERNAL_START_TIMEOUT):
                cancelled.set()
                self._loop = None
                raise TimeoutError("external runtime loop did not start coordinator")
        if failures:
            self._loop = None
            raise failures[0]

    def _start_internal(self) -> None:
        self._owns_loop = True
        self._closing = False
        self._coordinator_stop_expected = False
        self._closed_event.clear()
        self._started_event.clear()
        self._startup_failure = None
        self._thread = threading.Thread(
            target=self._thread_main,
            name="runtime-loop",
            daemon=True,
        )
        try:
            self._thread.start()
        except BaseException:
            self._thread = None
            self._owns_loop = False
            raise
        self._started_event.wait()
        if self._startup_failure is not None:
            raise self._startup_failure

    def _thread_main(self) -> None:
        loop: AbstractEventLoop | None = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._coordinator_task = loop.create_task(
                self._engine_runtime.coordinator.run()
            )
            self._coordinator_task.add_done_callback(self._handle_coordinator_done)
            self._started_event.set()
            loop.run_forever()
        except BaseException as failure:
            self._startup_failure = failure
            try:
                self._engine_runtime.gateway.notify_failed_state(failure)
            except BaseException as reporting_failure:
                failure.add_note(
                    f"runtime failure reporting also failed: {reporting_failure!r}"
                )
        finally:
            self._started_event.set()
            if loop is not None:
                try:
                    self._finalize_loop(loop)
                except BaseException as failure:
                    try:
                        self._engine_runtime.gateway.notify_failed_state(failure)
                    except BaseException as reporting_failure:
                        failure.add_note(
                            "runtime finalization failure reporting also failed: "
                            f"{reporting_failure!r}"
                        )
            self._closed_event.set()

    def _handle_coordinator_done(self, task: asyncio.Task[None]) -> None:
        if self._closing or self._coordinator_stop_expected:
            return
        if task.cancelled():
            failure: BaseException | None = RuntimeError(
                "coordinator was cancelled unexpectedly"
            )
        else:
            failure = task.exception()
        if failure is None and self._engine_runtime.coordinator.is_stopped:
            return
        if failure is None:
            failure = RuntimeError("coordinator stopped unexpectedly")
        self._engine_runtime.gateway.notify_failed_state(failure)

    def run_coroutine(self, coroutine: Coroutine[object, object, T]) -> Future[T]:
        loop = self._require_loop()
        if self._closing:
            raise RuntimeError("runtime loop is closing")
        if not self._owns_loop and self._is_current_loop_thread():
            raise RuntimeError(
                "external runtime loop cannot synchronously run a coroutine "
                "from its own thread"
            )
        return asyncio.run_coroutine_threadsafe(coroutine, loop)

    async def quiesce_coordinator(self) -> None:
        task = self._coordinator_task
        if task is None or task.done():
            return
        self._coordinator_stop_expected = True
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def submit(self, message: RuntimeMessage) -> None:
        loop = self._require_loop()
        if self._closing:
            raise RuntimeError("runtime loop is closing")
        if self._is_current_loop_thread():
            self._engine_runtime.coordinator.put(message)
            return
        loop.call_soon_threadsafe(
            self._put_safely,
            message,
        )

    def submit_after(self, message: RuntimeMessage, delay: float) -> bool:
        if not isinstance(delay, (int, float)):
            raise TypeError("delay must be int or float")
        if delay < 0:
            raise ValueError("delay must be non-negative")
        if self._closing:
            return False
        loop = self._require_loop()
        with self._scheduled_lock:
            if not self._accepting_scheduled_messages:
                return False

        def schedule() -> None:
            with self._scheduled_lock:
                if not self._accepting_scheduled_messages:
                    return

                def deliver() -> None:
                    with self._scheduled_lock:
                        self._scheduled_handles.discard(handle)
                        accepted = self._accepting_scheduled_messages
                    if accepted:
                        self._put_safely(message)

                handle = loop.call_later(delay, deliver)
                self._scheduled_handles.add(handle)

        if self._is_current_loop_thread():
            schedule()
            return True
        loop.call_soon_threadsafe(self._run_callback_safely, schedule)
        return True

    def _put_safely(self, message: RuntimeMessage) -> None:
        try:
            self._engine_runtime.coordinator.put(message)
        except BaseException as failure:
            self._engine_runtime.gateway.notify_failed_state(failure)

    def _run_callback_safely(self, callback: Callable[[], None]) -> None:
        try:
            callback()
        except BaseException as failure:
            self._engine_runtime.gateway.notify_failed_state(failure)

    def _cancel_scheduled_locally(self) -> None:
        with self._scheduled_lock:
            handles = tuple(self._scheduled_handles)
            self._scheduled_handles.clear()
        for handle in handles:
            handle.cancel()

    def cancel_scheduled_messages(self) -> None:
        loop = self._require_loop()
        with self._scheduled_lock:
            self._accepting_scheduled_messages = False

        # Delayed pause/resume commands cannot be allowed to revive or block a
        # context after the shutdown boundary has been established.
        def cancel() -> None:
            self._cancel_scheduled_locally()

        if loop.is_closed() or not loop.is_running():
            cancel()
            return
        if self._is_current_loop_thread():
            cancel()
            return
        loop.call_soon_threadsafe(cancel)

    def wait(self) -> None:
        self.close()

    async def wait_async(self) -> None:
        await asyncio.to_thread(self.close)

    def close(self, timeout: float | None = None) -> None:
        self._validate_close_timeout(timeout)
        loop = self._loop
        if loop is None:
            return
        self._closing = True
        if loop.is_closed():
            with self._scheduled_lock:
                self._accepting_scheduled_messages = False
            self._cancel_scheduled_locally()
            thread = self._thread
            if thread is not None and threading.current_thread() is not thread:
                thread.join(timeout)
                if thread.is_alive():
                    raise TimeoutError("runtime loop thread did not terminate")
            self._thread = None
            self._loop = None
            self._coordinator_task = None
            return
        self.cancel_scheduled_messages()
        if self._owns_loop:
            self._close_internal(loop, timeout)
            return
        self._close_external(loop, timeout)

    def _close_internal(
        self,
        loop: AbstractEventLoop,
        timeout: float | None,
    ) -> None:
        thread = self._thread
        if thread is None:
            return
        if threading.current_thread() is thread:
            raise RuntimeError("runtime loop cannot be closed from its own thread")
        submission_failure: BaseException | None = None
        try:
            loop.call_soon_threadsafe(self._stop_loop)
        except BaseException as failure:
            submission_failure = failure
        thread.join(timeout)
        if thread.is_alive():
            failure = TimeoutError("runtime loop thread did not terminate")
            if submission_failure is not None:
                failure.add_note(
                    f"loop stop submission also failed: {submission_failure!r}"
                )
            raise failure
        self._thread = None
        self._loop = None
        self._coordinator_task = None
        if submission_failure is not None:
            raise submission_failure

    def _close_external(
        self,
        loop: AbstractEventLoop,
        timeout: float | None,
    ) -> None:
        if self._is_current_loop_thread():
            raise RuntimeError(
                "external runtime loop cannot be synchronously closed from "
                "its own thread"
            )
        if loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                self._cancel_coordinator_task(),
                loop,
            )
            future.result(timeout)
        else:
            task = self._coordinator_task
            if task is not None and not task.done():
                task.cancel()
        self._loop = None
        self._coordinator_task = None

    def _stop_loop(self) -> None:
        task = self._coordinator_task
        if task is not None and not task.done():
            task.cancel()
        loop = self._loop
        if loop is not None:
            loop.stop()

    async def _cancel_coordinator_task(self) -> None:
        task = self._coordinator_task
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def _finalize_loop(self, loop: AbstractEventLoop) -> None:
        pending_tasks = tuple(
            task for task in asyncio.all_tasks(loop) if not task.done()
        )
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            loop.run_until_complete(
                asyncio.gather(
                    *pending_tasks,
                    return_exceptions=True,
                )
            )
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()

    def _require_loop(self) -> AbstractEventLoop:
        if self._loop is None:
            raise RuntimeError("runtime loop has not started")
        if self._loop.is_closed():
            raise RuntimeError("runtime loop is closed")
        return self._loop

    def _is_current_loop_thread(self) -> bool:
        try:
            return asyncio.get_running_loop() is self._loop
        except RuntimeError:
            return False

    @staticmethod
    def _validate_close_timeout(timeout: float | None) -> None:
        if isinstance(timeout, bool) or not isinstance(
            timeout,
            (int, float, type(None)),
        ):
            raise TypeError("timeout must be int, float, or None")
        if timeout is not None and (timeout < 0 or not math.isfinite(timeout)):
            raise ValueError("timeout must be finite and non-negative")

    @property
    def owns_loop(self) -> bool:
        return self._owns_loop

    @property
    def is_closing(self) -> bool:
        return self._closing

    @property
    def is_current_loop_thread(self) -> bool:
        return self._is_current_loop_thread()

    @property
    def loop_available(self) -> bool:
        loop = self._loop
        return (
            loop is not None
            and loop.is_running()
            and not loop.is_closed()
            and not self._closing
        )

    @property
    def coordinator_available(self) -> bool:
        task = self._coordinator_task
        return self.loop_available and task is not None and not task.done()
