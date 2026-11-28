from ...config.field import ConfigField
from ..definition.field import ConfigDefinition
from .field import FieldRegistry


class ConfigRegistry(FieldRegistry[ConfigField, ConfigDefinition]):
    pass
