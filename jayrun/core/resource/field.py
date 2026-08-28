from dataclasses import dataclass

from ..declaration.field import DeclarativeField


@dataclass(slots=True, frozen=True, kw_only=True, eq=False)
class ResourceField(DeclarativeField):
    """Declare a managed resource dependency on an operator.

    Args:
        name: Optional display name.
        description: Optional explanation of the dependency.
        required: Whether a resource must be bound before graph confirmation.
        parallel_safe: Whether concurrent executions may use the same resource
            instance.
    """

    parallel_safe: bool = True

    def __post_init__(self) -> None:
        DeclarativeField.__post_init__(self)

        if not isinstance(self.parallel_safe, bool):
            raise TypeError(
                f"'parallel_safe' must be a bool, got {type(self.parallel_safe).__name__!r}."
            )
