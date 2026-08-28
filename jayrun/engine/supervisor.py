from __future__ import annotations

import asyncio
import math
import threading
from collections.abc import Coroutine

from ..core.artifact.context import ArtifactContext
from ..core.config.context import ConfigContext
from .engine_state import EngineState, RuntimeActivity
from .gateway.engine_gateway import EngineGateway
from .messages.commands.shutdown_runtime import ShutdownRuntimeCommand
from .registry.context_instance import ContextInstance
from .registry.context_snapshot import ContextSnapshot
from .registry.context_state import ContextState
from .registry.identities import EngineIdentity
from .runtime import EngineRuntime
from .settings.context import ContextSettings
from .settings.engine import EngineSettings


class EngineSupervisor:
    _FORCED_ACK_TIMEOUT = 5.0
    _CLEANUP_TIMEOUT = 5.0

    def __init__(self, settings: EngineSettings) -> None:
        if not isinstance(settings, EngineSettings):
            raise TypeError("settings must be an EngineSettings instance")
        self._settings = settings
        self._identity = EngineIdentity()
        self._state = EngineState.CREATED
        self._activity = RuntimeActivity.IDLE
        self._runtime: EngineRuntime | None = None
        self._failure: BaseException | None = None
        self._secondary_failures: list[BaseException] = []
        self._cleanup_failures: list[BaseException] = []
        self._shutdown_started = False
        self._lock = threading.RLock()
        self._lifecycle_lock = threading.Lock()
        self._startup_complete = threading.Event()
        self._startup_complete.set()
        self._shutdown_complete = threading.Event()
        self._shutdown_complete.set()
        self._failure_shutdown_thread: threading.Thread | None = None

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        with self._lifecycle_lock:
            with self._lock:
                if self._state is EngineState.RUNNING:
                    return
                if self._state is not EngineState.CREATED:
                    raise RuntimeError(
                        f"engine cannot start from {self._state.value!r}"
                    )
                self._state = EngineState.STARTING
                self._startup_complete.clear()

            runtime: EngineRuntime | None = None
            try:
                runtime = EngineRuntime(
                    engine_settings=self._settings,
                    gateway=EngineGateway(
                        idled=self._mark_idle,
                        failed=self.report_failure,
                    ),
                )
                with self._lock:
                    self._runtime = runtime
                runtime.initialize()
                runtime.loop.start(loop)
            except BaseException as failure:
                self._record_failure(failure)

            with self._lock:
                startup_failure = self._failure
                if startup_failure is None:
                    self._state = EngineState.RUNNING
                    self._activity = RuntimeActivity.IDLE
                    self._startup_complete.set()
                    return
                self._state = EngineState.STOPPING
                self._shutdown_started = True
                self._shutdown_complete.clear()

            # Startup failure uses the same shutdown owner and cleanup pipeline,
            # but begins in emergency mode because initialization may be partial.
            try:
                self._execute_shutdown(
                    runtime=runtime,
                    forced=True,
                    timeout=None,
                    emergency=True,
                )
            finally:
                self._startup_complete.set()

            self._raise_failure()

    def submit(
        self,
        artifacts: ArtifactContext,
        configs: ConfigContext | None = None,
        context_settings: ContextSettings | None = None,
    ) -> int:
        self._validate_submission(
            artifacts=artifacts,
            configs=configs,
            context_settings=context_settings,
        )
        with self._lock:
            if self._state is not EngineState.RUNNING:
                raise RuntimeError(f"engine cannot submit from {self._state.value!r}")
            runtime = self._require_runtime()
            runtime.gateway.reset_idle_state()
            try:
                context_id = runtime.registry.register(
                    artifacts=artifacts,
                    configs=configs,
                    context_settings=context_settings,
                )
                context = runtime.registry.get_context(context_id)
            except BaseException as failure:
                # Public argument errors are rejected above. An exception after
                # entering the registry is therefore a runtime/module failure:
                # preserve it for debugging and start the unified shutdown.
                self.report_failure(failure)
                raise
            if self._state is EngineState.RUNNING:
                self._activity = (
                    RuntimeActivity.IDLE
                    if context.is_rejected and not runtime.registry.active_contexts()
                    else RuntimeActivity.ACTIVE
                )
            failure = self._failure

        if failure is not None:
            raise failure
        return context_id

    def get(self, context_id: int) -> ContextSnapshot | None:
        context, _ = self._get_context_for_inspection(context_id)
        if context is None:
            return None
        return context._snapshot()

    def wait(
        self,
        context_id: int,
        *,
        state: ContextState | None = None,
        timeout: int | float | None = None,
    ) -> ContextSnapshot | None:
        self._validate_wait_state(state)
        self._validate_timeout(timeout)
        context, on_runtime_loop = self._get_context_for_inspection(context_id)
        if context is None:
            return None
        snapshot = context._snapshot()
        if context._matches_wait(snapshot.state, state, snapshot.finalized):
            return snapshot
        if on_runtime_loop:
            raise RuntimeError(
                "synchronous context waiting cannot block the runtime loop; "
                "use wait_async instead"
            )
        return context._wait(state=state, timeout=timeout)

    async def wait_async(
        self,
        context_id: int,
        *,
        state: ContextState | None = None,
        timeout: int | float | None = None,
    ) -> ContextSnapshot | None:
        self._validate_wait_state(state)
        self._validate_timeout(timeout)
        context, _ = self._get_context_for_inspection(context_id)
        if context is None:
            return None
        return await context._wait_async(state=state, timeout=timeout)

    def delete(self, context_id: int) -> bool:
        self._validate_context_id(context_id)
        with self._lock:
            runtime = self._runtime
            if runtime is None:
                return False
            return runtime.registry.delete_context(context_id)

    def prune(self, *, limit: int | None = None) -> tuple[int, ...]:
        self._validate_prune_limit(limit)
        with self._lock:
            runtime = self._runtime
            if runtime is None:
                return ()
            return runtime.registry.prune_contexts(limit=limit)

    def shutdown(
        self,
        forced: bool = False,
        timeout: int | float | None = None,
    ) -> None:
        self._validate_forced(forced)
        self._validate_timeout(timeout)

        while True:
            with self._lock:
                if self._state is EngineState.STARTING:
                    startup_complete = self._startup_complete
                else:
                    startup_complete = None

                if startup_complete is None:
                    if self._state is EngineState.CREATED:
                        self._state = EngineState.STOPPED
                        return
                    if self._state is EngineState.STOPPED:
                        return
                    if self._state is EngineState.FAILED and (
                        self._runtime is None or self._shutdown_started
                    ):
                        self._raise_failure()
                    if self._shutdown_started:
                        runtime = self._runtime
                        if runtime is not None and runtime.loop.is_current_loop_thread:
                            raise RuntimeError(
                                "synchronous shutdown cannot wait on the runtime "
                                "loop; use shutdown_async instead"
                            )
                        shutdown_complete = self._shutdown_complete
                        owner = False
                    else:
                        runtime = self._require_runtime()
                        if runtime.loop.is_current_loop_thread:
                            raise RuntimeError(
                                "synchronous shutdown cannot run on the runtime "
                                "loop; use shutdown_async instead"
                            )
                        self._shutdown_started = True
                        self._shutdown_complete.clear()
                        self._state = EngineState.STOPPING
                        shutdown_complete = self._shutdown_complete
                        owner = True
                    break

            startup_complete.wait()

        if not owner:
            shutdown_complete.wait()
            self._raise_failure()
            return

        with self._lifecycle_lock:
            self._execute_shutdown(
                runtime=runtime,
                forced=forced,
                timeout=timeout,
                emergency=False,
            )

        self._raise_failure()

    async def shutdown_async(
        self,
        forced: bool = False,
        timeout: int | float | None = None,
    ) -> None:
        with self._lock:
            runtime = self._runtime
            if (
                runtime is not None
                and runtime.loop.owns_loop
                and runtime.loop.is_current_loop_thread
            ):
                raise RuntimeError(
                    "an engine-owned runtime loop cannot shut itself down"
                )
        await asyncio.to_thread(
            self.shutdown,
            forced=forced,
            timeout=timeout,
        )

    def report_failure(self, failure: BaseException) -> None:
        if not isinstance(failure, BaseException):
            raise TypeError("failure must be a BaseException")

        start_shutdown = False
        with self._lock:
            self._record_failure_locked(failure)
            if self._state is EngineState.STOPPED:
                self._state = EngineState.FAILED
                self._shutdown_complete.set()
                return
            if self._state is EngineState.RUNNING and not self._shutdown_started:
                self._shutdown_started = True
                self._shutdown_complete.clear()
                self._state = EngineState.STOPPING
                start_shutdown = True

        if not start_shutdown:
            return

        thread = threading.Thread(
            target=self._shutdown_after_failure,
            name="engine-supervisor",
            daemon=True,
        )
        with self._lock:
            self._failure_shutdown_thread = thread
        try:
            thread.start()
        except BaseException as thread_failure:
            with self._lock:
                self._record_cleanup_failure_locked(thread_failure)
                self._state = EngineState.FAILED
                self._shutdown_started = False
                self._shutdown_complete.set()

    def _shutdown_after_failure(self) -> None:
        try:
            with self._lifecycle_lock:
                with self._lock:
                    runtime = self._runtime
                self._execute_shutdown(
                    runtime=runtime,
                    forced=True,
                    timeout=None,
                    emergency=False,
                )
        except BaseException as failure:
            with self._lock:
                self._record_cleanup_failure_locked(failure)
                self._state = EngineState.FAILED
                self._shutdown_started = self._runtime is None
                self._shutdown_complete.set()

    def _execute_shutdown(
        self,
        runtime: EngineRuntime | None,
        forced: bool,
        timeout: int | float | None,
        emergency: bool,
    ) -> None:
        coordinated = False

        # The supervisor first uses the coordinator while it is trustworthy.
        # Any coordination failure falls through to the same emergency cleanup
        # path used for partial startup and failed runtime infrastructure.
        if runtime is not None and not emergency:
            try:
                coordinated = self._coordinate_shutdown(
                    runtime=runtime,
                    forced=forced or self.failure is not None,
                    timeout=timeout,
                )
            except BaseException as failure:
                self._record_cleanup_failure(failure)

        if runtime is not None and not coordinated:
            try:
                self._run_runtime_coroutine(
                    runtime,
                    runtime.prepare_emergency_shutdown(),
                )
            except BaseException as failure:
                self._record_cleanup_failure(failure)

        if runtime is not None:
            self._close_runtime(runtime, emergency=not coordinated)

        with self._lock:
            self._activity = RuntimeActivity.IDLE
            self._state = (
                EngineState.FAILED if self._failure is not None else EngineState.STOPPED
            )
            self._shutdown_complete.set()

    def _coordinate_shutdown(
        self,
        runtime: EngineRuntime,
        forced: bool,
        timeout: int | float | None,
    ) -> bool:
        if not runtime.loop.coordinator_available:
            return False

        # This establishes the shutdown boundary before the coordinator command:
        # delayed control messages are cancelled and no new submissions can pass
        # the supervisor's state check.
        failure_revision = runtime.gateway.prepare_shutdown()
        runtime.loop.cancel_scheduled_messages()
        runtime.messenger.submit(
            ShutdownRuntimeCommand(
                forced=forced,
                identity=self._identity,
            )
        )

        grace_timeout = (
            timeout if not forced or timeout is not None else self._FORCED_ACK_TIMEOUT
        )
        if runtime.gateway.wait_until_shutdown_ready(
            grace_timeout,
            failure_revision,
        ):
            return True

        if runtime.gateway.shutdown_ready:
            return True
        if not runtime.loop.coordinator_available:
            return False
        if forced:
            return False

        # A graceful timeout or a new runtime failure escalates exactly once to
        # abort. Another failure while aborting switches to emergency cleanup.
        failure_revision = runtime.gateway.failure_revision
        try:
            runtime.messenger.submit(
                ShutdownRuntimeCommand(
                    forced=True,
                    identity=self._identity,
                )
            )
        except RuntimeError:
            if runtime.gateway.shutdown_ready:
                return True
            raise
        return runtime.gateway.wait_until_shutdown_ready(
            self._FORCED_ACK_TIMEOUT,
            failure_revision,
        )

    def _close_runtime(self, runtime: EngineRuntime, emergency: bool) -> None:
        # Module shutdown is best-effort and dependency ordered. Runtime-loop
        # closure is attempted even when one or more module cleanups fail.
        try:
            self._run_runtime_coroutine(
                runtime,
                runtime.close(emergency=emergency),
            )
        except BaseException as failure:
            self._record_cleanup_failure(failure)

        try:
            runtime.loop.close(timeout=self._CLEANUP_TIMEOUT)
        except BaseException as failure:
            self._record_cleanup_failure(failure)

        with self._lock:
            if self._runtime is runtime:
                self._runtime = None

    def _run_runtime_coroutine(
        self,
        runtime: EngineRuntime,
        coroutine: Coroutine[object, object, object],
    ) -> object:
        if runtime.loop.loop_available:
            try:
                future = runtime.loop.run_coroutine(coroutine)
            except BaseException:
                coroutine.close()
                raise
            try:
                return future.result(timeout=self._CLEANUP_TIMEOUT)
            except TimeoutError as failure:
                future.cancel()
                raise TimeoutError(
                    "runtime cleanup coroutine did not finish in time"
                ) from failure
        return self._run_coroutine_in_thread(
            coroutine,
            timeout=self._CLEANUP_TIMEOUT,
        )

    @staticmethod
    def _run_coroutine_in_thread(
        coroutine: Coroutine[object, object, object],
        timeout: float,
    ) -> object:
        result: list[object] = []
        failures: list[BaseException] = []

        def run() -> None:
            try:
                result.append(asyncio.run(coroutine))
            except BaseException as failure:
                failures.append(failure)

        thread = threading.Thread(
            target=run,
            name="engine-emergency-cleanup",
            daemon=True,
        )
        try:
            thread.start()
        except BaseException:
            coroutine.close()
            raise
        thread.join(timeout)
        if thread.is_alive():
            raise TimeoutError("emergency cleanup coroutine did not finish in time")
        if failures:
            raise failures[0]
        return result[0] if result else None

    def _mark_idle(self) -> None:
        with self._lock:
            if self._state is EngineState.RUNNING:
                self._activity = RuntimeActivity.IDLE

    def _record_failure(self, failure: BaseException) -> None:
        with self._lock:
            self._record_failure_locked(failure)

    def _record_failure_locked(self, failure: BaseException) -> None:
        if self._failure is None:
            self._failure = failure
            return
        if failure is not self._failure:
            self._secondary_failures.append(failure)

    def _record_cleanup_failure(self, failure: BaseException) -> None:
        with self._lock:
            self._record_cleanup_failure_locked(failure)

    def _record_cleanup_failure_locked(self, failure: BaseException) -> None:
        self._cleanup_failures.append(failure)
        if self._failure is None:
            self._failure = failure
            return
        if failure is not self._failure:
            self._failure.add_note(f"engine cleanup also failed: {failure!r}")

    def _require_runtime(self) -> EngineRuntime:
        if self._runtime is None:
            raise RuntimeError("engine runtime is unavailable")
        return self._runtime

    def _get_context_for_inspection(
        self,
        context_id: int,
    ) -> tuple[ContextInstance | None, bool]:
        self._validate_context_id(context_id)
        with self._lock:
            runtime = self._runtime
            if runtime is None:
                return None, False
            context = runtime.registry.find_context(context_id)
            return context, runtime.loop.is_current_loop_thread

    def _raise_failure(self) -> None:
        with self._lock:
            failure = self._failure
        if failure is not None:
            raise failure

    @staticmethod
    def _validate_forced(forced: bool) -> None:
        if not isinstance(forced, bool):
            raise TypeError("forced must be a bool")

    @staticmethod
    def _validate_timeout(timeout: int | float | None) -> None:
        if isinstance(timeout, bool) or not isinstance(
            timeout,
            (int, float, type(None)),
        ):
            raise TypeError("timeout must be int, float, or None")
        if timeout is not None and (timeout < 0 or not math.isfinite(timeout)):
            raise ValueError("timeout must be finite and non-negative")

    @staticmethod
    def _validate_wait_state(state: ContextState | None) -> None:
        if state is not None and not isinstance(state, ContextState):
            raise TypeError("state must be a ContextState instance or None")

    @staticmethod
    def _validate_context_id(context_id: int) -> None:
        if type(context_id) is not int:
            raise TypeError("context_id must be int")

    @staticmethod
    def _validate_prune_limit(limit: int | None) -> None:
        if isinstance(limit, bool) or not isinstance(limit, (int, type(None))):
            raise TypeError("limit must be an int or None")
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")

    @staticmethod
    def _validate_submission(
        artifacts: ArtifactContext,
        configs: ConfigContext | None,
        context_settings: ContextSettings | None,
    ) -> None:
        if not isinstance(artifacts, ArtifactContext):
            raise TypeError("artifacts must be an ArtifactContext instance")
        if configs is not None and not isinstance(configs, ConfigContext):
            raise TypeError("configs must be a ConfigContext instance or None")
        if context_settings is not None and not isinstance(
            context_settings,
            ContextSettings,
        ):
            raise TypeError(
                "context_settings must be a ContextSettings instance or None"
            )

    @property
    def state(self) -> EngineState:
        with self._lock:
            return self._state

    @property
    def activity(self) -> RuntimeActivity:
        with self._lock:
            return self._activity

    @property
    def failure(self) -> BaseException | None:
        with self._lock:
            return self._failure

    @property
    def secondary_failures(self) -> tuple[BaseException, ...]:
        with self._lock:
            return tuple(self._secondary_failures)

    @property
    def cleanup_failures(self) -> tuple[BaseException, ...]:
        with self._lock:
            return tuple(self._cleanup_failures)
