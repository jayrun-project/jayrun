"""Optional recording policy; never a runtime authority or lifecycle policy."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import RecordingMode


@dataclass(frozen=True, slots=True)
class _InstrumentationPolicy:
    """Resolve modes once at construction, not throughout execution owners.

    Failure outcomes, current-step state, durations, attempts, explicit context
    records and artifact availability are mandatory existing evidence. These
    flags govern only additional recording. Performance retains exception
    details on failure paths even though ordinary diagnostics are disabled.
    """

    learn_progress: bool
    record_logs: bool
    record_metrics: bool
    record_timers: bool
    keep_artifact_history: bool
    record_failure_details: bool

    @classmethod
    def for_mode(cls, mode: RecordingMode) -> _InstrumentationPolicy:
        from .engine import RecordingMode

        if not isinstance(mode, RecordingMode):
            raise TypeError("mode must be a RecordingMode instance")
        if mode is RecordingMode.STANDARD:
            # Preserve all established production recording defaults, including
            # its omission of duplicate per-attempt failure records.
            return cls(True, True, True, False, False, False)
        if mode is RecordingMode.DIAGNOSTIC:
            return cls(True, True, True, True, True, True)
        if mode is RecordingMode.MINIMAL:
            return cls(False, False, False, False, False, True)
        raise ValueError("unsupported runtime mode")
