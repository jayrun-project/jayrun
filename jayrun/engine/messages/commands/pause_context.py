from dataclasses import dataclass, field
from time import monotonic

from ..runtime_message import RuntimeCommand


@dataclass(frozen=True, slots=True)
class PauseContextCommand(RuntimeCommand):
    context_id: int
    duration: int | float | None = None
    submitted_at: float = field(default_factory=monotonic)
