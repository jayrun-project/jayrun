from __future__ import annotations

import asyncio

from ..core.artifact.context import ArtifactContext
from ..core.config.context import ConfigContext
from ..core.graph.graph_definition import GraphDefinition
from .context_run import (
    ContextRun,
    _wait_context_runs,
    _wait_context_runs_async,
)
from .engine_state import EngineState, RuntimeActivity
from .registry.context_state import ContextState
from .settings.context import ContextSettings
from .settings.engine import EngineSettings
from .supervisor import EngineSupervisor


class Engine:
    """Run artifact graphs and return stable handles to their contexts.

    An engine owns its worker pool, runtime loop, resource cache, and placement
    capacity. :meth:`submit` accepts graph-bound artifact and configuration
    contexts and returns a :class:`~jayrun.context.ContextRun` that remains usable
    after execution finishes. Use the engine as a context manager for
    deterministic synchronous shutdown, or call :meth:`shutdown_async` when the
    engine shares an application event loop.

    Args:
        settings: Optional runtime settings. Defaults to
            :class:`~jayrun.settings.EngineSettings`.
    """

    def __init__(
        self,
        settings: EngineSettings | None = None,
    ) -> None:
        if settings is None:
            settings = EngineSettings()
        if not isinstance(settings, EngineSettings):
            raise TypeError("settings must be an EngineSettings instance")
        self._supervisor = EngineSupervisor(settings=settings)

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Start the runtime.

        Args:
            loop: Running application event loop to adopt. When omitted, Jayrun
                creates and owns a background event loop.

        Raises:
            RuntimeError: If the engine cannot be started from its current state.
        """
        self._supervisor.start(loop=loop)

    def submit(
        self,
        artifacts: ArtifactContext,
        configs: ConfigContext,
        *,
        context_settings: ContextSettings | None = None,
        supervises: GraphDefinition | tuple[GraphDefinition, ...] = (),
    ) -> ContextRun:
        """Submit one execution context and return its live run.

        Args:
            artifacts: Entry-artifact values for the graph.
            configs: Configuration values for the same graph. An empty
                :class:`ConfigContext` is valid when the graph has no fields.
            context_settings: Optional iteration, retry, and retention settings.
            supervises: Exact graph object, or tuple of graph objects, whose live
                contexts the submitted graph may observe and control through
                ``self.runtime``. The submitted graph becomes a supervisor when
                this argument is non-empty.

        Returns:
            A :class:`~jayrun.context.ContextRun` for the submitted context.

        Raises:
            TypeError: If a submission argument has an unsupported type.
            ValueError: If the contexts do not belong to the same graph or the
                supervision scope is invalid.
            RuntimeError: If the engine is not accepting submissions or the graph
                is not ready for execution.
        """
        return self._supervisor.submit(
            artifacts=artifacts,
            configs=configs,
            context_settings=context_settings,
            supervises=supervises,
        )

    def wait(
        self,
        runs: ContextRun | tuple[ContextRun, ...],
        state: ContextState | None = None,
        *,
        timeout: int | float | None = None,
    ) -> ContextRun | tuple[ContextRun, ...]:
        """Synchronously wait for one or more context runs.

        Waiting without ``state`` ends after every run is finalized, when reports
        and retained artifacts are available. Waiting for a non-terminal state
        also ends if a run terminates before reaching that state. A tuple shares
        one timeout budget and is returned unchanged.

        Args:
            runs: One run or a tuple of runs.
            state: Exact non-terminal state to observe, or ``None`` to wait for
                finalization.
            timeout: Maximum total seconds to wait, or ``None`` for no timeout.

        Returns:
            The same run or tuple supplied by the caller.

        Raises:
            TypeError: If an argument has an unsupported type.
            ValueError: If ``state`` is terminal or ``timeout`` is invalid.
            TimeoutError: If the timeout expires.
            RuntimeError: If called where synchronous waiting would block a
                running event loop.
        """
        return _wait_context_runs(runs, state, timeout=timeout)

    async def wait_async(
        self,
        runs: ContextRun | tuple[ContextRun, ...],
        state: ContextState | None = None,
        *,
        timeout: int | float | None = None,
    ) -> ContextRun | tuple[ContextRun, ...]:
        """Asynchronously wait for one or more context runs.

        This is the non-blocking counterpart of :meth:`wait`. Tuple members wait
        concurrently and share one timeout budget.

        Args:
            runs: One run or a tuple of runs.
            state: Exact non-terminal state to observe, or ``None`` to wait for
                finalization.
            timeout: Maximum total seconds to wait, or ``None`` for no timeout.

        Returns:
            The same run or tuple supplied by the caller.

        Raises:
            TypeError: If an argument has an unsupported type.
            ValueError: If ``state`` is terminal or ``timeout`` is invalid.
            TimeoutError: If the timeout expires.
        """
        return await _wait_context_runs_async(runs, state, timeout=timeout)

    def shutdown(
        self,
        forced: bool = False,
        timeout: int | float | None = None,
    ) -> None:
        """Shut down the runtime and release its resources.

        Args:
            forced: Abort live contexts instead of stopping future iterations and
                allowing accepted work to drain.
            timeout: Maximum seconds to wait, or ``None`` for no timeout.

        Raises:
            TimeoutError: If shutdown does not complete within ``timeout``.
            RuntimeError: If shutdown is requested from an invalid lifecycle state
                or cleanup fails.
        """
        self._supervisor.shutdown(
            forced=forced,
            timeout=timeout,
        )

    async def shutdown_async(
        self,
        forced: bool = False,
        timeout: int | float | None = None,
    ) -> None:
        """Asynchronously shut down the runtime and release its resources.

        This is the non-blocking counterpart of :meth:`shutdown` and is suitable
        when Jayrun uses the application's event loop.

        Args:
            forced: Abort live contexts instead of stopping future iterations and
                allowing accepted work to drain.
            timeout: Maximum seconds to wait, or ``None`` for no timeout.

        Raises:
            TimeoutError: If shutdown does not complete within ``timeout``.
            RuntimeError: If shutdown is requested from an invalid lifecycle state
                or cleanup fails.
        """
        await self._supervisor.shutdown_async(
            forced=forced,
            timeout=timeout,
        )

    def __enter__(self) -> Engine:
        self.start()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object,
    ) -> None:
        try:
            self.shutdown(forced=False)
        except BaseException as shutdown_failure:
            if exception is None:
                raise
            exception.add_note(
                f"engine shutdown also failed: {shutdown_failure!r}"
            )

    @property
    def state(self) -> EngineState:
        """Current engine lifecycle state."""
        return self._supervisor.state

    @property
    def activity(self) -> RuntimeActivity:
        """Whether the running engine is idle or actively processing work."""
        return self._supervisor.activity

    @property
    def failure(self) -> BaseException | None:
        """Primary runtime failure, if the engine failed."""
        return self._supervisor.failure

    @property
    def secondary_failures(self) -> tuple[BaseException, ...]:
        """Additional failures observed after the primary runtime failure."""
        return self._supervisor.secondary_failures

    @property
    def cleanup_failures(self) -> tuple[BaseException, ...]:
        """Failures raised while releasing runtime resources."""
        return self._supervisor.cleanup_failures

    @property
    def contexts(self) -> tuple[ContextRun, ...]:
        """Non-terminal context runs in submission order.

        Completed runs are released from the engine registry. A
        :class:`~jayrun.context.ContextRun` already held by application code remains
        usable for reports, stored values, and retained artifacts.
        """
        return self._supervisor.contexts()

    @property
    def active_contexts(self) -> tuple[ContextRun, ...]:
        """Context runs currently active or draining, in submission order."""
        return self._supervisor.contexts(active_only=True)
