from ..definition import ConfigDefinition, ResourceDefinition
from ..graph_specification import GraphSpecification
from .artifact import ArtifactInspection
from .field import FieldInspection
from .requirement import RequirementInspection


class GraphInspection:
    """Structured declarations discovered from a graph definition."""

    def __init__(
        self,
        specification: GraphSpecification,
    ) -> None:
        self._specification = specification
        self._artifacts = ArtifactInspection(specification.artifacts.definitions)
        self._resources = FieldInspection[ResourceDefinition](
            specification.resources.definitions
        )
        self._requirements = RequirementInspection(specification.operator_requirements)
        self._configs: FieldInspection[ConfigDefinition] | None = None

        if specification.complete:
            self._proceed()

    def proceed(self) -> None:
        """Complete inspection after graph resource selection is finalized."""
        if self._configs is not None:
            raise RuntimeError("The graph inspection is already complete.")

        if not self._specification.complete:
            raise RuntimeError("The graph specification is not complete.")

        self._proceed()

    def _proceed(self) -> None:
        self._configs = FieldInspection[ConfigDefinition](
            self._specification.configs.definitions
        )
        self._requirements.proceed(
            self._specification.resource_requirements,
            self._specification.requirements,
        )

    @property
    def artifacts(self) -> ArtifactInspection:
        """Artifact declarations grouped by graph role."""
        return self._artifacts

    @property
    def resources(self) -> FieldInspection[ResourceDefinition]:
        """Required and optional resource-field declarations."""
        return self._resources

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
        """Operator, resource, and combined package requirements."""
        return self._requirements

    @property
    def complete(self) -> bool:
        """Whether resource selection and configuration discovery are complete."""
        return self._configs is not None
