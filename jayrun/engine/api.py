from __future__ import annotations

import asyncio
from base64 import urlsafe_b64encode
from uuid import uuid4
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..persistence import Database

from ..authority import Controller, Supervisor
from ..core.artifact.context import ArtifactContext
from ..core.config.context import ConfigContext
from ..core.graph.graph_definition import GraphDefinition
from ..core.graph.graph_registry import GraphRegistry
from ..core.graph.inspection.registry import GraphIdentity
from .context_run import (
    ContextRun,
    _wait_context_runs,
    _wait_context_runs_async,
)
from .engine_state import EngineState, RuntimeActivity
from .observation import ContextObserver
from .pressure import PressureSnapshot
from .registry.context_state import ContextState
from .settings.context import ContextSettings
from .settings.engine import EngineSettings
from .snapshot import ContextSnapshot
from .terminal_history import TerminalCursor, TerminalHistoryPage
from .supervisor import EngineSupervisor


def _new_engine_id(name: str) -> str:
    token = urlsafe_b64encode(uuid4().bytes).decode("ascii").rstrip("=")
    return f"{name}@{token}"


class Engine:
    """Run artifact graphs and return stable handles to their contexts.

    An engine owns its worker pool, runtime loop, resource cache, and placement
    capacity. :meth:`submit` accepts an explicit graph and graph-independent
    artifact and configuration builders. It returns a
    :class:`~jayrun.context.ContextRun` that remains usable after execution
    finishes. Use the engine as a context manager for deterministic synchronous
    shutdown, or call :meth:`shutdown_async` when the engine shares an application
    event loop.

    Args:
        settings: Optional runtime settings. Defaults to
            :class:`~jayrun.settings.EngineSettings`.
        graph_registry: Optional graph registry. When supplied, submissions and
            scoped authority declarations must use graphs registered in it.
        database: Optional managed context/session and timing-profile persistence. None disables
            durable capture; constructing the engine performs no storage I/O.
            Enabled synchronous start,
            submit and apply must run outside an event-loop thread; async callers
            can use asyncio.to_thread and the existing async wait/shutdown APIs.
        name: Human-readable engine name. Every engine incarnation appends a
            compact UUID to this name for its unique :attr:`engine_id` value.
    """

    def __init__(
        self,
        settings: EngineSettings | None = None,
        graph_registry: GraphRegistry | None = None,
        *,
        name: str = "self",
        database: Database | None = None,
    ) -> None:
        if not isinstance(name, str):
            raise TypeError("name must be a string")
        name = name.strip()
        if not name:
            raise ValueError("name must not be empty")
        if settings is None:
            settings = EngineSettings()
        if not isinstance(settings, EngineSettings):
            raise TypeError("settings must be an EngineSettings instance")
        if graph_registry is not None and not isinstance(
            graph_registry,
            GraphRegistry,
        ):
            raise TypeError("graph_registry must be a GraphRegistry or None")
        if database is not None:
            from ..persistence import Database
            if not isinstance(database, Database):
                raise TypeError("database must be a Database instance or None")
        self._database = database
        self._name = name
        self._engine_id = _new_engine_id(name)
        self._graph_registry = graph_registry
        self._supervisor = EngineSupervisor(
            settings=settings,
            name=self._name,
            engine_id=self._engine_id,
            graph_registry=graph_registry,
            database=database,
        )

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
        graph: GraphDefinition | GraphIdentity,
        artifacts: ArtifactContext | None = None,
        configs: ConfigContext | None = None,
        *,
        settings: ContextSettings | None = None,
        authority: Supervisor | Controller | None = None,
    ) -> ContextRun:
        """Submit one execution context and return its live run.

        With local routing, ordinary work is assigned to this engine. With
        controlled routing, it remains in
        ``ContextState.ROUTING`` until an authorized caller
        selects an exact engine using
        :meth:`~jayrun.context.ContextRun.transfer`. Authority-bearing contexts
        always run locally through supervision capacity.

        Args:
            graph: Confirmed graph to execute, or its registered ``(key,
                version)`` identity. A registry identity is the portable form
                used by controlling contexts.
            artifacts: Optional graph-independent builder containing
                entry-artifact values. Omit it when the graph has no required
                entry artifacts.
            configs: Optional graph-independent configuration builder. Omit it
                when the graph has no required configuration fields.
            settings: Optional iteration, retry, and retention settings.
            authority: Optional :class:`~jayrun.Supervisor` or
                :class:`~jayrun.Controller` declaration. A scoped supervisor may
                observe and control contexts of its exact graph objects; an empty
                supervisor and a controller cover every graph.

        Returns:
            A :class:`~jayrun.context.ContextRun` for the submitted context.

        Raises:
            TypeError: If a submission argument has an unsupported type.
            KeyError: If a context contains a declaration outside ``graph``.
            ValueError: If required values are missing or references or authority
                graphs are duplicated.
            RuntimeError: If the engine is not accepting submissions or the graph
                is not ready for execution. Failed submission leaves both caller
                contexts unchanged.
        """
        return self._supervisor.submit(
            graph=graph,
            artifacts=artifacts,
            configs=configs,
            context_settings=settings,
            authority=authority,
        )

    def apply(self, snapshot: ContextSnapshot | PressureSnapshot) -> None:
        """Apply one context snapshot through the local coordinator.

        Jayrun performs no transport. Applications serialize and deliver a
        snapshot however they choose, then call this method on the receiving
        engine. A snapshot with a control request is executed only by the current
        owner; a committed snapshot synchronizes a non-local shadow. When a
        queued snapshot is assigned to this engine's :attr:`engine_id`, applying it
        also admits that context for execution. Stale revisions, duplicate
        requests, and obsolete ownership generations have no effect.

        Fresh work is never submitted through this method. Use :meth:`submit`
        with a graph (or graph key), :class:`~jayrun.ArtifactContext`, and
        :class:`~jayrun.ConfigContext` instead.

        During graceful shutdown, committed updates for contexts already known
        to this engine remain accepted so remote owners can return their final
        snapshots. New contexts and new control requests cannot be introduced
        after shutdown begins.

        Args:
            snapshot: Immutable snapshot received through application-owned
                transport.

        Raises:
            TypeError: If ``snapshot`` is not a context snapshot.
            ValueError: If its graph identity or portable payload is invalid.
            RuntimeError: If the engine is not running or has no graph registry.
        """
        self._supervisor.apply(snapshot)

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

    def terminal_history(self, *, after: TerminalCursor | None = None,
                         limit: int = 256) -> TerminalHistoryPage:
        """Read immutable, payload-free terminal summaries from this incarnation.

        ``after=None`` starts at the beginning of the retained window, reporting
        any earlier loss. Reuse ``next_cursor`` to continue. Bounds and shutdown
        can make data unavailable; no durable or full-report coverage is implied.
        """
        return self._supervisor.terminal_history(after=after, limit=limit)

    def observer(self, *, capacity: int = 256) -> ContextObserver:
        """Create a bounded queue of committed context events.

        The observer yields lifecycle transitions, stored-value notifications,
        transfer changes, and remote control requests. Every event carries the
        atomic :class:`~jayrun.context.ContextSnapshot` current at that boundary.
        Progress alone does not create an event. Both :func:`next` and
        :func:`anext` remove the returned event. An observer that reaches
        ``capacity`` is cleared and detached; its next consumption raises
        :class:`~jayrun.context.ObserverOverflowError`.

        Args:
            capacity: Maximum pending events before the observer overflows.

        Returns:
            A closeable synchronous and asynchronous context observer.

        Raises:
            TypeError: If ``capacity`` is not an integer.
            ValueError: If ``capacity`` is not positive.
            RuntimeError: If the engine is not running or its observer limit has
                been reached.
        """
        return self._supervisor.observer(capacity=capacity)

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

        Graceful shutdown stops future iterations and settles ordinary contexts
        before authority contexts, allowing controllers to finish transporting
        remote snapshots. Authority event queues then close and can drain a
        normal ``for`` or ``async for`` loop. Polling authority loops can use
        ``self.runtime.alive``, which stays true during the ordinary drain and
        becomes false when authority teardown begins. User code already
        executing must still return cooperatively.

        Args:
            forced: Abort live contexts instead of stopping future iterations and
                allowing accepted work to drain.
            timeout: Grace period before an incomplete graceful shutdown
                escalates to forced cleanup. For an already forced shutdown, it
                is the coordinator acknowledgement timeout; ``None`` uses an
                internal bounded acknowledgement wait. ``None`` on graceful
                shutdown waits without a graceful deadline.

        Raises:
            TimeoutError: If a concurrent caller does not observe completion
                within ``timeout``.
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
        when Jayrun uses the application's event loop. It uses the same
        ordinary-first graceful ordering and ``self.runtime.alive``
        cooperative-return boundary.

        Args:
            forced: Abort live contexts instead of stopping future iterations and
                allowing accepted work to drain.
            timeout: Grace period before an incomplete graceful shutdown
                escalates to forced cleanup. For an already forced shutdown, it
                is the coordinator acknowledgement timeout; ``None`` uses an
                internal bounded acknowledgement wait. ``None`` on graceful
                shutdown waits without a graceful deadline.

        Raises:
            TimeoutError: If a concurrent caller does not observe completion
                within ``timeout``.
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
    def database(self) -> Database | None:
        """Configured persistence component, owned from start through shutdown.

        None disables durable recording. wait() still means execution finalization;
        an explicit database.flush()/flush_async() additionally covers registered history
        handoffs. Borrowed readers never receive live control authority.
        """
        return self._database

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
    def graph_registry(self) -> GraphRegistry | None:
        """Graph registry constraining submissions, if one was configured."""
        return self._graph_registry

    @property
    def name(self) -> str:
        """Human-readable name shared by this engine's incarnations."""
        return self._name

    @property
    def engine_id(self) -> str:
        """Unique name and UUID of this engine incarnation.

        A newly constructed engine receives a new value even when it reuses the
        same :attr:`name`. Pass this value to
        :meth:`jayrun.context.ContextRun.transfer` when assigning work here.
        """
        return self._engine_id

    @property
    def pressure(self) -> PressureSnapshot:
        """Current engine-wide scheduling and execution pressure snapshot.

        State counts include only contexts owned by this engine; remote shadows
        remain visible through :attr:`contexts` but do not consume local
        pressure. Sampling pressure does not emit an event or update profiling
        history.

        Raises:
            RuntimeError: If the engine is not running.
        """
        return self._supervisor.pressure

    @property
    def unfinished_contexts(self) -> tuple[ContextRun, ...]:
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
