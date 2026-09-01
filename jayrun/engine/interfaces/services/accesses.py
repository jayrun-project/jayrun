from collections.abc import Callable, Hashable
from dataclasses import dataclass

from ...context_run import ContextRun
from ...registry.identities import BaseIdentity
from ..value_record import ValueRecord


@dataclass(frozen=True, slots=True)
class ContextAccess:
    store: Callable[[ValueRecord, BaseIdentity], None]
    get_records: Callable[[Hashable], tuple[ValueRecord, ...]]
    abort: Callable[[int, BaseIdentity], None]
    pause: Callable[[int, BaseIdentity, int | float | None], None]
    stop: Callable[[int, BaseIdentity], None]


@dataclass(frozen=True, slots=True)
class RuntimeAccess:
    contexts: Callable[[], tuple[ContextRun, ...]]
    active_contexts: Callable[[], tuple[ContextRun, ...]]
    paused_contexts: Callable[[], tuple[ContextRun, ...]]
