from collections.abc import Hashable

from ..recorders.execution.recorder import ExecutionRecorder
from ..registry.context_snapshot import ContextSnapshot
from ..registry.identities import SupervisorIdentity
from .base import ScopeInterface
from .services.accesses import RuntimeAccess
from .services.runtime import RuntimeCapabilityError
from .value_record import ValueRecord


class RuntimeInterface(ScopeInterface):
    """Share runtime-scoped values and, when enabled, supervise contexts.

    Cross-context inspection and lifecycle control require the current context to be
    submitted with ``ContextSettings(supervising=True)``.
    """

    def __init__(
        self,
        runtime_access: RuntimeAccess,
        recorder: ExecutionRecorder,
    ) -> None:
        super().__init__(recorder=recorder)
        self._runtime_access = runtime_access
        self._identity = SupervisorIdentity(context_id=self._recorder.context_id)

    def get_records(self, key: Hashable) -> tuple[ValueRecord, ...]:
        """Return runtime-scoped records for ``key`` in recording order."""
        return self._runtime_access.get_records(key)

    def _store(self, record: ValueRecord) -> None:
        self._runtime_access.store(record)

    def abort(self, context_id: int) -> None:
        """Prevent further dispatch and drain the target toward ``ABORTED``."""
        self._require_supervision("abort")
        self._validate_context_id(context_id)
        self._runtime_access.abort(context_id=context_id, identity=self._identity)

    def stop(self, context_id: int) -> None:
        """Stop the target's iteration after accepted work drains."""
        self._require_supervision("stop")
        self._validate_context_id(context_id)
        self._runtime_access.stop(context_id=context_id, identity=self._identity)

    def pause(
        self,
        context_id: int,
        duration_seconds: float | None = None,
    ) -> None:
        """Request that another context pause at a scheduling boundary."""
        self._require_supervision("pause")
        self._validate_context_id(context_id)
        self._validate_duration(duration_seconds)
        self._runtime_access.pause(
            context_id=context_id,
            identity=self._identity,
            duration_seconds=duration_seconds,
        )

    def resume(self, context_id: int) -> None:
        """Request that a paused context resume."""
        self._require_supervision("resume")
        self._validate_context_id(context_id)
        self._runtime_access.resume(context_id=context_id, identity=self._identity)

    def get(self, context_id: int) -> ContextSnapshot | None:
        """Return another context's latest snapshot, or ``None`` if unknown."""
        self._require_supervision("inspect contexts")
        self._validate_context_id(context_id)
        return self._runtime_access.get_context(context_id)

    @property
    def context_ids(self) -> tuple[int, ...]:
        """IDs of all contexts visible to the runtime."""
        self._require_supervision("access context IDs")
        return self._runtime_access.context_ids()

    @property
    def active_context_ids(self) -> tuple[int, ...]:
        """IDs of contexts in active or draining states."""
        self._require_supervision("access active context IDs")
        return self._runtime_access.active_context_ids()

    @property
    def paused_context_ids(self) -> tuple[int, ...]:
        """IDs of currently paused contexts."""
        self._require_supervision("access paused context IDs")
        return self._runtime_access.paused_context_ids()

    def _require_supervision(self, action: str) -> None:
        if not self._runtime_access.supervising:
            raise RuntimeCapabilityError(f"only supervising contexts can {action}")

    @staticmethod
    def _validate_context_id(context_id: int) -> None:
        if type(context_id) is not int:
            raise TypeError("context_id must be int")

    @staticmethod
    def _validate_duration(duration_seconds: float | None) -> None:
        if isinstance(duration_seconds, bool) or not isinstance(
            duration_seconds,
            (int, float, type(None)),
        ):
            raise TypeError("duration_seconds must be int, float, or None")
        if duration_seconds is not None and duration_seconds < 0:
            raise ValueError("duration_seconds must be non-negative")
