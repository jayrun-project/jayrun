from dataclasses import dataclass

from .data import DataDefinition


@dataclass(slots=True, frozen=True, kw_only=True)
class FieldDefinition(DataDefinition):
    """Common inspected metadata for a declarative component field."""

    owner: str
    required: bool
    layout_position: tuple[int, int]
    attribute_name: str


@dataclass(slots=True, frozen=True, kw_only=True)
class ConfigDefinition(FieldDefinition):
    """Graph-local inspected configuration-field metadata."""

    config_id: int
    value_type: type
    default: object | None


@dataclass(slots=True, frozen=True, kw_only=True)
class ResourceDefinition(FieldDefinition):
    """Graph-local inspected resource-field metadata."""

    resource_id: int
    parallel_safe: bool
