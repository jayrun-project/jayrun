from collections.abc import Iterator

from ..definition import ArtifactDefinition, SerializerDefinition


class SerializerInspection:
    """Serializer definitions bound to graph boundary artifacts."""

    def __init__(self, boundary: tuple[ArtifactDefinition, ...] = ()) -> None:
        self._definitions: tuple[SerializerDefinition, ...] = ()
        self._boundary = boundary
        self._bound = False

    def _bind(self, definitions: tuple[SerializerDefinition, ...]) -> None:
        if self._bound:
            raise RuntimeError("Serializer inspection is already bound.")
        self._definitions = definitions
        self._bound = True

    def __iter__(self) -> Iterator[SerializerDefinition]:
        return iter(self._definitions)

    def __len__(self) -> int:
        return len(self._definitions)

    def __getitem__(self, index: int) -> SerializerDefinition:
        return self._definitions[index]

    @property
    def entry(self) -> tuple[SerializerDefinition, ...]:
        """Serializers bound to application-supplied artifacts."""
        return tuple(
            definition
            for definition in self._definitions
            if definition.is_entry
        )

    @property
    def exit(self) -> tuple[SerializerDefinition, ...]:
        """Serializers bound to graph-result artifacts."""
        return tuple(
            definition
            for definition in self._definitions
            if definition.is_exit
        )

    @property
    def all(self) -> tuple[SerializerDefinition, ...]:
        """All serializer definitions in stable artifact order."""
        return self._definitions

    @property
    def boundary(self) -> tuple[ArtifactDefinition, ...]:
        """Artifacts that require coverage when boundary serialization is used."""
        return self._boundary

    @property
    def unbound(self) -> tuple[ArtifactDefinition, ...]:
        """Boundary artifacts without a serializer; ordinary graphs allow this."""
        covered = {definition.artifact_id for definition in self._definitions}
        return tuple(field for field in self._boundary if field.artifact_id not in covered)

    @property
    def complete(self) -> bool:
        """Whether every boundary artifact has a serializer, including no boundary."""
        return not self.unbound

    @property
    def bound(self) -> bool:
        """Whether serializer binding was explicitly completed."""
        return self._bound

    @property
    def enabled(self) -> bool:
        """Whether this graph has a serialized artifact boundary."""
        return bool(self._definitions)
