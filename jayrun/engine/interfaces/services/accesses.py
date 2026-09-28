from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ....persistence import DatabaseReader

from ...context_run import ContextRun
from ...messages.origin import CommandOrigin
from ...observation import ContextObserver
from ...pressure import PressureSnapshot
from ...snapshot import ContextSnapshot
from ...terminal_history import TerminalCursor, TerminalHistoryPage
from ..context_record import ContextRecord


@dataclass(frozen=True, slots=True)
class ContextAccess:
    record: Callable[[ContextRecord, CommandOrigin], None]
    records: Callable[[str], tuple[ContextRecord, ...]]
    abort: Callable[[CommandOrigin], None]
    pause: Callable[[CommandOrigin, int | float | None], None]
    stop: Callable[[CommandOrigin], None]


@dataclass(frozen=True, slots=True)
class RuntimeAccess:
    name: str
    engine_id: str
    alive: Callable[[], bool]
    contexts: Callable[[], tuple[ContextRun, ...]]
    active_contexts: Callable[[], tuple[ContextRun, ...]]
    paused_contexts: Callable[[], tuple[ContextRun, ...]]
    events: Callable[[], ContextObserver]
    pressure: Callable[[], PressureSnapshot]
    pressures: Callable[[], tuple[PressureSnapshot, ...]]
    apply: Callable[[ContextSnapshot | PressureSnapshot], None]
    submit: Callable[..., ContextRun]
    shutdown: Callable[[bool], None]
    terminal_history: Callable[[TerminalCursor | None, int], TerminalHistoryPage] | None = None

    history: Callable[[], DatabaseReader | None] | None = None
