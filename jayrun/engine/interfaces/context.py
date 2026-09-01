import math
from collections.abc import Hashable

from ..recorders.execution.recorder import ExecutionRecorder
from ..registry.identities import StepIdentity
from .base import ScopeInterface
from .services.accesses import ContextAccess
from .value_record import ValueRecord


class ContextInterface(ScopeInterface):
    """Inspect and control the currently executing graph context."""

    def __init__(
        self,
        context_access: ContextAccess,
        recorder: ExecutionRecorder,
    ) -> None:
        super().__init__(recorder=recorder)
        self._context_access = context_access

    def get_value_records(self, key: Hashable) -> tuple[ValueRecord, ...]:
        """Return context-scoped records for ``key`` in recording order."""
        return self._context_access.get_records(key)

    def _store(self, record: ValueRecord) -> None:
        self._context_access.store(record, self._identity())

    def abort(self) -> None:
        """Prevent further dispatch and drain this context toward ``ABORTED``."""
        self._context_access.abort(
            context_id=self.id,
            identity=self._identity(),
        )

    def stop(self) -> None:
        """Stop iteration after accepted work drains, preventing a next iteration."""
        self._context_access.stop(
            context_id=self.id,
            identity=self._identity(),
        )

    def pause(self, duration_seconds: float | None = None) -> None:
        """Request a pause at a controlled scheduling boundary.

        Args:
            duration_seconds: Non-negative automatic-resume delay, or ``None`` to
                require a supervising context to resume this context.
        """
        self._validate_duration(duration_seconds)
        self._context_access.pause(
            context_id=self.id,
            identity=self._identity(),
            duration_seconds=duration_seconds,
        )

    def _identity(self) -> StepIdentity:
        return StepIdentity(
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
