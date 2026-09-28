from collections.abc import Iterable, Mapping

from ..artifact.base import Artifact
from ..config.field import ConfigField
from ..operator.base import BaseOperator
from ..resource.base import BaseResource
from ..resource.field import ResourceField
from ..serializer.base import BaseSerializer
from .definition import (
    ArtifactDefinition,
    ArtifactRole,
    ConfigDefinition,
    RequirementDefinition,
    ResourceDefinition,
    SerializerDefinition,
)
from ._identity import declaration_tokens
from .graph_layout import GraphLayout
from .operator_reference import OperatorReference
from .registry import ArtifactRegistry, ConfigRegistry, ResourceRegistry
from .requirements import merge_requirements, requirement_key


class GraphSpecification:
    def __init__(
        self,
        layout: GraphLayout,
        artifacts: Mapping[Artifact, ArtifactDefinition],
    ) -> None:
        self._operators, occurrences = self._extract_operators(layout)
        self._artifacts = ArtifactRegistry(artifacts)
        self._resources = self._extract_resources()
        self._operator_requirements = self._extract_operator_requirements()
        self._identity_tokens = declaration_tokens(
            self._operators, occurrences, artifacts, self._operator_requirements,
        )
        self._resource_requirements: tuple[RequirementDefinition, ...] | None = None
        self._serializer_requirements: tuple[RequirementDefinition, ...] = ()
        self._serializer_definitions: tuple[SerializerDefinition, ...] = ()
        self._serializers_bound = False
        self._requirements: tuple[RequirementDefinition, ...] | None = None
        self._operator_requirements_by_id: (
            dict[
                int,
                tuple[RequirementDefinition, ...],
            ]
            | None
        ) = None
        self._resource_requirements_by_id: (
            dict[
                int,
                tuple[RequirementDefinition, ...],
            ]
            | None
        ) = None
        self._configs: ConfigRegistry | None = None

    def proceed(
        self,
        resources: Mapping[ResourceField, BaseResource],
    ) -> None:
        if self._configs is not None:
            raise RuntimeError("The graph specification is already complete.")

        expected_fields = set(self._resources.sources)
        provided_fields = set(resources)

        if not provided_fields <= expected_fields:
            raise ValueError(
                "Resources contain fields that do not belong to this graph."
            )

        resource_requirements = self._extract_resource_requirements(resources)
        requirements = merge_requirements(
            str(requirement)
            for requirement in (
                *self._operator_requirements,
                *resource_requirements,
                *self._serializer_requirements,
            )
        )
        operator_requirements_by_id = {
            id(reference.operator): self._select_requirement_definitions(
                reference.operator.requirements,
                requirements,
            )
            for reference in self._operators
        }
        resource_requirements_by_id = {
            id(resource): self._select_requirement_definitions(
                resource.requirements,
                requirements,
            )
            for resource in resources.values()
        }
        configs = self._extract_configs(resources)

        self._resource_requirements = resource_requirements
        self._requirements = requirements
        self._operator_requirements_by_id = operator_requirements_by_id
        self._resource_requirements_by_id = resource_requirements_by_id
        self._configs = configs

    def bind_serializers(
        self,
        serializers: Mapping[Artifact, BaseSerializer],
    ) -> None:
        if self._serializers_bound:
            raise RuntimeError("Serializers are already bound.")

        declarations = tuple(
            requirement
            for serializer in serializers.values()
            for requirement in serializer.requirements
        )
        serializer_requirements = merge_requirements(declarations)
        base_requirements = (
            self._operator_requirements
            if self._resource_requirements is None
            else (*self._operator_requirements, *self._resource_requirements)
        )
        requirements = merge_requirements(
            (
                *(str(requirement) for requirement in base_requirements),
                *declarations,
            )
        )
        definitions = tuple(
            self._create_serializer_definition(
                artifact=artifact,
                serializer=serializer,
                serializer_requirements=serializer_requirements,
            )
            for artifact, serializer in serializers.items()
        )
        operator_requirements_by_id = {
            key: self._select_requirement_definitions(map(str, values), requirements)
            for key, values in (self._operator_requirements_by_id or {}).items()
        }
        resource_requirements_by_id = {
            key: self._select_requirement_definitions(map(str, values), requirements)
            for key, values in (self._resource_requirements_by_id or {}).items()
        }

        self._serializer_requirements = serializer_requirements
        self._serializer_definitions = definitions
        self._serializers_bound = True
        if self._configs is not None:
            self._requirements = requirements
            self._operator_requirements_by_id = operator_requirements_by_id
            self._resource_requirements_by_id = resource_requirements_by_id

    def _create_serializer_definition(
        self,
        *,
        artifact: Artifact,
        serializer: BaseSerializer,
        serializer_requirements: tuple[RequirementDefinition, ...],
    ) -> SerializerDefinition:
        artifact_definition = self._artifacts.definition_for(artifact)
        serializer_type = type(serializer)
        return SerializerDefinition(
            artifact_id=artifact_definition.artifact_id,
            name=serializer.display_name,
            description=serializer.description,
            serializer_type=(
                f"{serializer_type.__module__}.{serializer_type.__qualname__}"
            ),
            requirements=self._select_requirement_definitions(
                serializer.requirements,
                serializer_requirements,
            ),
            is_entry=artifact_definition.role is ArtifactRole.ENTRY,
            is_exit=artifact_definition.is_exit,
        )

    @staticmethod
    def _extract_operators(
        layout: GraphLayout,
    ) -> tuple[tuple[OperatorReference, ...], tuple[int, ...]]:
        row_count, column_count = layout.shape
        declaration_indices: dict[int, int] = {}
        references: list[OperatorReference] = []
        occurrences: list[int] = []
        rows = layout.rows

        for column in range(column_count):
            column_operator_ids: set[int] = set()
            for row in range(row_count):
                operator = rows[row][column]
                if operator is None or id(operator) in column_operator_ids:
                    continue

                operator_id = id(operator)
                column_operator_ids.add(operator_id)
                if operator_id not in declaration_indices:
                    declaration_indices[operator_id] = len(references)
                    references.append(
                        OperatorReference(
                            operator=operator,
                            layout_position=(row, column),
                            config_fields=operator.config_fields,
                            resource_fields=operator.resource_fields,
                        )
                    )
                occurrences.append(declaration_indices[operator_id])

        return tuple(references), tuple(occurrences)

    def _extract_resources(self) -> ResourceRegistry:
        definitions: dict[ResourceField, ResourceDefinition] = {}

        for operator in self._operators:
            for field in operator.resource_fields:
                if field in definitions:
                    continue

                definitions[field] = ResourceDefinition(
                    resource_id=len(definitions),
                    parallel_safe=field.parallel_safe,
                    name=field.name,
                    owner=repr(field.owner),
                    description=field.description,
                    required=field.required,
                    layout_position=operator.layout_position,
                    attribute_name=field.attribute_name,
                )

        return ResourceRegistry(definitions)

    def _extract_operator_requirements(
        self,
    ) -> tuple[RequirementDefinition, ...]:
        return merge_requirements(
            requirement
            for reference in self._operators
            for requirement in reference.operator.requirements
        )

    @staticmethod
    def _extract_resource_requirements(
        resources: Mapping[ResourceField, BaseResource],
    ) -> tuple[RequirementDefinition, ...]:
        declarations: list[str] = []
        processed_resource_ids: set[int] = set()

        for resource in resources.values():
            resource_id = id(resource)

            if resource_id in processed_resource_ids:
                continue

            processed_resource_ids.add(resource_id)
            declarations.extend(resource.requirements)

        return merge_requirements(declarations)

    def _extract_configs(
        self,
        resources: Mapping[ResourceField, BaseResource],
    ) -> ConfigRegistry:
        definitions: dict[ConfigField, ConfigDefinition] = {}

        for operator in self._operators:
            for field in operator.config_fields:
                if field in definitions:
                    continue

                definitions[field] = self._create_config_definition(
                    config_id=len(definitions),
                    field=field,
                    layout_position=operator.layout_position,
                )

        processed_resource_ids: set[int] = set()

        for resource_field, resource in resources.items():
            resource_id = id(resource)

            if resource_id in processed_resource_ids:
                continue

            processed_resource_ids.add(resource_id)

            resource_definition = self._resources.definition_for(resource_field)

            for field in resource.config_fields:
                if field in definitions:
                    continue

                definitions[field] = self._create_config_definition(
                    config_id=len(definitions),
                    field=field,
                    layout_position=resource_definition.layout_position,
                )

        return ConfigRegistry(definitions)

    @staticmethod
    def _create_config_definition(
        config_id: int,
        field: ConfigField,
        layout_position: tuple[int, int],
    ) -> ConfigDefinition:
        return ConfigDefinition(
            config_id=config_id,
            name=field.name,
            owner=repr(field.owner),
            description=field.description,
            required=field.required,
            layout_position=layout_position,
            attribute_name=field.attribute_name,
            value_type=field.value_type,
            default=field.default,
        )

    @property
    def operators(self) -> tuple[OperatorReference, ...]:
        return self._operators

    @property
    def artifacts(self) -> ArtifactRegistry:
        return self._artifacts

    @property
    def resources(self) -> ResourceRegistry:
        return self._resources

    @property
    def configs(self) -> ConfigRegistry:
        if self._configs is None:
            raise RuntimeError(
                "Config definitions are unavailable until resource "
                "selection is finalized."
            )

        return self._configs

    @property
    def operator_requirements(self) -> tuple[RequirementDefinition, ...]:
        return self._operator_requirements

    @property
    def resource_requirements(self) -> tuple[RequirementDefinition, ...]:
        if self._resource_requirements is None:
            raise RuntimeError(
                "Resource requirements are unavailable until resource "
                "selection is finalized."
            )

        return self._resource_requirements

    @property
    def serializer_requirements(self) -> tuple[RequirementDefinition, ...]:
        return self._serializer_requirements

    @property
    def serializer_definitions(self) -> tuple[SerializerDefinition, ...]:
        return self._serializer_definitions

    @property
    def serializers_bound(self) -> bool:
        return self._serializers_bound

    @property
    def requirements(self) -> tuple[RequirementDefinition, ...]:
        if self._requirements is None:
            raise RuntimeError(
                "Requirements are unavailable until resource selection is finalized."
            )

        return self._requirements

    @staticmethod
    def _select_requirement_definitions(
        declarations: Iterable[str],
        requirements: tuple[RequirementDefinition, ...],
    ) -> tuple[RequirementDefinition, ...]:
        definitions_by_key = {
            (definition.name, definition.marker): definition
            for definition in requirements
        }
        definitions: dict[RequirementDefinition, None] = {}

        for declaration in declarations:
            key = requirement_key(declaration)

            try:
                definition = definitions_by_key[key]
            except KeyError as error:
                raise KeyError(
                    f"Requirement {declaration!r} is not registered."
                ) from error

            definitions.setdefault(definition, None)

        return tuple(definitions)

    def requirements_for_operator(
        self,
        operator: BaseOperator,
    ) -> tuple[RequirementDefinition, ...]:
        if self._operator_requirements_by_id is None:
            raise RuntimeError(
                "Operator requirement mappings are unavailable until resource "
                "selection is finalized."
            )

        try:
            return self._operator_requirements_by_id[id(operator)]
        except KeyError as error:
            raise KeyError(f"Operator {operator!r} is not registered.") from error

    def requirements_for_resource(
        self,
        resource: BaseResource,
    ) -> tuple[RequirementDefinition, ...]:
        if self._resource_requirements_by_id is None:
            raise RuntimeError(
                "Resource requirement mappings are unavailable until resource "
                "selection is finalized."
            )

        try:
            return self._resource_requirements_by_id[id(resource)]
        except KeyError as error:
            raise KeyError(f"Resource {resource!r} is not registered.") from error

    @property
    def complete(self) -> bool:
        return self._configs is not None
