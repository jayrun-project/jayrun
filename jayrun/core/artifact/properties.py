from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Generic, Self, TypeVar

T = TypeVar("T")


class ArtifactProperty(ABC, Generic[T]):
    """Base class for one statically validated artifact characteristic.

    Args:
        value: Declared property value.
    """

    def __init__(self, value: T) -> None:
        self._validate_value(value)
        self._value = value

    @property
    def value(self) -> T:
        """Normalized declared value."""
        return self._value

    def _validate_value(self, value: T) -> None:
        pass

    @abstractmethod
    def accepts(self, output: Self) -> bool:
        """Return whether a producer property satisfies this consumer property.

        Args:
            output: Property declared by the producing output field.
        """
        pass


class TypeProperty(ArtifactProperty[type]):
    """Require an exact Python value type."""

    def _validate_value(self, value: type) -> None:
        if not isinstance(value, type):
            raise TypeError("Expected a Python type.")

    def accepts(self, output: Self) -> bool:
        return self.value is output.value


class DTypeProperty(ArtifactProperty[tuple[object, ...]]):
    """Require at least one shared dtype from a set of accepted values.

    Args:
        value: One dtype or an iterable of acceptable dtypes.
    """

    def __init__(self, value: object | Iterable[object]) -> None:
        if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
            values = tuple(value)
        else:
            values = (value,)

        super().__init__(values)

    def _validate_value(self, value: tuple[object, ...]) -> None:
        if len(value) == 0:
            raise ValueError("Expected at least one dtype.")

    def accepts(self, output: Self) -> bool:
        return not set(self.value).isdisjoint(output.value)


class ShapeProperty(ArtifactProperty[tuple[int | None, ...]]):
    """Require a tensor-like shape, using ``None`` as a consumer wildcard."""

    def _validate_value(self, value: tuple[int | None, ...]) -> None:
        for dimension in value:
            if dimension is not None and not isinstance(dimension, int):
                raise TypeError("Shape dimensions must be integers or None.")

    def accepts(self, output: Self) -> bool:
        if len(self.value) != len(output.value):
            return False

        for input_artifact, output_artifact in zip(self.value, output.value):
            if input_artifact is None and output_artifact is not None:
                continue
            if input_artifact != output_artifact:
                return False

        return True


class DeviceProperty(ArtifactProperty[str]):
    """Require an exact device name such as ``\"cpu\"`` or ``\"cuda\"``."""

    def _validate_value(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("Expected a device name.")

    def accepts(self, output: Self) -> bool:
        return self.value == output.value


class BackendProperty(ArtifactProperty[str]):
    """Require an exact data backend name such as ``\"torch\"``."""

    def _validate_value(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("Expected a backend name.")

    def accepts(self, output: Self) -> bool:
        return self.value == output.value
