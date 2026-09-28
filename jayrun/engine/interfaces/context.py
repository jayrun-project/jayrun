import math

from ..messages.origin import StepOrigin
from ..recorders.execution.recorder import ExecutionRecorder
from .base import ScopeInterface
from .services.accesses import ContextAccess
from .context_record import ContextRecord


class ContextInterface(ScopeInterface):
    """Inspect and control the currently executing graph context."""

    def __init__(
        self,
        context_access: ContextAccess,
        recorder: ExecutionRecorder,
    ) -> None:
        super().__init__(recorder=recorder)
        self._context_access = context_access

    def records(self, key: str) -> tuple[ContextRecord, ...]:
        """Return context-scoped records for ``key`` in recording order."""
        return self._context_access.records(key)

    def _record(self, record: ContextRecord) -> None:
        self._context_access.record(record, self._origin())

    def abort(self) -> None:
        """Prevent further dispatch and drain this context toward ``ABORTED``."""
        self._context_access.abort(self._origin())

    def stop(self) -> None:
        """Stop iteration after accepted work drains, preventing a next iteration."""
        self._context_access.stop(self._origin())

    def pause(self, duration_seconds: float | None = None) -> None:
        """Request a pause at a controlled scheduling boundary.

        Args:
            duration_seconds: Non-negative automatic-resume delay, or ``None`` to
                require a supervising context to resume this context.
        """
        self._validate_duration(duration_seconds)
        self._context_access.pause(
            self._origin(),
            duration_seconds=duration_seconds,
        )

    def _origin(self) -> StepOrigin:
        return StepOrigin(
            context_id=self.id,
            step_name=self._recorder.step_name,
            step_type=self._recorder.step_kind,
            layout_position=self._recorder.layout_position,
        )

    @staticmethod
    def _validate_duration(duration_seconds: float | None) -> None:
        if isinstance(duration_seconds, bool) or not isinstance(
            duration_seconds,
            (int, float, type(None)),
        ):
            raise TypeError("duration_seconds must be int, float, or None")
        if duration_seconds is not None and (
            duration_seconds < 0 or not math.isfinite(duration_seconds)
        ):
            raise ValueError("duration_seconds must be finite and non-negative")

    @property
    def id(self) -> int:
        """ID of the currently executing context."""
        return self._recorder.context_id
