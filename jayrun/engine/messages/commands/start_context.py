from dataclasses import dataclass

from ..runtime_message import RuntimeCommand


@dataclass(frozen=True, slots=True)
class StartContextCommand(RuntimeCommand):
    context_id: int
