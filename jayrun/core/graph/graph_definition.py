from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import replace
from functools import cached_property
from typing import TYPE_CHECKING

from ...engine.execution.execution_mode import ExecutionMode
from ..artifact.base import Artifact
from ..config.field import ConfigField
from ..operator.base import BaseOperator
from ..resource.base import BaseResource
from ..resource.context import ResourceContext
from ..resource.field import ResourceField
from ..serializer.base import BaseSerializer
from .artifact_flow import ArtifactFlow
from .compiled_graph import (
    CompiledGraph,
    CompiledOperatorStep,
    CompiledResourceStep,
    CompiledStep,
)
from .definition.artifact import ArtifactDefinition, ArtifactRole
from .definition.field import ConfigDefinition, ResourceDefinition
from .graph_layout import GraphLayout
from .graph_specification import GraphSpecification
from .graph_state import GraphState
from .inspection.graph import GraphInspection

if TYPE_CHECKING:
    from ..validation.graph import GraphValidationReport
    from ...visualization.adapters.definition import GraphPlotter
    from .reporting import GraphReporter


class GraphDefinition:
    """Define and confirm an executable artifact graph.

    Graph construction freezes topology and identifies every produced artifact
    whose final value has no later consumer as an exit, including outputs without
    their own flow. Per-run artifact policy selects retained exit values. Every graph requires an explicit confirm() after all bindings and timing
    configuration are complete.
    Finish construction and binding before sharing a graph across threads.

    Args:
        *flows: Every artifact flow in the graph.
        entry_flows: Flow or flows whose initial artifact values are supplied by the
            application. Omit this argument when every flow starts from an
            independent zero-input operator.
        version: Non-empty graph version used as part of registry identity.
    """

    def __init__(
        self,
        *flows: ArtifactFlow,
        entry_flows: ArtifactFlow | tuple[ArtifactFlow, ...] = (),
        version: str = "1",
    ) -> None:
        if not isinstance(version, str):
            raise TypeError("'version' must be a string")
        if not version.strip():
            raise ValueError("'version' must not be empty")

        self._timing_config_fields: tuple[ConfigField, ...] | None = None
        self._version = version
        self._sealed = False
        self._serializers_bound = False
        self._serializer_bindings: dict[Artifact, BaseSerializer] = {}
        self._entry_flows = entry_flows
        self._flows = flows

        self._confirm_flows()
        self._collect_artifacts()
        self._generate_layout()
        active_operator_outputs = self._validate_layout()
        self._layout._freeze()
        self._set_exit_artifacts(active_operator_outputs)

        self._state = GraphState.CREATED

        self._specification = GraphSpecification(
            self._layout,
            artifacts=self._artifacts,
        )
        self._resource_context = ResourceContext()
        self._inspection = GraphInspection(self._specification, self._resource_context)


    def bind_resources(
        self,
        resources: Mapping[
            int | ResourceField | ResourceDefinition,
            BaseResource,
        ],
    ) -> None:
        """Bind resource instances to graph resource fields.

        Invalid selection, requirements, or configuration discovery leave the
        graph unbound and permit retry. Optional omissions still require confirm().
        Construction and binding must finish before sharing a graph across threads.

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

        candidate = ResourceContext()
        candidate.set(ordered_resources)
        # Discovery stages all fallible input checks before committing selection.
        self._specification.proceed(candidate.instances)
        self._resource_context.set(candidate.instances)
        self._state = GraphState.RESOURCES_BOUND


    def select_timing_configs(
        self,
        *configs: int | ConfigField | ConfigDefinition,
    ) -> None:
        """Select which resolved config values partition timing history.

        Omit this call to use all effective fields. Calling it with no fields
        explicitly ignores config differences for timing reuse; other execution
        compatibility checks still apply. Diagnostic history retains the full
        configuration independently. This does not alter graph_id or execution.

        Use exact declarations or existing graph-local IDs/definitions, not field
        names. Resource-owned fields become available after resource binding.
        Selection replaces the previous selection atomically and is forbidden
        after confirmation, including repeated identical calls. Call confirm()
        only after selection is complete.
        """
        if self.confirmed:
            raise RuntimeError("The graph is already confirmed.")
        specification = self._specification
        registry = (specification.configs if specification.complete else
                    specification._extract_configs(self._resource_context.instances))
        selected: set[ConfigField] = set()
        for reference in configs:
            if isinstance(reference, ConfigField):
                field = next((field for field in registry.sources if field is reference), None)
            elif type(reference) is int:
                field = next((registry.source_for(d) for d in registry.definitions
                              if d.config_id == reference), None)
            elif isinstance(reference, ConfigDefinition):
                field = next((registry.source_for(d) for d in registry.definitions
                              if d is reference), None)
            else:
                raise TypeError("Expected int, ConfigField, or ConfigDefinition for timing selection.")
            if field is None:
                raise KeyError("Timing config does not belong to the currently discovered graph fields.")
            if field in selected:
                raise ValueError("Multiple timing config references resolve to the same ConfigField.")
            selected.add(field)
        self._timing_config_fields = tuple(field for field in registry.sources if field in selected)

    def bind_serializers(
        self,
        serializers: Mapping[
            int | Artifact | ArtifactDefinition,
            BaseSerializer,
        ],
    ) -> None:
        """Bind serializers to the complete graph boundary.

        Serializer binding is optional. When a non-empty mapping is supplied, it
        must bind every entry and exit artifact and no intermediate artifacts.
        Binding is atomic and may occur once before explicit graph confirmation.

        Args:
            serializers: Mapping from graph-local artifact IDs, artifacts, or
                inspected artifact definitions to serializer instances.

        Raises:
            TypeError: If the mapping, a reference, or a serializer has an
                unsupported type.
            KeyError: If an artifact reference does not belong to this graph.
            ValueError: If aliases are duplicated or boundary coverage is partial.
            RuntimeError: If serializers were already bound or the graph is sealed.
        """
        if self._sealed:
            raise RuntimeError("The graph is sealed.")
        if self._serializers_bound:
            raise RuntimeError("Serializers are already bound.")
        if not isinstance(serializers, Mapping):
            raise TypeError("Expected a mapping of serializers.")

        registry = self._specification.artifacts
        definitions_by_id = {
            definition.artifact_id: definition
            for definition in registry.definitions
        }
        resolved: dict[Artifact, BaseSerializer] = {}

        for reference, serializer in serializers.items():
            artifact = self._resolve_serializer_artifact(
                reference,
                definitions_by_id=definitions_by_id,
            )
            if artifact in resolved:
                raise ValueError(
                    "Multiple serializer keys resolve to the same Artifact."
                )
            if not isinstance(serializer, BaseSerializer):
                raise TypeError("Serializer values must be BaseSerializer instances.")
            resolved[artifact] = serializer

        boundary = tuple(
            artifact
            for artifact, definition in self._artifacts.items()
            if definition.role is ArtifactRole.ENTRY or definition.is_exit
        )
        if resolved:
            missing = tuple(
                artifact for artifact in boundary if artifact not in resolved
            )
            extra = tuple(artifact for artifact in resolved if artifact not in boundary)
            if missing or extra:
                raise ValueError(
                    "Serializers must bind every entry and exit artifact and no "
                    f"other artifacts; missing={missing!r}, extra={extra!r}."
                )

        ordered = {
            artifact: resolved[artifact]
            for artifact in boundary
            if artifact in resolved
        }
        self._specification.bind_serializers(ordered)
        self._serializer_bindings = ordered
        self._serializers_bound = True
        self._inspection._bind_serializers()
        self.__dict__.pop("_compiled_graph", None)

    def _resolve_serializer_artifact(
        self,
        reference: int | Artifact | ArtifactDefinition,
        *,
        definitions_by_id: Mapping[int, ArtifactDefinition],
    ) -> Artifact:
        registry = self._specification.artifacts

        if type(reference) is int:
            try:
                definition = definitions_by_id[reference]
            except KeyError:
                raise KeyError(f"Unknown artifact ID: {reference!r}.") from None
            return registry.source_for(definition)

        if isinstance(reference, ArtifactDefinition):
            for definition in registry.definitions:
                if definition is reference:
                    return registry.source_for(definition)
            raise KeyError("The ArtifactDefinition does not belong to this graph.")

        if isinstance(reference, Artifact):
            if reference not in registry.sources:
                raise KeyError("The Artifact does not belong to this graph.")
            return reference

        raise TypeError(
            "Serializer references must be int, Artifact, or ArtifactDefinition"
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
        """Finalize resource selection, accepting any unbound optional resources.

        May be called directly when every resource field is optional. Required
        resources must be bound first. Confirmation completes configuration and
        requirement discovery and rejects known artifact-contract mismatches.
        Serializer and timing bindings are frozen. Operators and resources are not executed.
        """
        if self._state is GraphState.CONFIRMED:
            raise RuntimeError("The graph is already confirmed.")

        self._validate_required_resources(self._resource_context.instances)

        validation = self.validate()
        if not validation.valid:
            raise ValueError(f"The graph contains {len(validation.mismatched_edges)} incompatible artifact edge(s).")
        self._confirm()
        self._seal()

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
        if not self._specification.complete:
            self._specification.proceed(self._resource_context.instances)
        self._inspection._proceed()
        self._state = GraphState.CONFIRMED

    def _seal(self) -> None:
        self._sealed = True

    def _collect_artifacts(self) -> None:
        flow_by_artifact: dict[Artifact, ArtifactFlow] = {}

        for flow in self._flows:
            artifact = flow.artifact

            if artifact is None:
                continue

            if artifact in flow_by_artifact:
                raise ValueError(f"Artifact {artifact!r} is assigned to multiple flows")

            flow_by_artifact[artifact] = flow

        entry_artifacts = {
            flow.artifact
            for flow in self._entry_flows
            if flow.artifact is not None
        }

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

        flow_ids = {id(flow) for flow in self._flows}

        if any(id(entry_flow) not in flow_ids for entry_flow in self._entry_flows):
            raise ValueError("Every entry flow must also be included in 'flows'")

        for entry_flow in self._entry_flows:
            if entry_flow.artifact is None:
                raise ValueError("An artifact-free flow cannot be an entry flow")
            if not entry_flow.operators[0].input_artifacts:
                raise ValueError(
                    "An entry flow must start with an operator that consumes its "
                    "artifact"
                )

    def _generate_layout(self) -> None:
        active_artifacts = set(self.entry_artifacts)

        row_by_artifact = {
            flow.artifact: row
            for row, flow in enumerate(self._flows)
            if flow.artifact is not None
        }

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
                position = positions[row]

                if position >= len(flow.operators):
                    continue

                operator = flow.operators[position]
                is_independent_root = position == 0 and not operator.input_artifacts

                if is_independent_root or flow.artifact in active_artifacts:
                    column[row] = operator

            candidates = {operator for operator in column if operator is not None}

            ready_operators = {
                operator
                for operator in candidates
                if all(
                    column[row_by_artifact[artifact]] is operator
                    for artifact in operator.input_artifacts
                )
            }

            if not ready_operators:
                blocked = []
                for row, flow in enumerate(self._flows):
                    position = positions[row]
                    if position >= len(flow.operators):
                        continue
                    operator = flow.operators[position]
                    missing = tuple(
                        artifact for artifact in operator.input_artifacts
                        if artifact not in active_artifacts
                    )
                    waiting = tuple(
                        f"{artifact!r} at flow row {row_by_artifact[artifact]}"
                        for artifact in operator.input_artifacts
                        if column[row_by_artifact[artifact]] is not operator
                    )
                    blocked.append(
                        f"operator {operator.display_name!r} at flow row {row}, "
                        f"position {position}: unavailable artifacts={missing!r}; "
                        f"waiting for flow alignment={waiting!r}"
                    )
                raise ValueError(
                    "The graph cannot make further progress. "
                    + "; ".join(blocked)
                    + ". Check entry_flows for missing initial values and check "
                    "consumption order across flows."
                )

            for row, operator in enumerate(column):
                if operator not in ready_operators:
                    column[row] = None

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
                is_exit=artifact in active_operator_outputs,
            )
            for artifact, definition in self._artifacts.items()
        }


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
    def version(self) -> str:
        """Immutable version used with a registry key to identify this graph."""
        return self._version

    @property
    def graph_id(self) -> str:
        """Cached ``jrg1:`` declaration fingerprint, independent of registration.

        The same ordered declaration, supported static contracts and graph version
        reproduce this ID. Independent branch reorderings may differ. Labels,
        config defaults/values, resource and serializer bindings, implementation
        code and runtime state are excluded. Opaque contracts contribute only
        their qualified type; use ``version`` for otherwise invisible revisions.

        First access hashes construction-frozen tokens; later reads return the
        cached string without traversal. Access does not confirm, seal, compile,
        render or perform I/O. An ID is correlation metadata, not executable
        equivalence, registry identity or authority. Equality/hash are unchanged.
        """
        return self._graph_id

    @cached_property
    def _graph_id(self) -> str:
        from ._identity import graph_id

        return graph_id(self._version, self._specification._identity_tokens)

    @property
    def confirmed(self) -> bool:
        """Whether resource selection and configuration discovery are complete.

        Confirmation rejects known artifact-contract mismatches; unknown static
        contracts do not establish runtime correctness.
        """
        return self._state is GraphState.CONFIRMED

    @property
    def _has_complete_boundary_serializers(self) -> bool:
        boundary = (
            artifact
            for artifact, definition in self._artifacts.items()
            if definition.role is ArtifactRole.ENTRY or definition.is_exit
        )
        return all(
            artifact in self._serializer_bindings for artifact in boundary
        )

    def validate(self) -> GraphValidationReport:
        """Return the cached artifact-contract validation result.

        Available before resource confirmation. This does not execute operators,
        load resources, or compile the graph. Unknown contracts are distinct from
        mismatches; a valid result does not establish runtime correctness.
        """
        return self._validation_result

    @cached_property
    def _validation_result(self) -> GraphValidationReport:
        from ..validation.validation import GraphValidation

        return GraphValidation(self)()

    @cached_property
    def report(self) -> GraphReporter:
        """Combined graph declarations, dependencies, bindings, and validation.

        Provides format, print, and save methods, with optional compact output.
        Binding information is refreshed whenever the report is formatted.
        """
        from .reporting import GraphReporter, _format_graph

        return GraphReporter(lambda compact: _format_graph(self, compact), "graph_report.txt")

    @cached_property
    def plot(self) -> GraphPlotter:
        """Offline definition viewer with current declared resource bindings.

        show() opens a snapshot; save(path) exports the same portable viewer.
        Each call refreshes binding evidence without compiling or executing work.
        """
        from ...visualization.adapters.definition import GraphPlotter

        return GraphPlotter(self.validate(), self.artifacts, graph=self)


    @cached_property
    def _compiled_graph(self) -> CompiledGraph:
        if self._state is not GraphState.CONFIRMED:
            raise RuntimeError("The graph must be confirmed before compilation.")

        validation = self.validate()
        if not validation.valid:
            raise ValueError(
                "The graph contains "
                f"{len(validation.mismatched_edges)} incompatible artifact edge(s)."
            )

        row_count, column_count = self._layout.shape

        steps: list[CompiledStep] = []
        successor_indices: list[set[int]] = []
        producer_by_artifact: dict[Artifact, int] = {}
        entry_artifact_set = set(self.entry_artifacts)

        for column in range(column_count):
            compiled_operator_ids: set[int] = set()

            for row in range(row_count):
                operator = self._layout.rows[row][column]

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
            version=self.version,
            steps=compiled_steps,
            artifacts=self.artifacts,
            entry_artifacts=self.entry_artifacts,
            serializers=tuple(self._serializer_bindings.items()),
            initial_dependency_counts=tuple(
                step.initial_dependency_count for step in compiled_steps
            ),
            requirements=self._specification.requirements,
        )
