from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from ..artifact.base import Artifact
from ..artifact.field import ArtifactField
from ..graph.graph_definition import GraphDefinition
from ..operator.base import BaseOperator
from .artifact import ArtifactValidator
from .graph import (
    EdgeType,
    EntryNode,
    ExitNode,
    GraphEdge,
    GraphNode,
    GraphValidationReport,
    NodeType,
    OperatorNode,
)
from .plotting import GraphPlotter
from .reporting import ValidationReporter


@dataclass(slots=True, frozen=True)
class ArtifactProducer:
    y_position: int
    node_id: int | None = None
    node_type: NodeType | None = None
    x_position: int | None = None
    output_field: ArtifactField | None = None


class _ArtifactProducerRegistry:
    def __init__(self, artifacts: tuple[Artifact, ...]) -> None:
        self._producers = {
            artifact: ArtifactProducer(y_position=y_position)
            for y_position, artifact in enumerate(artifacts)
        }

    def get(self, artifact: Artifact) -> ArtifactProducer:
        return self._producers[artifact]

    def set_producer(
        self,
        artifact: Artifact,
        *,
        node_id: int,
        node_type: NodeType,
        x_position: int,
        output_field: ArtifactField | None,
    ) -> None:
        y_position = self._producers[artifact].y_position
        self._producers[artifact] = ArtifactProducer(
            y_position=y_position,
            node_id=node_id,
            node_type=node_type,
            x_position=x_position,
            output_field=output_field,
        )

    def consume(self, artifact: Artifact) -> ArtifactProducer:
        producer = self._producers[artifact]

        if producer.node_id is None:
            raise RuntimeError(f"Artifact {artifact!r} has no active producer.")

        self._producers[artifact] = ArtifactProducer(y_position=producer.y_position)
        return producer

    def active(self) -> tuple[tuple[Artifact, ArtifactProducer], ...]:
        return tuple(
            (artifact, producer)
            for artifact, producer in self._producers.items()
            if producer.node_id is not None
        )


class GraphValidator:
    """Validate artifact contracts across every edge of a graph.

    Validation is structural and does not execute the graph. The report and plot
    views reuse the same cached validation result.

    Args:
        graph: Graph definition to inspect.
    """

    def __init__(self, graph: GraphDefinition) -> None:
        if not isinstance(graph, GraphDefinition):
            raise TypeError(f"Expected GraphDefinition, got {type(graph).__name__!r}.")

        self._graph = graph
        self._artifact_validator = ArtifactValidator()

    def validate(self) -> GraphValidationReport:
        """Return the cached structured validation report."""
        return self._validation

    @cached_property
    def report(self) -> ValidationReporter:
        """Text reporter backed by the cached validation result."""
        return ValidationReporter(self._validation)

    @cached_property
    def plot(self) -> GraphPlotter:
        """Interactive graph plotter backed by the cached validation result."""
        return GraphPlotter(self._validation, self._graph.artifacts)

    @cached_property
    def _validation(self) -> GraphValidationReport:
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        producers = _ArtifactProducerRegistry(self._graph.artifacts)

        self._add_entries(nodes, producers)
        self._add_operators(nodes, edges, producers)
        self._add_exits(nodes, edges, producers)

        return GraphValidationReport(
            nodes=tuple(nodes),
            edges=tuple(edges),
        )

    def _add_entries(
        self,
        nodes: list[GraphNode],
        producers: _ArtifactProducerRegistry,
    ) -> None:
        for artifact in self._graph.entry_artifacts:
            producer = producers.get(artifact)
            node_id = len(nodes)
            artifact_id = self._graph._specification.artifacts.definition_for(
                artifact
            ).artifact_id

            nodes.append(
                EntryNode(
                    node_id=node_id,
                    x_position=0,
                    y_position=producer.y_position,
                    artifact=artifact,
                    artifact_id=artifact_id,
                )
            )

            producers.set_producer(
                artifact,
                node_id=node_id,
                node_type=NodeType.ENTRY,
                x_position=0,
                output_field=None,
            )

    def _add_operators(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        producers: _ArtifactProducerRegistry,
    ) -> None:
        row_count, column_count = self._graph.layout.shape

        for column in range(column_count):
            processed_operator_ids: set[int] = set()

            for row in range(row_count):
                operator = self._graph.layout.rows[row][column]

                if operator is None:
                    continue

                operator_identity = id(operator)

                if operator_identity in processed_operator_ids:
                    continue

                processed_operator_ids.add(operator_identity)
                consumed_inputs = self._consume_inputs(operator, producers)
                node_id = len(nodes)
                x_position = column + 1
                y_position = consumed_inputs[0][1].y_position

                nodes.append(
                    OperatorNode(
                        node_id=node_id,
                        x_position=x_position,
                        y_position=y_position,
                        operator=operator,
                        layout_position=(row, column),
                    )
                )

                self._add_input_edges(node_id, consumed_inputs, edges)
                self._register_outputs(
                    operator,
                    node_id,
                    x_position,
                    producers,
                )

    @staticmethod
    def _consume_inputs(
        operator: BaseOperator,
        producers: _ArtifactProducerRegistry,
    ) -> tuple[tuple[ArtifactField, ArtifactProducer], ...]:
        consumed: list[tuple[ArtifactField, ArtifactProducer]] = []

        for input_field in operator.bound_artifact_fields:
            artifact = input_field.artifact

            if artifact is None:
                continue

            consumed.append((input_field, producers.consume(artifact)))

        if not consumed:
            raise RuntimeError(f"Operator {operator!r} has no active artifact input.")

        return tuple(consumed)

    def _add_input_edges(
        self,
        node_id: int,
        consumed_inputs: tuple[tuple[ArtifactField, ArtifactProducer], ...],
        edges: list[GraphEdge],
    ) -> None:
        for input_field, producer in consumed_inputs:
            artifact = input_field.artifact
            output_field = producer.output_field
            validation = (
                self._artifact_validator.validate(
                    target_properties=input_field.properties,
                    source_properties=output_field.properties,
                )
                if output_field is not None
                else None
            )

            edges.append(
                GraphEdge(
                    edge_id=len(edges),
                    edge_type=(
                        EdgeType.ENTRY
                        if producer.node_type is NodeType.ENTRY
                        else EdgeType.INTERMEDIATE
                    ),
                    source=producer.node_id,
                    target=node_id,
                    artifact=artifact,
                    target_field=input_field,
                    source_field=output_field,
                    validation=validation,
                )
            )

    @staticmethod
    def _register_outputs(
        operator: BaseOperator,
        node_id: int,
        x_position: int,
        producers: _ArtifactProducerRegistry,
    ) -> None:
        for output_field in operator.outputs:
            artifact = output_field.artifact

            if artifact is None:
                continue

            producers.set_producer(
                artifact,
                node_id=node_id,
                node_type=NodeType.OPERATOR,
                x_position=x_position,
                output_field=output_field,
            )

    def _add_exits(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        producers: _ArtifactProducerRegistry,
    ) -> None:
        for artifact, producer in producers.active():
            if producer.node_type is not NodeType.OPERATOR:
                continue

            edge_type = self._terminal_edge_type(artifact)
            node_id = len(nodes)
            node_type = ExitNode
            artifact_id = self._graph._specification.artifacts.definition_for(
                artifact
            ).artifact_id
            nodes.append(
                node_type(
                    node_id=node_id,
                    x_position=producer.x_position + 1,
                    y_position=producer.y_position,
                    artifact=artifact,
                    artifact_id=artifact_id,
                )
            )
            edges.append(
                GraphEdge(
                    edge_id=len(edges),
                    edge_type=edge_type,
                    source=producer.node_id,
                    target=node_id,
                    artifact=artifact,
                    target_field=None,
                    source_field=producer.output_field,
                    validation=None,
                )
            )

    def _terminal_edge_type(self, artifact: Artifact) -> EdgeType:
        definition = self._graph._specification.artifacts.definition_for(artifact)
        return EdgeType.EXIT if definition.is_exit else EdgeType.UNUSED
