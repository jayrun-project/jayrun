from collections.abc import Hashable
from dataclasses import dataclass

from ..declaration.field import DeclarativeField


@dataclass(slots=True, frozen=True, kw_only=True, eq=False)
class ConfigField(DeclarativeField):
    """Declare a hashable configuration value for an operator or resource.

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

        if not isinstance(self.value_type, type):
            raise TypeError(
                f"'value_type' must be a type, got {type(self.value_type).__name__!r}"
            )

        if not issubclass(self.value_type, Hashable):
            raise TypeError(
                f"'value_type' must be hashable, got {self.value_type.__name__!r}"
            )

        if self.required and self.default is not None:
            raise ValueError("A required ConfigField cannot have a default value")

        if self.default is not None and not isinstance(
            self.default,
            self.value_type,
        ):
            raise TypeError(
                f"'default' must be an instance of "
                f"{self.value_type.__name__!r}, "
                f"got {type(self.default).__name__!r}"
            )
