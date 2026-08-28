from __future__ import annotations

from enum import Enum


class ContextState(Enum):
    """Lifecycle state of a submitted execution context."""

    SUBMITTED = "submitted"
    VALIDATING = "validating"
    VALIDATED = "validated"
    REJECTED = "rejected"
    QUEUED = "queued"
    RUNNING = "running"
    PLACEMENT_WAITING = "placement_waiting"
    PAUSED = "paused"
    ABORTING = "aborting"
    FAILING = "failing"
    FINISHED = "finished"
    STOPPED = "stopped"
    FAILED = "failed"
    ABORTED = "aborted"

    @property
    def is_terminal(self) -> bool:
        """Whether the context has reached a terminal outcome state."""
        return self in {
            ContextState.REJECTED,
            ContextState.FINISHED,
            ContextState.STOPPED,
            ContextState.FAILED,
            ContextState.ABORTED,
        }

    @property
    def is_draining(self) -> bool:
        """Whether cancellation or failure cleanup is in progress."""
        return self in {
            ContextState.ABORTING,
            ContextState.FAILING,
        }

    @property
    def is_active(self) -> bool:
        """Whether the context currently owns or may request runtime work."""
        return self in {
            ContextState.RUNNING,
            ContextState.PLACEMENT_WAITING,
            ContextState.PAUSED,
            ContextState.ABORTING,
            ContextState.FAILING,
        }
