from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .._history import _ContextCapture

from .origin import CommandOrigin


class RuntimeMessagePriority(Enum):
    ACTIVE = "active"
    SUBMISSION = "submission"


class RuntimeMessage:
    __slots__ = ()


class RuntimeCommand(RuntimeMessage):
    __slots__ = ()


class RuntimeEvent(RuntimeMessage):
    __slots__ = ()


@dataclass(frozen=True, slots=True)
class _AcceptedRuntimeMessage:
    message: RuntimeMessage
    origin: CommandOrigin
    priority: RuntimeMessagePriority
    accepted_during_shutdown: bool
    ownership_reservation: int | None = None
    history_capture: _ContextCapture | None = None
