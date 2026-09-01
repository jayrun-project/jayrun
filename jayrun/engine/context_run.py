from __future__ import annotations

import asyncio
import math
from collections.abc import Hashable
from time import monotonic
from typing import Self

from ..core.artifact.base import Artifact
from ..core.artifact.context import ArtifactContext
from ..core.config.context import ConfigContext
from ..core.graph.definition.artifact import ArtifactDefinition
from ..core.graph.graph_definition import GraphDefinition
from .artifact.result import ArtifactResult
from .interfaces.services.control import ContextControlService
from .interfaces.services.context import ContextService
from .interfaces.value_record import ValueRecord
from .recorders.context.report import ContextReport
from .registry.context_instance import ContextInstance
from .registry.context_state import ContextState
from .registry.identities import BaseIdentity


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
        "_identity",
    )

    def __init__(
        self,
        *,
        context: ContextInstance,
        context_service: ContextService,
        control_service: ContextControlService,
        identity: BaseIdentity,
    ) -> None:
        self._context = context
        self._context_service = context_service
        self._control_service: ContextControlService | None = control_service
        self._identity = identity

    @property
    def graph(self) -> GraphDefinition:
        """Exact graph object submitted for this context.

        Object identity is also the supervision boundary: a supervising graph
        sees runs only for the graph objects supplied through ``supervises``.
        """
        return self._context.graph

    @property
    def context_id(self) -> int:
        """Engine-local context identifier."""
        return self._context.context_id

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
            control_service.abort(self.context_id, self._identity)

    def stop(self) -> None:
        """Prevent another graph iteration after accepted work drains.

        For a queued context, stopping can finalize it without starting work. For
        a running iterative context, the current iteration completes and the run
        terminates in ``STOPPED``. Calling this method on a terminal run has no
        effect.

        Raises:
            RuntimeError: If this run no longer has authority to control an active
                context.
        """
        control_service = self._control_service_for_control()
        if control_service is not None:
            control_service.stop(self.context_id, self._identity)

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
                self.context_id,
                self._identity,
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
            control_service.resume(self.context_id, self._identity)

    @property
    def report(self) -> ContextReport:
        """Terminal context report.

        Raises:
            ContextNotTerminatedError: If the context has not terminated.

        Returns:
            The immutable terminal report for this context.
        """
        self._require_terminated()
        return self._context._report_value()

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

    def has_value(self, key: Hashable) -> bool:
        """Return whether the context has stored a record under ``key``.

        Args:
            key: Hashable key used with ``self.context.store``.
        """
        return self.get_value_record(key) is not None

    def get_value(self, key: Hashable) -> object | None:
        """Return the latest context-stored value under ``key``, if present.

        Use :meth:`has_value` or :meth:`get_value_record` to distinguish a missing
        key from a stored value of ``None``.
        """
        record = self.get_value_record(key)
        return None if record is None else record.value

    def get_values(self, key: Hashable) -> tuple[object, ...]:
        """Return all context-stored values under ``key`` in recording order."""
        return tuple(record.value for record in self.get_value_records(key))

    def get_value_record(self, key: Hashable) -> ValueRecord | None:
        """Return the latest context-stored record under ``key``, if present."""
        records = self.get_value_records(key)
        return None if not records else records[-1]

    def get_value_records(self, key: Hashable) -> tuple[ValueRecord, ...]:
        """Return all context-stored records under ``key`` in recording order.

        Args:
            key: Hashable key used with ``self.context.store``.

        Returns:
            Immutable records containing values and their execution provenance.

        Raises:
            TypeError: If ``key`` is not hashable.
        """
        hash(key)
        return self._context_service.get_records(key)

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
