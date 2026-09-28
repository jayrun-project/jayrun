from __future__ import annotations

from enum import Enum


class ContextState(Enum):
    """Lifecycle state of a submitted execution context."""

    SUBMITTED = "submitted"
    VALIDATING = "validating"
    VALIDATED = "validated"
    REJECTED = "rejected"
    ROUTING = "routing"
    QUEUED = "queued"
    RUNNING = "running"
    PLACEMENT_WAITING = "placement_waiting"
    PAUSED = "paused"
    ABORTING = "aborting"
    FAILING = "failing"
    FINISHED = "finished"
    STOPPED = "stopped"  # Legacy terminal outcome, retained for snapshot compatibility.
    FAILED = "failed"
    ABORTED = "aborted"

    @property
    def is_terminal(self) -> bool:
        """Whether the context has reached a terminal outcome state."""
        return self in _TERMINAL_STATES

    @property
    def is_draining(self) -> bool:
        """Whether cancellation or failure cleanup is in progress."""
        return self in _DRAINING_STATES

    @property
    def is_active(self) -> bool:
        """Whether the context currently owns or may request runtime work."""
        return self in _ACTIVE_STATES


# Immutable classification, not cached context state. Keep live reads/locks at
# their existing call sites while avoiding rebuilding sets on every dispatch.
_TERMINAL_STATES = frozenset((
    ContextState.REJECTED,
    ContextState.FINISHED,
    ContextState.STOPPED,
    ContextState.FAILED,
    ContextState.ABORTED,
))
_DRAINING_STATES = frozenset((ContextState.ABORTING, ContextState.FAILING))
_ACTIVE_STATES = frozenset((
    ContextState.RUNNING,
    ContextState.PLACEMENT_WAITING,
    ContextState.PAUSED,
    ContextState.ABORTING,
    ContextState.FAILING,
))


class ContextRequest(Enum):
    """Portable lifecycle change requested for a context.

    Requests describe intent, while :class:`ContextState` describes a committed
    lifecycle fact. A remote pause therefore remains a ``PAUSE`` request until
    the owning runtime publishes a snapshot whose state is ``PAUSED``.
    """

    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    ABORT = "abort"
