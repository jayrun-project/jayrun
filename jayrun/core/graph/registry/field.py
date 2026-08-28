from typing import Generic, TypeVar

from ...config.field import ConfigField
from ...resource.field import ResourceField
from ..definition.field import ConfigDefinition, ResourceDefinition
from .data import DataRegistry

FieldT = TypeVar("FieldT", ConfigField, ResourceField)
FieldDefinitionT = TypeVar(
    "FieldDefinitionT",
    ConfigDefinition,
    ResourceDefinition,
)


class FieldRegistry(
    DataRegistry[FieldT, FieldDefinitionT],
    Generic[FieldT, FieldDefinitionT],
):
    pass
