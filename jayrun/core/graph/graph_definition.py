from __future__ import annotations

import inspect
import warnings
from collections.abc import Mapping
from dataclasses import replace
from functools import cached_property

from ...engine.execution.execution_mode import ExecutionMode
from ..artifact.base import Artifact
from ..operator.base import BaseOperator
from ..resource.base import BaseResource
from ..resource.context import ResourceContext
from ..resource.field import ResourceField
from .artifact_flow import ArtifactFlow
from .compiled_graph import (
    CompiledGraph,
    CompiledOperatorStep,
    CompiledResourceStep,
    CompiledStep,
)
from .definition.artifact import ArtifactDefinition, ArtifactRole
from .definition.field import ResourceDefinition
from .graph_layout import GraphLayout
from .graph_specification import GraphSpecification
from .graph_state import GraphState
from .inspection.graph import GraphInspection


class GraphDefinition:
    """Define and confirm an executable artifact graph.

    Graph construction validates topology and infers exit artifacts. Graphs without
    resource fields confirm immediately; graphs with resources confirm after all
    required bindings are supplied and optional bindings are accepted explicitly.

    Args:
        *flows: Every artifact flow in the graph.
        entry_flows: Flow or flows whose initial artifact values are supplied by the
            application.
    """

    def __init__(
        self,
        *flows: ArtifactFlow,
        entry_flows: ArtifactFlow | tuple[ArtifactFlow, ...],
    ) -> None:
        if isinstance(entry_flows, ArtifactFlow):
            entry_flows = (entry_flows,)

        self._entry_flows = entry_flows
        self._flows = flows

        self._confirm_flows()
        self._collect_artifacts()
        self._generate_layout()
        active_operator_outputs = self._validate_layout()
        self._set_exit_artifacts(active_operator_outputs)

        self._state = GraphState.CREATED

        self._specification = GraphSpecification(
            self._layout,
            artifacts=self._artifacts,
        )
        self._inspection = GraphInspection(self._specification)

        self._resource_context = ResourceContext()

        if not self._specification.resources:
            self._confirm()

    def bind_resources(
        self,
        resources: Mapping[
            int | ResourceField | ResourceDefinition,
            BaseResource,
        ],
    ) -> None:
        """Bind resource instances to graph resource fields.

        Args:
            resources: Mapping from resource IDs, fields, or inspected definitions to
                resource instances.

        Raises:
            RuntimeError: If resources were already bound or the graph is confirmed.
            KeyError: If a key does not belong to the graph.
            ValueError: If required resources are missing or keys are ambiguous.
        """
        if self._state is GraphState.CONFIRMED:
            raise RuntimeError("The graph is already confirmed.")

        if self._state is GraphState.RESOURCES_BOUND:
            raise RuntimeError("Resources are already bound.")

        if not isinstance(resources, Mapping):
            raise TypeError("Expected a mapping of resources.")

        registry = self._specification.resources
        definitions_by_id = {
            definition.resource_id: definition for definition in registry.definitions
        }
        resolved_resources: dict[ResourceField, BaseResource] = {}

        for key, resource in resources.items():
            field = self._resolve_resource_field(
                key,
                definitions_by_id=definitions_by_id,
            )

            if field in resolved_resources:
                raise ValueError(
                    "Multiple resource keys resolve to the same ResourceField."
                )

            resolved_resources[field] = resource

        self._validate_required_resources(resolved_resources)

        ordered_resources = {
            field: resolved_resources[field]
            for field in registry.sources
            if field in resolved_resources
        }

        self._resource_context.set(ordered_resources)
        self._state = GraphState.RESOURCES_BOUND

        if len(self._inspection.resources.all) == len(ordered_resources):
            self._confirm()
            return

        warnings.warn(
            "Required resources are satisfied, but optional resources "
            "remain unbound. Call confirm() to explicitly continue "
            "without them.",
            UserWarning,
            stacklevel=2,
        )

    def _resolve_resource_field(
        self,
        resource: int | ResourceField | ResourceDefinition,
        *,
        definitions_by_id: Mapping[int, ResourceDefinition],
    ) -> ResourceField:
        registry = self._specification.resources

        if type(resource) is int:
            try:
                definition = definitions_by_id[resource]
            except KeyError:
                raise KeyError(f"Unknown resource ID: {resource!r}.") from None

            return registry.source_for(definition)

        if isinstance(resource, ResourceDefinition):
            if resource not in registry.definitions:
                raise KeyError("The ResourceDefinition does not belong to this graph.")

            return registry.source_for(resource)

        if isinstance(resource, ResourceField):
            if resource not in registry.sources:
                raise KeyError("The ResourceField does not belong to this graph.")

            return resource

        raise TypeError(
            "Expected int, ResourceField, or ResourceDefinition, "
            f"got {type(resource).__name__!r}."
        )

    def confirm(self) -> None:
        """Confirm a graph after intentionally leaving optional resources unbound."""
        if self._state is GraphState.CONFIRMED:
            raise RuntimeError("The graph is already confirmed.")

        if self._specification.resources:
            if self._state is GraphState.CREATED:
                raise RuntimeError(
                    "Resources must be bound before the graph can be confirmed."
                )

        self._confirm()

    def _validate_required_resources(
        self,
        resources: Mapping[ResourceField, BaseResource],
    ) -> None:
        registry = self._specification.resources
        missing_fields = tuple(
            field
            for field in registry.sources
            if registry.definition_for(field).required and field not in resources
        )

        if missing_fields:
            missing = ", ".join(repr(field) for field in missing_fields)
            raise ValueError(f"Required resources are missing: {missing}.")

    def _confirm(self) -> None:
        self._specification.proceed(self._resource_context.instances)
        self._inspection._proceed()
        self._state = GraphState.CONFIRMED

    def _collect_artifacts(self) -> None:
        flow_by_artifact: dict[Artifact, ArtifactFlow] = {}

        for flow in self._flows:
            artifact = flow.artifact

            if artifact in flow_by_artifact:
                raise ValueError(f"Artifact {artifact!r} is assigned to multiple flows")

            flow_by_artifact[artifact] = flow

        entry_artifacts = {flow.artifact for flow in self._entry_flows}

        generated_artifacts: set[Artifact] = set()
        unused_artifacts: dict[Artifact, None] = {}

        for flow in self._flows:
            for operator in flow.operators:
                for artifact in operator.input_artifacts:
                    if artifact not in flow_by_artifact:
                        raise ValueError(
                            f"Artifact {artifact!r}, consumed by "
                            f"{operator!r}, has no ArtifactFlow"
                        )

                for artifact in operator.output_artifacts:
                    if artifact in flow_by_artifact:
                        generated_artifacts.add(artifact)
                    else:
                        unused_artifacts.setdefault(artifact, None)

        for artifact in flow_by_artifact:
            if artifact in entry_artifacts:
                continue

            if artifact not in generated_artifacts:
                raise ValueError(
                    f"Artifact {artifact!r} has a flow but is neither "
                    "an entry artifact nor generated by an operator"
                )

        ordered_artifacts = tuple(flow_by_artifact) + tuple(unused_artifacts)

        self._artifacts = {}

        for artifact_id, artifact in enumerate(ordered_artifacts):
            if artifact in entry_artifacts:
                role = ArtifactRole.ENTRY
            elif artifact in flow_by_artifact:
                role = ArtifactRole.INTERMEDIATE
            else:
                role = ArtifactRole.UNUSED

            self._artifacts[artifact] = ArtifactDefinition(
                artifact_id=artifact_id,
                name=artifact.name,
                description=artifact.description,
                role=role,
                is_exit=False,
            )

    def _confirm_flows(self) -> None:
        if not self._flows:
            raise ValueError("GraphDefinition requires at least one ArtifactFlow")

        if not all(isinstance(flow, ArtifactFlow) for flow in self._flows):
            raise TypeError("'flows' must contain only ArtifactFlow instances")

        if isinstance(self._entry_flows, ArtifactFlow):
            self._entry_flows = (self._entry_flows,)
        elif isinstance(self._entry_flows, tuple):
            if not all(isinstance(flow, ArtifactFlow) for flow in self._entry_flows):
                raise TypeError(
                    "'entry_flows' must contain only ArtifactFlow instances"
                )
        else:
            raise TypeError(
                "'entry_flows' must be an ArtifactFlow or "
                "tuple of ArtifactFlow instances"
            )

        if not self._entry_flows:
            raise ValueError("GraphDefinition requires at least one entry flow")

        flow_ids = {id(flow) for flow in self._flows}

        if any(id(entry_flow) not in flow_ids for entry_flow in self._entry_flows):
            raise ValueError("Every entry flow must also be included in 'flows'")

    def _generate_layout(self) -> None:
        active_artifacts = set(self.entry_artifacts)

        row_by_artifact = {flow.artifact: row for row, flow in enumerate(self._flows)}

        self._layout = GraphLayout(num_rows=len(self._flows))

        while True:
            positions = self._layout.row_counts

            if all(
                position >= len(flow.operators)
                for position, flow in zip(positions, self._flows)
            ):
                break

            column: list[BaseOperator | None] = [None] * len(self._flows)

            for row, flow in enumerate(self._flows):
                if flow.artifact not in active_artifacts:
                    continue

                position = positions[row]

                if position < len(flow.operators):
                    column[row] = flow.operators[position]

            candidates = {operator for operator in column if operator is not None}

            ready_operators = {
                operator
                for operator in candidates
                if all(
                    column[row_by_artifact[artifact]] is operator
                    for artifact in operator.input_artifacts
                )
            }

            for row, operator in enumerate(column):
                if operator not in ready_operators:
                    column[row] = None

            if not ready_operators:
                raise ValueError(
                    "The graph cannot make further progress. "
                    "Check artifact dependencies and flow ordering."
                )

            consumed_artifacts = {
                artifact
                for operator in ready_operators
                for artifact in operator.input_artifacts
            }

            generated_artifacts = {
                artifact
                for operator in ready_operators
                for artifact in operator.output_artifacts
            }

            self._layout.append(column)

            active_artifacts.difference_update(consumed_artifacts)
            active_artifacts.update(generated_artifacts)

    def _validate_layout(self) -> frozenset[Artifact]:
        active_artifacts = set(self.entry_artifacts)
        active_operator_outputs: set[Artifact] = set()

        for column_index in range(self._layout.shape[1]):
            operators: list[BaseOperator] = []

            for operator in self._layout.col(column_index):
                if operator is None:
                    continue

                if not any(existing is operator for existing in operators):
                    operators.append(operator)

            consumers: dict[Artifact, BaseOperator] = {}
            producers: dict[Artifact, BaseOperator] = {}

            for operator in operators:
                for artifact in operator.input_artifacts:
                    previous_consumer = consumers.get(artifact)

                    if previous_consumer is not None:
                        raise ValueError(
                            f"Fan-out detected at layout column {column_index}: "
                            f"artifact {artifact!r} is consumed by both "
                            f"{previous_consumer!r} and {operator!r}. "
                            "An artifact can be consumed by only one operator. "
                            "Insert an explicit copy/split operator if branching "
                            "is intended."
                        )

                    if artifact not in active_artifacts:
                        raise ValueError(
                            f"Fan-out detected at layout column {column_index}: "
                            f"operator {operator!r} consumes artifact {artifact!r}, "
                            "but that artifact is no longer available. "
                            "It was already consumed and has not been generated again."
                        )

                    consumers[artifact] = operator

                for artifact in operator.output_artifacts:
                    previous_producer = producers.get(artifact)

                    if previous_producer is not None:
                        raise ValueError(
                            f"Fan-in detected at layout column {column_index}: "
                            f"artifact {artifact!r} is produced by both "
                            f"{previous_producer!r} and {operator!r}. "
                            "Multiple operators cannot produce the same artifact "
                            "in one execution stage."
                        )

                    if artifact in active_artifacts and artifact not in consumers:
                        raise ValueError(
                            f"Fan-in detected at layout column {column_index}: "
                            f"operator {operator!r} produces artifact {artifact!r}, "
                            "but a previous value of that artifact is still available. "
                            "The existing artifact must be consumed before it can "
                            "be generated again."
                        )

                    producers[artifact] = operator

            active_artifacts.difference_update(consumers)
            active_artifacts.update(producers)

            active_operator_outputs.difference_update(consumers)
            active_operator_outputs.update(producers)

        return frozenset(active_operator_outputs)

    def _set_exit_artifacts(
        self,
        active_operator_outputs: frozenset[Artifact],
    ) -> None:
        self._artifacts = {
            artifact: replace(
                definition,
                is_exit=(
                    artifact in active_operator_outputs
                    and definition.role is not ArtifactRole.UNUSED
                ),
            )
            for artifact, definition in self._artifacts.items()
        }

    @property
    def layout(self) -> GraphLayout:
        """Computed row-and-column execution layout."""
        return self._layout

    @property
    def flows(self) -> tuple[ArtifactFlow, ...]:
        """Artifact flows in declaration order."""
        return self._flows

    @property
    def inspect(self) -> GraphInspection:
        """Structured inspection of graph artifacts, fields, and requirements."""
        return self._inspection

    @property
    def entry_artifacts(self) -> tuple[Artifact, ...]:
        """Artifacts whose initial values must be supplied by the application."""
        return tuple(
            artifact
            for artifact, definition in self._artifacts.items()
            if definition.role is ArtifactRole.ENTRY
        )

    @property
    def artifacts(self) -> tuple[Artifact, ...]:
        """All artifacts known to the graph in stable order."""
        return tuple(self._artifacts)

    @property
    def state(self) -> GraphState:
        """Current graph construction state."""
        return self._state

    @property
    def confirmed(self) -> bool:
        """Whether the graph is ready to create contexts and submit work."""
        return self._state is GraphState.CONFIRMED

    @cached_property
    def compiled_graph(self) -> CompiledGraph:
        """Validated immutable execution plan for this confirmed graph.

        Compilation is lazy and cached. Access raises if the graph is unconfirmed or
        contains incompatible artifact-property edges.
        """
        if self._state is not GraphState.CONFIRMED:
            raise RuntimeError("The graph must be confirmed before compilation.")

        from ..validation.validator import GraphValidator

        validation = GraphValidator(self).validate()
        if not validation.valid:
            raise ValueError(
                "The graph contains "
                f"{len(validation.mismatched_edges)} incompatible artifact edge(s)."
            )

        row_count, column_count = self.layout.shape

        steps: list[CompiledStep] = []
        successor_indices: list[set[int]] = []
        producer_by_artifact: dict[Artifact, int] = {}
        entry_artifact_set = set(self.entry_artifacts)

        for column in range(column_count):
            compiled_operator_ids: set[int] = set()

            for row in range(row_count):
                operator = self.layout.rows[row][column]

                if operator is None:
                    continue

                operator_id = id(operator)

                if operator_id in compiled_operator_ids:
                    continue

                compiled_operator_ids.add(operator_id)

                artifact_predecessors: set[int] = set()

                for field in operator.bound_artifact_fields:
                    artifact = field.artifact

                    if artifact is None:
                        continue

                    producer_index = producer_by_artifact.get(artifact)

                    if producer_index is not None:
                        artifact_predecessors.add(producer_index)
                    elif artifact not in entry_artifact_set:
                        raise RuntimeError(
                            f"Artifact {artifact!r} has no active producer "
                            f"for operator {operator.display_name!r} at "
                            f"layout position {(row, column)!r}."
                        )

                bound_resources: list[tuple[ResourceField, BaseResource]] = []

                for field in operator.resource_fields:
                    resource = self._resource_context.get(field)

                    if resource is not None:
                        bound_resources.append((field, resource))

                group_start = len(steps)
                operator_index = group_start + len(bound_resources)
                group_indices = tuple(range(group_start, operator_index + 1))

                for field, resource in bound_resources:
                    requirements = self._specification.requirements_for_resource(
                        resource
                    )

                    step = CompiledResourceStep(
                        group_indices=group_indices,
                        successor_indices=frozenset(),
                        initial_dependency_count=len(artifact_predecessors),
                        output_mask=(True,),
                        execution_mode=(
                            ExecutionMode.EVENT_LOOP
                            if inspect.iscoroutinefunction(resource.setup)
                            else ExecutionMode.THREAD
                        ),
                        layout_position=(row, column),
                        requirements=requirements,
                        resource_field=field,
                        resource=resource,
                        config_fields=resource.config_fields,
                        setup_method=resource.setup.__func__,
                        teardown_method=resource.teardown.__func__,
                        resource_name=resource.display_name,
                    )

                    steps.append(step)
                    successor_indices.append(set())

                output_fields = operator.outputs

                output_mask = tuple(
                    field.artifact is not None for field in output_fields
                )

                requirements = self._specification.requirements_for_operator(operator)

                operator_step = CompiledOperatorStep(
                    group_indices=group_indices,
                    successor_indices=frozenset(),
                    initial_dependency_count=(
                        len(artifact_predecessors) + len(bound_resources)
                    ),
                    output_mask=output_mask,
                    execution_mode=(
                        ExecutionMode.EVENT_LOOP
                        if inspect.iscoroutinefunction(operator.execute)
                        else ExecutionMode.THREAD
                    ),
                    layout_position=(row, column),
                    requirements=requirements,
                    execute_method=operator.execute.__func__,
                    bound_artifact_fields=operator.bound_artifact_fields,
                    declared_artifact_fields=operator.declared_artifact_fields,
                    config_fields=operator.config_fields,
                    bound_resources=tuple(bound_resources),
                    output_fields=output_fields,
                    operator_name=operator.display_name,
                )

                steps.append(operator_step)
                successor_indices.append(set())

                for resource_index in range(
                    group_start,
                    operator_index,
                ):
                    successor_indices[resource_index].add(operator_index)

                for predecessor_index in artifact_predecessors:
                    successor_indices[predecessor_index].update(group_indices)

                for field in operator.bound_artifact_fields:
                    artifact = field.artifact

                    if artifact is not None:
                        producer_by_artifact.pop(artifact, None)

                for field, active in zip(
                    output_fields,
                    output_mask,
                ):
                    if active:
                        producer_by_artifact[field.artifact] = operator_index

        compiled_steps = tuple(
            replace(
                step,
                successor_indices=frozenset(successor_indices[index]),
            )
            for index, step in enumerate(steps)
        )

        return CompiledGraph(
            steps=compiled_steps,
            artifacts=self.artifacts,
            entry_artifacts=self.entry_artifacts,
            initial_dependency_counts=tuple(
                step.initial_dependency_count for step in compiled_steps
            ),
            requirements=self._specification.requirements,
        )
