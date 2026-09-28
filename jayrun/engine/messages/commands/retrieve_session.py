from dataclasses import dataclass

from ..runtime_message import RuntimeCommand


@dataclass(frozen=True, slots=True)
class RetrieveSessionCommand(RuntimeCommand):
    session_id: int
