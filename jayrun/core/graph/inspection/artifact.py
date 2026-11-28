from collections.abc import Iterator
from typing import TypeVar

from ..definition import ArtifactDefinition, ArtifactRole, FieldDefinition

FieldDefinitionT = TypeVar(
    "FieldDefinitionT",
    bound=FieldDefinition,
)


class ArtifactInspection:
    """Sequence of artifact definitions with role-based views."""

    def __init__(
        self,
        definitions: tuple[ArtifactDefinition, ...],
    ) -> None:
        self._definitions = definitions

    def __iter__(self) -> Iterator[ArtifactDefinition]:
        return iter(self._definitions)

    def __len__(self) -> int:
        return len(self._definitions)

    def __getitem__(self, index: int) -> ArtifactDefinition:
        return self._definitions[index]

    def by_id(self, artifact_id: int) -> ArtifactDefinition:
        """Resolve an exact, nonnegative graph-local artifact ID."""
        if type(artifact_id) is not int:
            raise TypeError("artifact_id must be an integer")
        if 0 <= artifact_id < len(self._definitions):
            definition = self._definitions[artifact_id]
            if definition.artifact_id == artifact_id:
                return definition
        raise KeyError(f"Unknown artifact ID: {artifact_id!r}.")

    @property
    def entry(self) -> tuple[ArtifactDefinition, ...]:
        """Artifacts supplied by the application."""
        return tuple(
            definition
            for definition in self._definitions
            if definition.role is ArtifactRole.ENTRY
        )

    @property
    def intermediate(self) -> tuple[ArtifactDefinition, ...]:
        """Artifacts generated and consumed within the graph."""
        return tuple(
            definition
            for definition in self._definitions
            if definition.role is ArtifactRole.INTERMEDIATE
        )

    @property
    def exit(self) -> tuple[ArtifactDefinition, ...]:
        """Generated artifacts active when the graph completes."""
        return tuple(
            definition for definition in self._definitions if definition.is_exit
        )

    @property
    def unused(self) -> tuple[ArtifactDefinition, ...]:
        """Produced artifacts without a consuming flow; these are also exits.

        The historical name means unused within the graph. It does not mean
        discarded at runtime; use ``exit`` and the run's retention policy.
        """
        return tuple(
            definition for definition in self._definitions
            if definition.role is ArtifactRole.UNUSED
        )

    @property
    def boundary(self) -> tuple[ArtifactDefinition, ...]:
        """Entry and exit artifacts in graph order, without duplicates."""
        return tuple(
            definition for definition in self._definitions
            if definition.role is ArtifactRole.ENTRY or definition.is_exit
        )

    @property
    def all(self) -> tuple[ArtifactDefinition, ...]:
        """All artifact definitions in stable graph order."""
        return self._definitions
