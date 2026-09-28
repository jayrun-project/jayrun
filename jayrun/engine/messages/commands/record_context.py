from dataclasses import dataclass

from ...interfaces.context_record import ContextRecord
from ..runtime_message import RuntimeCommand


@dataclass(frozen=True, slots=True)
class RecordContextCommand(RuntimeCommand):
    record: ContextRecord
