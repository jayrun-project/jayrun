from dataclasses import dataclass

from ..runtime_message import RuntimeCommand


@dataclass(frozen=True, slots=True)
class TransferContextCommand(RuntimeCommand):
    context_id: int
    engine_id: str
