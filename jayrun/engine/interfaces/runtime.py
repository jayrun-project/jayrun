from ..context_run import (
    ContextRun,
    _wait_context_runs,
    _wait_context_runs_async,
)
from ..registry.context_state import ContextState
from .services.accesses import RuntimeAccess


class RuntimeInterface:
    """Access graph-scoped context runs from a supervising context.

    Visibility is established at submission with ``supervises=...``. The returned
    runs expose the same observation, waiting, and control API as runs held outside
    the engine.
    """

    def __init__(
        self,
        runtime_access: RuntimeAccess,
    ) -> None:
        self._runtime_access = runtime_access

    def wait(
        self,
        runs: ContextRun | tuple[ContextRun, ...],
        state: ContextState | None = None,
        *,
        timeout: int | float | None = None,
    ) -> ContextRun | tuple[ContextRun, ...]:
        """Synchronously wait for one or more visible context runs.

        The behavior and validation are identical to :meth:`jayrun.Engine.wait`.
        """
        return _wait_context_runs(runs, state, timeout=timeout)

    async def wait_async(
        self,
        runs: ContextRun | tuple[ContextRun, ...],
        state: ContextState | None = None,
        *,
        timeout: int | float | None = None,
    ) -> ContextRun | tuple[ContextRun, ...]:
        """Asynchronously wait for one or more visible context runs.

        The behavior and validation are identical to
        :meth:`jayrun.Engine.wait_async`.
        """
        return await _wait_context_runs_async(runs, state, timeout=timeout)

    @property
    def contexts(self) -> tuple[ContextRun, ...]:
        """Non-terminal runs whose graphs this context supervises."""
        return self._runtime_access.contexts()

    @property
    def active_contexts(self) -> tuple[ContextRun, ...]:
        """Visible runs in active or draining states."""
        return self._runtime_access.active_contexts()

    @property
    def paused_contexts(self) -> tuple[ContextRun, ...]:
        """Visible contexts currently paused."""
        return self._runtime_access.paused_contexts()
