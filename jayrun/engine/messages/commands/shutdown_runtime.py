from dataclasses import dataclass

from ..runtime_message import RuntimeCommand


@dataclass(frozen=True, slots=True)
class ShutdownRuntimeCommand(RuntimeCommand):
    forced: bool
