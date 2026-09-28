from dataclasses import dataclass

from ...context.context_outcome import ContextOutcome
from ..runtime_message import RuntimeEvent


@dataclass(frozen=True, slots=True)
class ContextTerminatedEvent(RuntimeEvent):
    context_id: int
    outcome: ContextOutcome
