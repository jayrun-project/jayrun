from ..definition import RequirementDefinition


class RequirementInspection:
    """Package requirements collected from operators and bound resources."""

    def __init__(
        self,
        operator_requirements: tuple[RequirementDefinition, ...],
    ) -> None:
        self._operators = operator_requirements
        self._resources: tuple[RequirementDefinition, ...] | None = None
        self._all: tuple[RequirementDefinition, ...] | None = None

    def proceed(
        self,
        resource_requirements: tuple[RequirementDefinition, ...],
        requirements: tuple[RequirementDefinition, ...],
    ) -> None:
        """Attach resource and combined requirements after resource binding."""
        if self._resources is not None:
            raise RuntimeError("Requirement inspection is already complete.")

        self._resources = resource_requirements
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
    def all(self) -> tuple[RequirementDefinition, ...]:
        """Deduplicated operator and resource requirements."""
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
