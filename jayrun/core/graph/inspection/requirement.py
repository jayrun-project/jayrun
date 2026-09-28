from ..definition import RequirementDefinition


class RequirementInspection:
    """Package requirements collected from graph components and serializers."""

    def __init__(
        self,
        operator_requirements: tuple[RequirementDefinition, ...],
    ) -> None:
        self._operators = operator_requirements
        self._resources: tuple[RequirementDefinition, ...] | None = None
        self._serializers: tuple[RequirementDefinition, ...] = ()
        self._serializers_bound = False
        self._all: tuple[RequirementDefinition, ...] | None = None

    def _proceed(
        self,
        resource_requirements: tuple[RequirementDefinition, ...],
        requirements: tuple[RequirementDefinition, ...],
    ) -> None:
        """Attach resource and combined requirements after resource binding."""
        if self._resources is not None:
            raise RuntimeError("Requirement inspection is already complete.")

        self._resources = resource_requirements
        self._all = requirements

    def _bind_serializers(
        self,
        serializer_requirements: tuple[RequirementDefinition, ...],
        requirements: tuple[RequirementDefinition, ...] | None,
    ) -> None:
        """Attach serializer requirements after boundary binding."""
        if self._serializers_bound:
            raise RuntimeError("Serializer requirements are already bound.")
        self._serializers = serializer_requirements
        self._serializers_bound = True
        if requirements is not None:
            self._all = requirements

    @property
    def operators(self) -> tuple[RequirementDefinition, ...]:
        """Requirements declared by graph operators."""
        return self._operators

    @property
    def resources(self) -> tuple[RequirementDefinition, ...]:
        """Requirements declared by selected resources."""
        if self._resources is None:
            raise RuntimeError(
                "Resource requirements are unavailable until resource "
                "selection is finalized."
            )

        return self._resources

    @property
    def serializers(self) -> tuple[RequirementDefinition, ...]:
        """Requirements introduced by bound boundary serializers."""
        return self._serializers

    @property
    def all(self) -> tuple[RequirementDefinition, ...]:
        """Combined operator, resource, and serializer requirements."""
        if self._all is None:
            raise RuntimeError(
                "Combined requirements are unavailable until resource "
                "selection is finalized."
            )

        return self._all

    @property
    def complete(self) -> bool:
        """Whether resource requirements have been attached."""
        return self._resources is not None
