from collections.abc import Mapping

from ...config.field import ConfigField
from ..definition.field import ConfigDefinition
from .field import FieldRegistry


class ConfigRegistry(FieldRegistry[ConfigField, ConfigDefinition]):
    def __init__(self, definitions: Mapping[ConfigField, ConfigDefinition]) -> None:
        super().__init__(definitions)
        # Registry membership is fixed at construction. Keep the actual sources
        # alive and compare identity, never user-defined equality or hashing.
        self._sources_by_identity = {id(source): source for source in self.sources}

    def _contains_source(self, source: ConfigField) -> bool:
        return self._sources_by_identity.get(id(source)) is source
