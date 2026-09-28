from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...persistence import DatabaseReader

from ...core.artifact.context import ArtifactContext
from ...core.config.context import ConfigContext
from ...core.graph.inspection.registry import GraphIdentity
from ..context_run import (
    ContextRun,
    _wait_context_runs,
    _wait_context_runs_async,
)
from ..observation import ContextObserver
from ..pressure import PressureSnapshot
from ..registry.context_state import ContextState
from ..settings.context import ContextSettings
from ..snapshot import ContextSnapshot
from ..terminal_history import TerminalCursor, TerminalHistoryPage
from .services.accesses import RuntimeAccess


class RuntimeInterface:
    """Access graph-scoped context runs from a supervising context.

    Visibility is established at submission with ``authority=Supervisor(...)`` or
    ``authority=Controller()``. The returned runs expose the same observation,
    waiting, and control API as runs held outside the engine.
    """

    def __init__(
        self,
        runtime_access: RuntimeAccess,
    ) -> None:
        self._runtime_access = runtime_access

    @property
    def name(self) -> str:
        """Human-readable name of this context's engine."""
        return self._runtime_access.name

    @property
    def engine_id(self) -> str:
        """Unique name and UUID of this engine incarnation.

        Pass this value to a remote run's
        :meth:`~jayrun.context.ContextRun.transfer` method to reclaim it here.
        """
        return self._runtime_access.engine_id

    @property
    def alive(self) -> bool:
        """Whether this context should continue serving its runtime.

        A graceful engine shutdown first settles ordinary contexts, so this
        remains true for controllers and supervisors during that drain. It
        becomes false when their final shutdown stage begins. For ordinary
        contexts it becomes false when stopping, aborting, failing, or
        finishing begins. Forced shutdown makes it false immediately.

        Use this property as the condition for cooperative polling or service
        loops. Event-driven authority code can instead iterate over
        :attr:`events`, whose queue closes at the same shutdown boundary.
        """
        return self._runtime_access.alive()

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
    def events(self) -> ContextObserver:
        """This authority context's single bounded destructive event queue.

        Repeated access returns the same queue. Both :func:`next` and
        :func:`anext` consume its oldest event. During graceful shutdown the
        queue closes after ordinary work finalizes, allowing a normal ``for`` or
        ``async for`` loop to drain and return. It also closes when the authority
        context finalizes, and raises
        :class:`~jayrun.context.ObserverOverflowError` after overflow.

        Raises:
            PermissionError: If this context has no supervising authority.
        """
        return self._runtime_access.events()

    @property
    def history(self) -> DatabaseReader | None:
        """Borrow the history scope explicitly granted through Controller.

        Ordinary/supervisor contexts are denied. Controller() without a history
        grant returns None, even when its engine records to a Database. A granted
        reader expires with this controller or its source database lifecycle.
        Reads recheck authority before admission and before returning results.
        """
        reader = self._runtime_access.history
        if reader is None:
            raise PermissionError("historical access is unavailable to this runtime interface")
        return reader()

    def terminal_history(self, *, after: TerminalCursor | None = None,
                         limit: int = 256) -> TerminalHistoryPage:
        """Read bounded finalized summaries with current Controller authority.

        This is not an event replay or a full-report store. A gap signals lost
        summaries; an expired grant or another engine's cursor is rejected.
        Supervisor-scoped cursors are deliberately unsupported, to avoid leaking
        hidden activity through global sequence numbers.
        """
        reader = self._runtime_access.terminal_history
        if reader is None:
            raise PermissionError("terminal history is unavailable to this runtime interface")
        return reader(after, limit)

    def apply(self, snapshot: ContextSnapshot | PressureSnapshot) -> None:
        """Apply one portable context snapshot through local authorization.

        For a locally owned context, an embedded request is dispatched through
        the normal coordinator. Committed state, records, reports, progress, and
        artifacts synchronize the local view. A queued snapshot assigned to this
        runtime's :attr:`engine_id` is admitted for execution. Duplicate,
        obsolete-generation, and stale-revision snapshots have no effect.
        During shutdown, committed updates for known contexts remain admissible
        while new contexts and control-request snapshots are rejected.

        Args:
            snapshot: Immutable snapshot received through application-owned
                transport.

        Raises:
            TypeError: If ``snapshot`` has an unsupported type.
            PermissionError: If the target is outside this authority.
            RuntimeError: If the runtime cannot apply the snapshot.
        """
        if not isinstance(snapshot, (ContextSnapshot, PressureSnapshot)):
            raise TypeError("snapshot must be a ContextSnapshot or PressureSnapshot instance")
        self._runtime_access.apply(snapshot)

    def submit(
        self,
        graph_key: GraphIdentity,
        artifacts: ArtifactContext | None = None,
        configs: ConfigContext | None = None,
        *,
        settings: ContextSettings | None = None,
    ) -> ContextRun:
        """Submit ordinary registered-graph work from a controller.

        Submission creates a new logical context from a ``(key, version)`` graph
        identity plus graph-independent artifact and configuration contexts. It
        follows the engine's routing mode and never accepts a snapshot; snapshots
        belong to :meth:`apply`. Runtime submission cannot create a supervisor or
        controller, so authority is intentionally absent from this API.

        Args:
            graph_key: Registered ``(key, version)`` graph identity.
            artifacts: Optional entry-artifact builder context. Omit it for a
                graph without required entry artifacts.
            configs: Optional configuration builder context. Omit it for a graph
                without required configuration fields.
            settings: Optional context execution settings.

        Returns:
            The newly submitted context run.

        Raises:
            PermissionError: If the caller is not a controller.
            RuntimeError: If no graph registry is configured or submission is
                unavailable.
        """
        return self._runtime_access.submit(
            graph_key,
            artifacts,
            configs,
            context_settings=settings,
        )

    def shutdown(self, forced: bool = False) -> None:
        """Request engine shutdown from a controlling context.

        The request is asynchronous because an executing controller cannot wait
        for the runtime that is currently executing it to close. Graceful
        shutdown settles ordinary work before stopping authority contexts;
        :attr:`alive` then becomes false and :attr:`events` closes so both
        polling and event-driven loops can return.

        Args:
            forced: Abort live work instead of stopping future iterations and
                draining accepted work.

        Raises:
            TypeError: If ``forced`` is not a bool.
            PermissionError: If the caller is not a controller.
        """
        if not isinstance(forced, bool):
            raise TypeError("forced must be a bool")
        self._runtime_access.shutdown(forced)

    @property
    def unfinished_contexts(self) -> tuple[ContextRun, ...]:
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

    @property
    def pressure(self) -> PressureSnapshot:
        """Latest authority-scoped runtime pressure snapshot.

        Context-state counts include only work owned by this engine and visible
        to this authority. Sampling pressure does not emit an event or update
        profiling history.
        """
        return self._runtime_access.pressure()

    @property
    def pressures(self) -> tuple[PressureSnapshot, ...]:
        return self._runtime_access.pressures()
