from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar

from ..artifact.base import Artifact
from ..artifact.field import ArtifactField
from ..operator.base import BaseOperator
from .artifact import ArtifactValidationReport, ValidationStatus


class NodeType(Enum):
    ENTRY = "entry"
    OPERATOR = "operator"
    EXIT = "exit"


class EdgeType(Enum):
    ENTRY = "entry"
    INTERMEDIATE = "intermediate"
    EXIT = "exit"
    UNUSED = "unused"


def _display_name(value: object) -> str:
    display_name = getattr(value, "display_name", None)

    if isinstance(display_name, str) and display_name:
        return display_name

    name = getattr(value, "name", None)

    if isinstance(name, str) and name:
        return name

    return type(value).__name__


def _append_repr(
    lines: list[str],
    title: str,
    value: object,
    *,
    indent: int = 1,
) -> None:
    lines.append(f"{'  ' * indent}{title}: {value}")


@dataclass(slots=True, frozen=True)
class GraphNode:
    node_id: int
    x_position: int
    y_position: int

    @property
    def label(self) -> str:
        raise NotImplementedError


@dataclass(slots=True, frozen=True)
class EntryNode(GraphNode):
    artifact: Artifact
    artifact_id: int
    node_type: ClassVar[NodeType] = NodeType.ENTRY

    @property
    def label(self) -> str:
        return f"ENTRY · {_display_name(self.artifact)}"

    def __repr__(self) -> str:
        lines = ["ENTRY"]
        _append_repr(lines, "node_id", self.node_id)
        _append_repr(lines, "artifact", self.artifact.name)
        _append_repr(lines, "description", self.artifact.description)
        _append_repr(lines, "artifact_id", self.artifact_id)
        return "\n".join(lines)


@dataclass(slots=True, frozen=True)
class OperatorNode(GraphNode):
    operator: BaseOperator
    layout_position: tuple[int, int]

    node_type: ClassVar[NodeType] = NodeType.OPERATOR

    @property
    def label(self) -> str:
        return _display_name(self.operator)

    def __repr__(self) -> str:
        lines = ["OPERATOR"]
        _append_repr(lines, "node_id", self.node_id)
        _append_repr(lines, "name", self.operator.display_name)
        _append_repr(lines, "description", self.operator.description)

        _append_repr(lines, "layout position", self.layout_position)

        for side, fields in (
            ("inputs", self.operator.declared_artifact_fields),
            ("outputs", self.operator.outputs),
        ):
            lines.append(f"  {side}:")
            for field in fields:
                _append_repr(lines, "field", field.display_name, indent=2)
                _append_repr(
                    lines, "binding",
                    repr(field.artifact.name) if field.artifact is not None else "UNBOUND",
                    indent=3,
                )
                _append_repr(lines, "description", field.description, indent=3)

        if self.operator.config_fields:
            lines.append("  configs:")
            for config in self.operator.config_fields:
                value = config.value_type.__name__

                if config.default is not None:
                    value += f" = {config.default!r}"

                _append_repr(
                    lines,
                    config.display_name,
                    value,
                    indent=2,
                )
                _append_repr(lines, "description", config.description, indent=3)
        else:
            _append_repr(lines, "configs", "none")

        if self.operator.resource_fields:
            lines.append("  resources:")
            for resource in self.operator.resource_fields:
                lines.append(f"    {resource.display_name}")
                _append_repr(lines, "description", resource.description, indent=3)
        else:
            _append_repr(lines, "resources", "none")

        return "\n".join(lines)


@dataclass(slots=True, frozen=True)
class ExitNode(GraphNode):
    artifact: Artifact
    artifact_id: int
    node_type: ClassVar[NodeType] = NodeType.EXIT

    @property
    def label(self) -> str:
        return f"EXIT · {_display_name(self.artifact)}"

    def __repr__(self) -> str:
        lines = ["EXIT"]
        _append_repr(lines, "node_id", self.node_id)
        _append_repr(lines, "artifact", self.artifact.name)
        _append_repr(lines, "description", self.artifact.description)
        _append_repr(lines, "artifact_id", self.artifact_id)
        return "\n".join(lines)


@dataclass(slots=True, frozen=True)
class GraphEdge:
    edge_id: int
    edge_type: EdgeType
    source: int
    target: int
    artifact: Artifact
    target_field: ArtifactField | None
    source_field: ArtifactField | None
    validation: ArtifactValidationReport | None

    @property
    def status(self) -> ValidationStatus | None:
        return self.validation.status if self.validation is not None else None

    @property
    def mismatched(self) -> bool:
        return self.status is ValidationStatus.MISMATCH

    @property
    def unknown(self) -> bool:
        return self.status is ValidationStatus.UNKNOWN

    @property
    def label(self) -> str:
        prefix = "⚠ " if self.mismatched else "? " if self.unknown else ""
        return f"{prefix}{_display_name(self.artifact)}"

    def __repr__(self) -> str:
        lines = [self.edge_type.value.upper()]
        _append_repr(lines, "edge", self.edge_id)
        _append_repr(lines, "nodes", f"{self.source} -> {self.target}")
        _append_repr(lines, "artifact", self.artifact.name)
        _append_repr(lines, "description", self.artifact.description)
        for side, field in (("output", self.source_field), ("input", self.target_field)):
            if field is not None:
                _append_repr(lines, f"{side} field", field.display_name)
                _append_repr(lines, f"{side} description", field.description)
        if self.validation is None:
            lines.append("Validation: not available")
        else:
            lines.extend(repr(self.validation).splitlines())

        return "\n".join(lines)


@dataclass(slots=True, frozen=True)
class GraphValidationReport:
    """Structured nodes, edges, and compatibility results for one graph."""

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]

    @property
    def valid(self) -> bool:
        """Whether the graph contains no known property mismatches."""
        return not any(edge.mismatched for edge in self.edges)

    @property
    def mismatched_edges(self) -> tuple[GraphEdge, ...]:
        """Edges with incompatible producer and consumer properties."""
        return tuple(edge for edge in self.edges if edge.mismatched)

    @property
    def unknown_edges(self) -> tuple[GraphEdge, ...]:
        """Edges whose compatibility cannot be established statically."""
        return tuple(edge for edge in self.edges if edge.unknown)
