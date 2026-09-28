"""Persistence failures do not describe an execution's outcome."""
from __future__ import annotations


class PersistenceError(RuntimeError):
    """Base storage/service error."""


class StorageContractError(PersistenceError, ValueError):
    """Invalid input, incompatible format, corrupt data, or backend protocol error."""


class StorageUnavailable(PersistenceError):
    """Operational failure; a transaction may have committed before acknowledgement."""


class PersistenceBackpressure(PersistenceError):
    """Bounded capture, queue, retention, or producer capacity is unavailable."""


class PersistenceTimeout(PersistenceError, TimeoutError):
    """The wait expired; an admitted operation may still own its handle."""


class PersistenceFlushError(PersistenceError):
    """A point-in-time barrier covers failed or missing work."""

    def __init__(self, target: int, first_failed: int, message: str = "covered persistence work failed") -> None:
        self.target = target
        self.first_failed = first_failed
        super().__init__(f"{message} (barrier={target}, first_failed={first_failed})")
