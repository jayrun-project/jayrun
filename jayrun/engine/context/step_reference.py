from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StepReference:
    step_name: str
    step_kind: str
    step_index: int
    layout_position: tuple[int, int]
