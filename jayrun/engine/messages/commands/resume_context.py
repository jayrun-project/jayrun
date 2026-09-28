from dataclasses import dataclass

from ..runtime_message import RuntimeCommand


@dataclass(frozen=True, slots=True)
class ResumeContextCommand(RuntimeCommand):
    context_id: int
