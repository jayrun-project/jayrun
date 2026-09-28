from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RecordOrigin(Enum):
    """Whether a record was emitted by Jayrun or user component code."""

    INTERNAL = "internal"
    USER = "user"


class ExecutionOutcome(Enum):
    """Final outcome of one operator or resource step session."""

    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    """Base metadata shared by execution log, metric, timer, and failure records."""

    origin: RecordOrigin
    execution: int


@dataclass(frozen=True, slots=True)
class TimerRecord(ExecutionRecord):
    """Elapsed duration recorded by a named execution timer."""

    name: str
    elapsed_time: float


@dataclass(frozen=True, slots=True)
class MetricRecord(ExecutionRecord):
    """Named numeric metric recorded by component code."""

    name: str
    value: int | float


@dataclass(frozen=True, slots=True)
class LogRecord(ExecutionRecord):
    """Text message recorded by component code."""

    message: str


@dataclass(frozen=True, slots=True)
class FailureRecord(ExecutionRecord):
    """Exception recorded for a failed execution attempt."""

    exception: Exception


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    """Records produced by one retry attempt of an execution."""

    execution: int
    attempt: int
    records: tuple[ExecutionRecord, ...]


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    """Immutable outcome and observability data for one graph step session.

    ``duration_seconds`` is monotonic active execution time. It excludes time
    spent waiting for placement between dispatch attempts. Progress profiling
    consumes complete report batches at context or iteration boundaries; live
    progress updates do not mutate durable history.
    """

    step_index: int
    step_kind: str
    step_name: str
    layout_position: tuple[int, int]
    context_id: int
    iteration: int
    attempts: tuple[AttemptRecord, ...]
    execution_count: int
    outcome: ExecutionOutcome
    skip_reason: str | None = None
    duration_seconds: float = 0.0
