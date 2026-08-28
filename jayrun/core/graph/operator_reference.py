from dataclasses import dataclass

from ..config.field import ConfigField
from ..operator.base import BaseOperator
from ..resource.field import ResourceField


@dataclass(slots=True, frozen=True, kw_only=True, eq=False)
class OperatorReference:
    operator: BaseOperator
    layout_position: tuple[int, int]
    config_fields: tuple[ConfigField, ...]
    resource_fields: tuple[ResourceField, ...]
