from dataclasses import dataclass

from ..runtime_message import RuntimeCommand


@dataclass(frozen=True, slots=True)
class AbortContextCommand(RuntimeCommand):
    context_id: int
