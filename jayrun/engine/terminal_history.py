"""Bounded terminal metadata recovery, separate from payload-bearing snapshots.

This is a process-local observation window, not durable history or a checkpoint.
Only the registry's finalization owner publishes. Readers receive immutable values;
no context, graph, exception, record value, artifact, or capability is retained.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, replace
from datetime import datetime
import json
import threading
from typing import TYPE_CHECKING

from .registry.context_state import ContextState

if TYPE_CHECKING:
    from .registry.context_instance import ContextInstance


@dataclass(frozen=True, slots=True)
class TerminalCursor:
    """Position in one engine incarnation's terminal commit order; not authority."""
    engine: str
    sequence: int


@dataclass(frozen=True, slots=True)
class TerminalSummary:
    """Finalized outcome metadata, without report, record or artifact payloads.

    Missing optional identity/counter fields are listed in ``omitted_fields``.
    Their absence is not evidence of an empty history. ``engine_id`` is the recorded
    execution-owner incarnation, not a physical hostname. ``supervising`` is a
    factual role label; it neither contains nor grants a capability.
    """
    sequence: int
    context_id: int
    graph_key: str | None
    graph_version: str | None
    engine_id: str | None
    generation: int | None
    revision: int | None
    state: ContextState
    iteration_count: int | None
    completed_iterations: int | None
    stop_requested: bool
    created_at: datetime
    finished_at: datetime
    failure_type: str | None
    omitted_fields: tuple[str, ...] = ()
    supervising: bool = False


@dataclass(frozen=True, slots=True)
class TerminalHistoryPage:
    """A bounded read of finalized summaries after a cursor.

    ``gap`` means at least one sequence in this read's traversed interval is no
    longer available, including an oversized entry or a disabled window.
    ``has_more`` means another page was available at the atomic read boundary.
    No gap establishes only summary coverage, never full report/event coverage.
    """
    entries: tuple[TerminalSummary, ...]
    next_cursor: TerminalCursor
    oldest_sequence: int
    latest_sequence: int
    gap: bool
    has_more: bool


class _TerminalHistory:
    _MAX_ENTRY_BYTES = 8192
    _MAX_PAGE = 256

    def __init__(self, engine: str, limit: int, max_bytes: int) -> None:
        self._engine = engine
        self._limit = limit
        self._max_bytes = max_bytes
        self._entries: deque[tuple[TerminalSummary, int]] = deque()
        self._bytes = 0
        self._sequence = 0
        self._lock = threading.RLock()
        self._closed = False

    def publish(self, context: ContextInstance) -> None:
        # No full snapshot construction here: it could reference user artifacts.
        with context._inspection_lock:
            if not context.finalized or context.status.finished_at is None:
                raise RuntimeError("terminal history requires finalized evidence")
            eligible = type(context.context_id) is int and 0 <= context.context_id < 2**128
            omitted: list[str] = []

            def text(name: str, value: str | None) -> str | None:
                if value is None or len(value) <= 256:
                    return value
                omitted.append(name)
                return None

            def count(name: str, value: int) -> int | None:
                if type(value) is int and 0 <= value < 2**128:
                    return value
                omitted.append(name)
                return None

            summary = TerminalSummary(
                sequence=0, context_id=context.context_id,
                graph_key=text('graph_key', context.graph_scope[0] if isinstance(context.graph_scope, tuple) else None),
                graph_version=text('graph_version', context.graph.version),
                engine_id=text('engine_id', context.engine_id),
                generation=count('generation', context.generation),
                revision=count('revision', context._snapshot_revision),
                state=context.state,
                iteration_count=count('iteration_count', context.iteration_count),
                completed_iterations=count('completed_iterations', context.completed_iterations),
                stop_requested=context.stop_requested,
                created_at=context.status.created_at, finished_at=context.status.finished_at,
                failure_type=text('failure_type', type(context.failure).__name__ if context.failure is not None else None),
                omitted_fields=tuple(omitted), supervising=context.is_supervising,
            )
        with self._lock:
            if self._closed:
                raise RuntimeError('terminal history is closed')
            self._sequence += 1
            if not eligible:
                # An unusual received identity must not make metadata recording
                # fail a legitimate finalization or retain an unbounded integer.
                return
            summary = replace(summary, sequence=self._sequence)
            data = asdict(summary)
            data.update(state=summary.state.value, created_at=summary.created_at.isoformat(),
                        finished_at=summary.finished_at.isoformat())
            size = len(json.dumps(data, ensure_ascii=True, separators=(',', ':')).encode('utf-8'))
            if self._limit and size <= min(self._MAX_ENTRY_BYTES, self._max_bytes):
                self._entries.append((summary, size))
                self._bytes += size
            # Skipped entries still advance the cursor, so loss is detectable.
            while len(self._entries) > self._limit or self._bytes > self._max_bytes:
                _, size = self._entries.popleft()
                self._bytes -= size

    def read(self, after: TerminalCursor | None, limit: int) -> TerminalHistoryPage:
        if type(limit) is not int or not 1 <= limit <= self._MAX_PAGE:
            raise ValueError(f'limit must be an integer from 1 to {self._MAX_PAGE}')
        if after is not None and not isinstance(after, TerminalCursor):
            raise TypeError('after must be a TerminalCursor or None')
        if after is not None and (after.engine != self._engine or type(after.sequence) is not int or after.sequence < 0):
            raise ValueError('cursor must identify this engine incarnation and a nonnegative sequence')
        start = 0 if after is None else after.sequence
        with self._lock:
            if self._closed:
                raise RuntimeError('terminal history is closed')
            if start > self._sequence:
                raise ValueError('cursor is ahead of this engine terminal history')
            selected: list[TerminalSummary] = []
            position = start
            gap = False
            for entry, _ in self._entries:
                if entry.sequence <= start:
                    continue
                gap |= entry.sequence != position + 1
                selected.append(entry)
                position = entry.sequence
                if len(selected) == limit:
                    break
            if len(selected) < limit:
                gap |= position < self._sequence
                position = self._sequence
            return TerminalHistoryPage(
                tuple(selected), TerminalCursor(self._engine, position),
                self._entries[0][0].sequence if self._entries else self._sequence + 1,
                self._sequence, gap, position < self._sequence,
            )

    def close(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes = 0
            self._closed = True
