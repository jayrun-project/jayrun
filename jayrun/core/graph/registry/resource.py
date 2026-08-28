from ...resource.field import ResourceField
from ..definition.field import ResourceDefinition
from .field import FieldRegistry


class ResourceRegistry(FieldRegistry[ResourceField, ResourceDefinition]):
    pass
