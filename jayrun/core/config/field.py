from dataclasses import dataclass

from ..declaration.field import DeclarativeField
from .values import CONFIG_TYPES, validate_config_value


@dataclass(slots=True, frozen=True, kw_only=True, eq=False)
class ConfigField(DeclarativeField):
    """Declare a portable immutable configuration value for an operator or resource.

    Args:
        name: Optional display name.
        description: Optional explanation of the setting.
        value_type: Required Python type for configured values.
        required: Whether a value must be supplied in the configuration context.
        default: Value used when an optional field is not explicitly configured.
    """

    value_type: type
    default: object | None = None

    def __post_init__(self) -> None:
        DeclarativeField.__post_init__(self)

        if not any(self.value_type is allowed for allowed in CONFIG_TYPES):
            raise TypeError("value_type must be bool, int, float, str or tuple")

        if self.required and self.default is not None:
            raise ValueError("A required ConfigField cannot have a default value")

        if self.default is not None:
            if type(self.default) is not self.value_type:
                raise TypeError(f"default must be an exact {self.value_type.__name__}")
            validate_config_value(self.default, path=self.name or "default")
