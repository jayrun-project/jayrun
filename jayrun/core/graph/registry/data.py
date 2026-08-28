from collections.abc import Iterator, Mapping
from typing import Generic, TypeVar

SourceT = TypeVar("SourceT")
DefinitionT = TypeVar("DefinitionT")
ValueT = TypeVar("ValueT")


class DataRegistry(Generic[SourceT, DefinitionT]):
    def __init__(
        self,
        definitions: Mapping[SourceT, DefinitionT],
    ) -> None:
        self._definitions = dict(definitions)
        self._sources = {
            definition: source for source, definition in self._definitions.items()
        }

        if len(self._definitions) != len(self._sources):
            raise ValueError(
                "Definitions must have a one-to-one relationship with sources."
            )

    def definition_for(self, source: SourceT) -> DefinitionT:
        try:
            return self._definitions[source]
        except KeyError as error:
            raise KeyError(f"{source!r} is not registered.") from error

    def source_for(self, definition: DefinitionT) -> SourceT:
        try:
            return self._sources[definition]
        except KeyError as error:
            raise KeyError(f"{definition!r} is not registered.") from error

    def to_definitions(
        self,
        values: Mapping[SourceT, ValueT],
    ) -> dict[DefinitionT, ValueT]:
        return {self.definition_for(source): value for source, value in values.items()}

    def to_sources(
        self,
        values: Mapping[DefinitionT, ValueT],
    ) -> dict[SourceT, ValueT]:
        return {
            self.source_for(definition): value for definition, value in values.items()
        }

    @property
    def sources(self) -> tuple[SourceT, ...]:
        return tuple(self._sources.values())

    @property
    def definitions(self) -> tuple[DefinitionT, ...]:
        return tuple(self._definitions.values())

    def __iter__(self) -> Iterator[DefinitionT]:
        return iter(self._definitions.values())

    def __len__(self) -> int:
        return len(self._definitions)

    def __bool__(self) -> bool:
        return bool(self._definitions)
