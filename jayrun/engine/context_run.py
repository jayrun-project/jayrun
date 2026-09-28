from __future__ import annotations

import asyncio
import math
from time import monotonic
from typing import Self, TYPE_CHECKING

from ..core.artifact.base import Artifact
from ..core.artifact.context import ArtifactContext
from ..core.config.context import ConfigContext
from ..core.graph.definition.artifact import ArtifactDefinition
from ..core.graph.graph_definition import GraphDefinition
from .artifact.result import ArtifactResult
from .interfaces.services.control import ContextControlService
from .interfaces.services.context import ContextService
from .interfaces.context_record import ContextRecord
from .progress import ProgressSnapshot
from .recorders.context.report import ContextReport
from .registry.context_instance import ContextInstance
from .registry.context_state import ContextState
from .snapshot import ContextSnapshot


if TYPE_CHECKING:
    from ..visualization._facade import Plot
    from ..reporting._completed import _RunReporter


class ContextNotTerminatedError(RuntimeError):
    """Raised when terminal context data is requested before termination."""


class ContextRun:
    """Observe and control one submitted context throughout its lifetime.

    A run is returned by :meth:`jayrun.Engine.submit` or exposed through a
    supervising graph's ``self.runtime`` interface. It is awaitable, remains
    usable after the engine releases the execution context, and resolves in
    place rather than producing a separate result object. Its submission
    contexts are read-only views; terminal reports and artifact results become
    available when :attr:`done` becomes ``True``.
    """

    __slots__ = (
        "_context",
        "_context_service",
        "_control_service",
        "_reporter",
    )

    def __init__(
        self,
        *,
        context: ContextInstance,
        context_service: ContextService,
        control_service: ContextControlService,
    ) -> None:
        self._context = context
        self._context_service = context_service
        self._control_service: ContextControlService | None = control_service
        from ..reporting._completed import _RunReporter
        self._reporter = _RunReporter(self)

    @property
    def graph(self) -> GraphDefinition:
        """Exact graph object submitted for this context.

        Object identity is the local boundary for a scoped
        :class:`~jayrun.Supervisor`. When the engine has a graph registry, the
        registered key and version form that boundary instead.
        """
        return self._context.graph

    @property
    def context_id(self) -> int:
        """Probabilistically unique 62-bit identity of this logical context.

        The compact non-negative integer fits signed 64-bit systems. Treat it
        as an opaque correlation value rather than deriving application data
        from it.
        """
        return self._context.context_id

    @property
    def engine_id(self) -> str:
        """Unique engine incarnation currently assigned to this context.

        The value combines the owning engine's human-readable name and compact
        UUID. Jayrun treats it as an opaque routing identity, not an address or
        security credential.
        """
        return self._context.engine_id

    @property
    def artifact_context(self) -> ArtifactContext:
        """Read-only artifact context captured at submission.

        The artifact policy may clear entry values after execution; terminal
        outputs are exposed separately through :meth:`artifact`.
        """
        return self._context.submitted_artifact_context

    @property
    def config_context(self) -> ConfigContext:
        """Read-only configuration context captured at submission."""
        return self._context.submitted_config_context

    @property
    def state(self) -> ContextState:
        """Current publicly observable lifecycle state."""
        return self._context.observed_state

    @property
    def iteration_count(self) -> int:
        """Number of graph iterations that have started."""
        return self._context.iteration_count

    @property
    def progress(self) -> ProgressSnapshot:
        """Latest immutable factual and estimated progress snapshot.

        Reading this property does not emit an event or update profiling history.
        Live step reports refine only this run's estimate. Durable history learns
        once at finite-context finalization or at completed iteration boundaries
        for an unbounded context. Estimates can move backward as routing and
        execution behavior become known.
        """
        return self._context.progress

    def snapshot(self) -> ContextSnapshot:
        """Capture the complete immutable state currently known for this context.

        The snapshot contains no runtime capability or transport. It can be
        serialized with an application-selected codec. Applying it to another
        engine requires a registered graph with complete boundary serializers.
        Capturing it emits no event and does not update progress history.
        """
        return self._context.snapshot

    @property
    def done(self) -> bool:
        """Whether terminal reporting and retained artifacts are available."""
        return self._context.finalized

    def wait(
        self,
        state: ContextState | None = None,
        *,
        timeout: int | float | None = None,
    ) -> Self:
        """Synchronously wait for a state or for context termination.

        When ``state`` is supplied, waiting also ends if the context terminates
        before reaching that state. When omitted, waiting ends only after the
        terminal report and artifact results are available.

        Args:
            state: Exact non-terminal state to observe, or ``None`` to wait for
                termination.
            timeout: Maximum seconds to wait, or ``None`` for no timeout.

        Returns:
            This context run.

        Raises:
            TimeoutError: If the timeout expires.
            RuntimeError: If the call would block an event loop in the current
                thread.
        """
        self._validate_wait(state=state, timeout=timeout)
        if self._context._wait_ready(state):
            return self
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError(
                "synchronous context waiting cannot block an event loop; "
                "use wait_async or await the ContextRun instead"
            )
        self._context._wait(state=state, timeout=timeout)
        return self

    async def wait_async(
        self,
        state: ContextState | None = None,
        *,
        timeout: int | float | None = None,
    ) -> Self:
        """Asynchronously wait for a state or for context termination.

        When ``state`` is supplied, waiting also ends if the context terminates
        before reaching that state. When omitted, waiting ends only after the
        terminal report and artifact results are available.

        Args:
            state: Exact non-terminal state to observe, or ``None`` to wait for
                termination.
            timeout: Maximum seconds to wait, or ``None`` for no timeout.

        Returns:
            This context run.

        Raises:
            TypeError: If an argument has an unsupported type.
            ValueError: If ``state`` is terminal or ``timeout`` is invalid.
            TimeoutError: If the timeout expires.
        """
        self._validate_wait(state=state, timeout=timeout)
        await self._context._wait_async(state=state, timeout=timeout)
        return self

    def abort(self) -> None:
        """Prevent further dispatch and drain the context toward ``ABORTED``.

        The request crosses the runtime message boundary and may not be visible
        immediately. Calling this method on a terminal run has no effect.

        Raises:
            RuntimeError: If this run no longer has authority to control an active
                context.
        """
        control_service = self._control_service_for_control()
        if control_service is not None:
            control_service.abort()

    def stop(self) -> None:
        """Prevent another graph iteration after accepted work drains.

        For a queued context, stopping can finalize it without starting work. For
        a running iterative context, the current iteration completes and the run
        finishes normally in ``FINISHED``; failure or abort keeps its actual
        outcome. Acceptance records ``stop_requested`` in the snapshot/report
        and publishes ``ContextStopRequested`` without replacing the live state.
        Zero iterations means no execution began, even when the outcome is
        ``FINISHED``. A paused context resumes so its accepted iteration can
        drain; subsequent pause/resume remains possible, but cannot clear Stop
        or begin another iteration. Terminal calls have no effect.

        Raises:
            RuntimeError: If this run no longer has authority to control an active
                context.
        """
        control_service = self._control_service_for_control()
        if control_service is not None:
            control_service.stop()

    def pause(
        self,
        duration_seconds: int | float | None = None,
    ) -> None:
        """Pause at a scheduling boundary, optionally resuming after a delay.

        Args:
            duration_seconds: Non-negative automatic-resume delay, or ``None`` for
                an indefinite pause that requires :meth:`resume`.

        Raises:
            TypeError: If ``duration_seconds`` is not numeric or ``None``.
            ValueError: If ``duration_seconds`` is negative or not finite.
            RuntimeError: If this run no longer has authority to control an active
                context.
        """
        self._validate_duration(duration_seconds)
        control_service = self._control_service_for_control()
        if control_service is not None:
            control_service.pause(
                duration_seconds=duration_seconds,
            )

    def resume(self) -> None:
        """Resume this context when it is paused.

        Calling this method when the run is not paused has no effect.

        Raises:
            RuntimeError: If this run no longer has authority to control an active
                context.
        """
        control_service = self._control_service_for_control()
        if control_service is not None:
            control_service.resume()

    def transfer(self, target_engine_id: str) -> None:
        """Assign this context to an engine incarnation.

        Pass :attr:`jayrun.Engine.engine_id` externally or ``self.runtime.engine_id``
        from a controlling context. For a context waiting in ``ROUTING``, passing
        its current local target_engine_id admits it locally without changing ownership;
        passing another target_engine_id assigns that owner and advances the generation.
        An addressed queued snapshot starts automatically when applied by the
        target engine. Authority-bearing contexts cannot be transferred. A
        locally executing context must first reach a safe boundary; a non-local
        context can be reassigned from its last synchronized completed-iteration
        checkpoint.

        Args:
            target_engine_id: Unique target engine-incarnation string.

        Raises:
            TypeError: If ``target_engine_id`` is not a string.
            ValueError: If ``target_engine_id`` is empty or the context state is unsafe.
            RuntimeError: If control expired or the context carries authority.
        """
        if not isinstance(target_engine_id, str):
            raise TypeError("target_engine_id must be a string")
        if not target_engine_id.strip():
            raise ValueError("target_engine_id must not be empty")
        if target_engine_id.strip() == "self":
            raise ValueError(
                "target_engine_id must be an engine.engine_id value, not 'self'"
            )
        if self._context.is_supervising:
            raise RuntimeError("authority-bearing contexts cannot be transferred")
        if self.state.is_terminal:
            raise ValueError("terminal contexts cannot be transferred")
        if (
            self._context.is_local
            and target_engine_id != self.engine_id
            and self.state not in {
                ContextState.ROUTING,
                ContextState.QUEUED,
            }
        ):
            raise ValueError(
                "a locally executing context cannot be transferred; "
                "wait for a safe queued boundary"
            )
        if not self._context._is_local_engine(target_engine_id):
            if not isinstance(self._context.graph_scope, tuple):
                raise RuntimeError(
                    "remote transfer requires a registered graph key"
                )
            if not self.graph._has_complete_boundary_serializers:
                raise RuntimeError(
                    "remote transfer requires graph boundary serializers"
                )
        control_service = self._control_service_for_control()
        if control_service is not None:
            control_service.transfer(target_engine_id)

    @property
    def plot(self) -> Plot:
        """Show or save a finalized run using the shared offline graph viewer."""
        self._require_terminated()
        from ..visualization._facade import Plot
        from ..visualization.adapters.completed import completed_payload
        return Plot(lambda: completed_payload(self))

    @property
    def report(self) -> _RunReporter:
        """Finalized formatter; ``data`` exposes the immutable ContextReport.

        Raises:
            ContextNotTerminatedError: If the context has not terminated.

        Returns:
            The sole formatter for this finalized context.
        """
        self._require_terminated()
        return self._reporter

    def artifact(
        self,
        reference: int | ArtifactDefinition | Artifact,
    ) -> ArtifactResult:
        """Return a finalized artifact result.

        Args:
            reference: Graph-local artifact ID, inspected definition, or artifact
                declaration.

        Raises:
            ContextNotTerminatedError: If the context has not terminated.
            KeyError: If the reference is unknown or artifact reporting is
                unavailable, such as for a rejected submission.
            TypeError: If the reference type is unsupported.

        Returns:
            Final data, placement, and lifecycle records for the artifact. A
            cleared or non-retained payload has value ``None``.
        """
        self._require_terminated()
        return self._context._artifact_result(reference)

    def records(self, key: str) -> tuple[ContextRecord, ...]:
        """Return retained context records in commit order, or () for an unknown key.

        The immutable tuple is reused until this key changes. Its sequence numbers
        are stable identities, not tuple indexes; history may have been pruned.
        """
        return self._context_service.records(key)

    def __await__(self):
        """Wait asynchronously for finalization and return this run."""
        return self.wait_async().__await__()

    def __repr__(self) -> str:
        return (
            f"ContextRun(context_id={self.context_id!r}, "
            f"state={self.state.value!r}, graph={self.graph!r})"
        )

    def _control_service_for_control(self) -> ContextControlService | None:
        if self._context.is_terminal:
            return None
        control_service = self._control_service
        if control_service is None:
            raise RuntimeError("context control is no longer available")
        return control_service

    def _detach_control(self) -> None:
        self._control_service = None

    def _require_terminated(self) -> None:
        if not self._context.finalized:
            raise ContextNotTerminatedError(
                f"context {self.context_id!r} has not terminated"
            )

    @staticmethod
    def _validate_wait(
        state: ContextState | None,
        timeout: int | float | None,
    ) -> None:
        if state is not None and not isinstance(state, ContextState):
            raise TypeError("state must be a ContextState instance or None")
        if state is not None and state.is_terminal:
            raise ValueError("state must be non-terminal; omit it for termination")
        if isinstance(timeout, bool) or not isinstance(
            timeout,
            (int, float, type(None)),
        ):
            raise TypeError("timeout must be int, float, or None")
        if timeout is not None and (timeout < 0 or not math.isfinite(timeout)):
            raise ValueError("timeout must be finite and non-negative")

    @staticmethod
    def _validate_duration(duration: int | float | None) -> None:
        if isinstance(duration, bool) or not isinstance(
            duration,
            (int, float, type(None)),
        ):
            raise TypeError("duration_seconds must be int, float, or None")
        if duration is not None and (
            duration < 0 or not math.isfinite(duration)
        ):
            raise ValueError("duration_seconds must be finite and non-negative")

_ContextRuns = ContextRun | tuple[ContextRun, ...]


def _wait_context_runs(
    runs: _ContextRuns,
    state: ContextState | None = None,
    *,
    timeout: int | float | None = None,
) -> _ContextRuns:
    normalized = _normalize_context_runs(runs)
    ContextRun._validate_wait(state=state, timeout=timeout)
    deadline = None if timeout is None else monotonic() + timeout

    for run in normalized:
        remaining = None if deadline is None else max(deadline - monotonic(), 0)
        run.wait(state, timeout=remaining)

    return runs


async def _wait_context_runs_async(
    runs: _ContextRuns,
    state: ContextState | None = None,
    *,
    timeout: int | float | None = None,
) -> _ContextRuns:
    normalized = _normalize_context_runs(runs)
    ContextRun._validate_wait(state=state, timeout=timeout)
    if not normalized:
        return runs
    if isinstance(runs, ContextRun):
        return await runs.wait_async(state, timeout=timeout)

    waiting = asyncio.gather(
        *(run.wait_async(state) for run in normalized)
    )
    try:
        await asyncio.wait_for(waiting, timeout=timeout)
    except TimeoutError:
        context_ids = tuple(run.context_id for run in normalized)
        raise TimeoutError(
            f"timed out waiting for contexts {context_ids!r}"
        ) from None
    return runs


def _normalize_context_runs(runs: _ContextRuns) -> tuple[ContextRun, ...]:
    if isinstance(runs, ContextRun):
        return (runs,)
    if not isinstance(runs, tuple):
        raise TypeError("runs must be a ContextRun or tuple of ContextRun")
    if any(not isinstance(run, ContextRun) for run in runs):
        raise TypeError("runs must contain only ContextRun instances")
    return runs
