from dataclasses import dataclass

from ...snapshot import ContextSnapshot
from ...pressure import PressureSnapshot
from ..runtime_message import RuntimeCommand


class _SnapshotRejectedError(RuntimeError):
    """Expected lifecycle/ownership rejection, not an internal validation fault."""


@dataclass(frozen=True, slots=True)
class ApplySnapshotCommand(RuntimeCommand):
    snapshot: ContextSnapshot | PressureSnapshot
