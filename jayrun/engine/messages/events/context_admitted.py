from dataclasses import dataclass

from ..runtime_message import RuntimeEvent


@dataclass(frozen=True, slots=True)
class ContextAdmittedEvent(RuntimeEvent):
    context_id: int
