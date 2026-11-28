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
        self._sources = tuple(definitions)
        self._definitions = tuple(definitions.values())
        self._definition_by_source = {id(s): d for s, d in definitions.items()}
        self._source_by_definition = {id(d): s for s, d in definitions.items()}
        if len(self._sources) != len(self._source_by_definition):
            raise ValueError("Definitions must have a one-to-one relationship with sources.")

    def _contains_source(self, source: SourceT) -> bool:
        # Strong references in the registry keep these object IDs live.
        return id(source) in self._definition_by_source

    def definition_for(self, source: SourceT) -> DefinitionT:
        try:
            return self._definition_by_source[id(source)]
        except KeyError:
            raise KeyError(f"{type(source).__name__} does not belong to this graph.") from None

    def source_for(self, definition: DefinitionT) -> SourceT:
        try:
            return self._source_by_definition[id(definition)]
        except KeyError:
            raise KeyError(f"{type(definition).__name__} does not belong to this graph.") from None

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
        return self._sources

    @property
    def definitions(self) -> tuple[DefinitionT, ...]:
        return self._definitions

    def __iter__(self) -> Iterator[DefinitionT]:
        return iter(self._definitions)

    def __len__(self) -> int:
        return len(self._definitions)

    def __bool__(self) -> bool:
        return bool(self._definitions)
