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


def incompatible_feedback(
    inputs: tuple[ArtifactField, ...],
    outputs: tuple[ArtifactField, ...],
) -> tuple[Artifact, ...]:
    """Compare only regenerated slots which will feed the next invocation."""
    sources = {field.artifact: field for field in outputs if field.artifact is not None}
    validator = ArtifactValidator()
    return tuple(
        field.artifact for field in inputs
        if field.artifact in sources and not validator.validate(
            field.properties, sources[field.artifact].properties,
        ).valid
    )


class GraphValidation:
    """Internal builder for artifact-contract validation records."""

    def __init__(self, graph: GraphDefinition) -> None:
        if not isinstance(graph, GraphDefinition):
            raise TypeError(f"Expected GraphDefinition, got {type(graph).__name__!r}.")

        self._graph = graph
        self._artifact_validator = ArtifactValidator()

    def __call__(self) -> GraphValidationReport:
        """Return the cached structured validation report."""
        return self._validation

    @cached_property
    def _validation(self) -> GraphValidationReport:
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        producers = _ArtifactProducerRegistry(self._graph.artifacts)

        self._add_entries(nodes, producers)
        self._add_operators(nodes, edges, producers)
        self._add_exits(nodes, edges, producers)

        entries = tuple(edge.target_field for edge in edges if edge.edge_type is EdgeType.ENTRY)
        exits = tuple(edge.source_field for edge in edges if edge.edge_type is EdgeType.EXIT)
        return GraphValidationReport(
            feedback_mismatches=incompatible_feedback(entries, exits),
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
        for column, occurrences in enumerate(self._graph._layout.columns):
            for row, operator in occurrences:
                consumed_inputs = self._consume_inputs(operator, producers)
                node_id = len(nodes)
                x_position = column + 1
                y_position = (
                    consumed_inputs[0][1].y_position
                    if consumed_inputs
                    else self._root_y_position(operator, producers, fallback=row)
                )

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

        return tuple(consumed)

    @staticmethod
    def _root_y_position(
        operator: BaseOperator,
        producers: _ArtifactProducerRegistry,
        *,
        fallback: int,
    ) -> int:
        for artifact in operator.output_artifacts:
            return producers.get(artifact).y_position
        return fallback

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
