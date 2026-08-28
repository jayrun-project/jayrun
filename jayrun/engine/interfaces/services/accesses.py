from collections.abc import Callable, Hashable
from dataclasses import dataclass

from ...registry.context_snapshot import ContextSnapshot
from ...registry.identities import BaseIdentity
from ..value_record import ValueRecord


@dataclass(frozen=True, slots=True)
class ScopeAccess:
    store: Callable[[ValueRecord], None]
    get_records: Callable[[Hashable], tuple[ValueRecord, ...]]
    abort: Callable[[int, BaseIdentity], None]
    pause: Callable[[int, BaseIdentity, int | float | None], None]
    stop: Callable[[int, BaseIdentity], None]


@dataclass(frozen=True, slots=True)
class ContextAccess(ScopeAccess):
    pass


@dataclass(frozen=True, slots=True)
class RuntimeAccess(ScopeAccess):
    supervising: bool
    resume: Callable[[int, BaseIdentity], None]
    get_context: Callable[[int], ContextSnapshot | None]
    context_ids: Callable[[], tuple[int, ...]]
    active_context_ids: Callable[[], tuple[int, ...]]
    paused_context_ids: Callable[[], tuple[int, ...]]
