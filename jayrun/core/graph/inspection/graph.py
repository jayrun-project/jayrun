from ...resource.context import ResourceContext
from ..definition import ConfigDefinition
from ..graph_specification import GraphSpecification
from ..operator_reference import OperatorReference
from .artifact import ArtifactInspection
from .field import FieldInspection
from .requirement import RequirementInspection
from .serializer import SerializerInspection
from .resource import ResourceInspection


class GraphInspection:
    """Structured declarations discovered from a graph definition."""

    def __init__(
        self,
        specification: GraphSpecification,
        resource_context: ResourceContext | None = None,
    ) -> None:
        self._specification = specification
        self._artifacts = ArtifactInspection(specification.artifacts.definitions)
        self._resources = ResourceInspection(
            specification.resources,
            resource_context if resource_context is not None else ResourceContext(),
        )
        self._requirements = RequirementInspection(specification.operator_requirements)
        self._serializers = SerializerInspection(self._artifacts.boundary)
        self._configs: FieldInspection[ConfigDefinition] | None = None

        if specification.complete:
            self._proceed()

    def _proceed(self) -> None:
        self._configs = FieldInspection[ConfigDefinition](
            self._specification.configs.definitions
        )
        self._requirements._proceed(
            self._specification.resource_requirements,
            self._specification.requirements,
        )

    def _bind_serializers(self) -> None:
        self._serializers._bind(self._specification.serializer_definitions)
        self._requirements._bind_serializers(
            self._specification.serializer_requirements,
            (
                self._specification.requirements
                if self.complete
                else None
            ),
        )

    @property
    def artifacts(self) -> ArtifactInspection:
        """Artifact declarations grouped by graph role."""
        return self._artifacts

    @property
    def resources(self) -> ResourceInspection:
        """Resource declarations, bindings, missing fields, and local sharing."""
        return self._resources

    @property
    def operators(self) -> tuple[OperatorReference, ...]:
        """Operator references, positions, and declared fields in graph order."""
        return self._specification.operators

    @property
    def configs(self) -> FieldInspection[ConfigDefinition]:
        """Configuration declarations available after graph confirmation."""
        if self._configs is None:
            raise RuntimeError(
                "Config inspection is unavailable until resource "
                "selection is finalized."
            )

        return self._configs

    @property
    def requirements(self) -> RequirementInspection:
        """Operator, resource, serializer, and combined requirements."""
        return self._requirements

    @property
    def serializers(self) -> SerializerInspection:
        """Serializer declarations for graph entry and exit artifacts."""
        return self._serializers

    @property
    def complete(self) -> bool:
        """Whether resource selection and configuration discovery are complete."""
        return self._configs is not None
