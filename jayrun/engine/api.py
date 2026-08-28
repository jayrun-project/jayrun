from __future__ import annotations

import asyncio

from ..core.artifact.context import ArtifactContext
from ..core.config.context import ConfigContext
from .engine_state import EngineState, RuntimeActivity
from .registry.context_snapshot import ContextSnapshot
from .registry.context_state import ContextState
from .settings.context import ContextSettings
from .settings.engine import EngineSettings
from .supervisor import EngineSupervisor


class Engine:
    """Submit graphs and supervise their execution contexts.

    An engine owns its worker pool, runtime loop, placement capacity, and retained
    context snapshots. Use it as a context manager for deterministic shutdown.

    Args:
        settings: Optional runtime settings. Defaults to :class:`EngineSettings`.
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
            loop: Optional running event loop to adopt. When omitted, Jayrun owns a
                background runtime loop.
        """
        self._supervisor.start(loop=loop)

    def submit(
        self,
        artifacts: ArtifactContext,
        configs: ConfigContext | None = None,
        context_settings: ContextSettings | None = None,
    ) -> int:
        """Submit one execution context and return its unique ID.

        Args:
            artifacts: Entry-artifact values for the graph.
            configs: Optional configuration values. Omit when the graph has no
                required configuration fields.
            context_settings: Optional iteration, retry, retention, and supervision
                settings for this submission.

        Returns:
            The submitted context ID.
        """
        return self._supervisor.submit(
            artifacts=artifacts,
            configs=configs,
            context_settings=context_settings,
        )

    def get(self, context_id: int) -> ContextSnapshot | None:
        """Return the latest snapshot for a context, or ``None`` if unknown."""
        return self._supervisor.get(context_id)

    def wait(
        self,
        context_id: int,
        *,
        state: ContextState | None = None,
        timeout: int | float | None = None,
    ) -> ContextSnapshot | None:
        """Block until a context reaches a state or the timeout expires.

        When ``state`` is omitted, the wait completes after terminal finalization.
        If the context becomes terminal before a requested non-terminal state is
        observed, its finalized terminal snapshot is returned.

        Args:
            context_id: Context to observe.
            state: Optional exact state to wait for.
            timeout: Maximum seconds to wait, or ``None`` for no timeout.

        Returns:
            The matching snapshot, or ``None`` if the context is unknown.

        Raises:
            TimeoutError: If the wait exceeds ``timeout``.
            RuntimeError: If called from the event loop used by Jayrun.
        """
        return self._supervisor.wait(
            context_id,
            state=state,
            timeout=timeout,
        )

    async def wait_async(
        self,
        context_id: int,
        *,
        state: ContextState | None = None,
        timeout: int | float | None = None,
    ) -> ContextSnapshot | None:
        """Asynchronously wait for a context state.

        This is the non-blocking counterpart of :meth:`wait` and follows the same
        state, timeout, and return-value rules.
        """
        return await self._supervisor.wait_async(
            context_id,
            state=state,
            timeout=timeout,
        )

    def delete(self, context_id: int) -> bool:
        """Delete a finalized context and its retained runtime data.

        Returns:
            ``True`` when the context was deleted, or ``False`` when it was unknown.

        Raises:
            RuntimeError: If the context has not reached terminal finalization.
        """
        return self._supervisor.delete(context_id)

    def prune(self, *, limit: int | None = None) -> tuple[int, ...]:
        """Delete finalized contexts, oldest first.

        Args:
            limit: Maximum number to delete, or ``None`` for every eligible context.

        Returns:
            IDs of the deleted contexts.
        """
        return self._supervisor.prune(limit=limit)

    def shutdown(
        self,
        forced: bool = False,
        timeout: int | float | None = None,
    ) -> None:
        """Shut down the runtime and release its resources.

        Args:
            forced: Abort live contexts instead of allowing graceful completion.
            timeout: Maximum seconds to wait, or ``None`` for no timeout.
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
        """Asynchronously shut down the runtime.

        This is the non-blocking counterpart of :meth:`shutdown`.
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
