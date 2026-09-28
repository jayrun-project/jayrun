from abc import ABC, abstractmethod
from typing import ClassVar

from ..graph.graph_component import GraphComponent


class BaseSerializer(GraphComponent, ABC):
    """Base class for an artifact boundary serializer.

    Serializers convert boundary values to and from bytes. They are bound to
    graph entry and exit artifacts with
    :meth:`~jayrun.GraphDefinition.bind_serializers`. They encode portable
    context snapshots, not the values passed between local graph steps.

    Args:
        name: Optional name used in graph inspection.
        description: Optional explanation of the wire representation.
    """

    __version__: ClassVar[str] = "0.2.0"
    requirements: ClassVar[tuple[str, ...]] = ()

    def __init__(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)

    @property
    def display_name(self) -> str:
        """Configured name, or the serializer class name when unnamed."""
        return self.name or type(self).__name__

    @abstractmethod
    def serialize(self, value: object) -> bytes:
        """Serialize one artifact value.

        Args:
            value: Runtime artifact value.

        Returns:
            Serialized bytes.
        """
        raise NotImplementedError

    @abstractmethod
    def deserialize(self, payload: bytes) -> object:
        """Deserialize one artifact value.

        Args:
            payload: Bytes produced by ``serialize()``.

        Returns:
            Reconstructed artifact value.
        """
        raise NotImplementedError

    def __repr__(self) -> str:
        name = self.name if self.name is not None else "<unnamed>"
        return f"{type(self).__name__}(name={name!r})"
