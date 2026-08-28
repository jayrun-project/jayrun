from collections.abc import Iterator
from typing import Generic, TypeVar

from ..definition import FieldDefinition

FieldDefinitionT = TypeVar(
    "FieldDefinitionT",
    bound=FieldDefinition,
)


class FieldInspection(Generic[FieldDefinitionT]):
    """Sequence of field definitions with required and optional views."""

    def __init__(
        self,
        definitions: tuple[FieldDefinitionT, ...],
    ) -> None:
        self._definitions = definitions

    def __iter__(self) -> Iterator[FieldDefinitionT]:
        return iter(self._definitions)

    def __len__(self) -> int:
        return len(self._definitions)

    def __getitem__(self, index: int) -> FieldDefinitionT:
        return self._definitions[index]

    @property
    def required(self) -> tuple[FieldDefinitionT, ...]:
        """Definitions whose values or bindings are required."""
        return tuple(
            definition for definition in self._definitions if definition.required
        )

    @property
    def optional(self) -> tuple[FieldDefinitionT, ...]:
        """Definitions whose values or bindings may be omitted."""
        return tuple(
            definition for definition in self._definitions if not definition.required
        )

    @property
    def all(self) -> tuple[FieldDefinitionT, ...]:
        """All field definitions in stable graph order."""
        return self._definitions
