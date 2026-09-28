from dataclasses import dataclass

from .requirement import RequirementDefinition


@dataclass(slots=True, frozen=True, kw_only=True)
class SerializerDefinition:
    """Inspected serializer binding for one graph boundary artifact."""

    artifact_id: int
    name: str
    description: str | None
    serializer_type: str
    requirements: tuple[RequirementDefinition, ...]
    is_entry: bool
    is_exit: bool
