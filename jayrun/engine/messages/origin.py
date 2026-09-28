from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandOrigin:
    pass


@dataclass(frozen=True, slots=True)
class EngineOrigin(CommandOrigin):
    name: str = "engine"


@dataclass(frozen=True, slots=True)
class RuntimeModuleOrigin(CommandOrigin):
    name: str


@dataclass(frozen=True, slots=True)
class ContextOrigin(CommandOrigin):
    context_id: int


@dataclass(frozen=True, slots=True)
class StepOrigin(CommandOrigin):
    context_id: int
    step_name: str
    step_type: object
    layout_position: object
