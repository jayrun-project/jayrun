from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BaseIdentity:
    pass


@dataclass(frozen=True, slots=True)
class SupervisorIdentity(BaseIdentity):
    context_id: int


@dataclass(frozen=True, slots=True)
class ContextIdentity(BaseIdentity):
    context_id: int


@dataclass(frozen=True, slots=True)
class ContextRunIdentity(BaseIdentity):
    context_id: int


@dataclass(frozen=True, slots=True)
class StepIdentity(BaseIdentity):
    context_id: int
    step_name: str
    step_type: object
    layout_position: object


@dataclass(frozen=True, slots=True)
class RuntimeModuleIdentity(BaseIdentity):
    name: str


@dataclass(frozen=True, slots=True)
class EngineIdentity(BaseIdentity):
    name: str = "engine"
