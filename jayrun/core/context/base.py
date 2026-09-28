from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Generic, TypeVar

SourceT = TypeVar("SourceT")
ValueT = TypeVar("ValueT")


class DataContext(Generic[SourceT, ValueT]):
    def __init__(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        if name is not None and not isinstance(name, str):
            raise TypeError("name must be str or None")

        if description is not None and not isinstance(description, str):
            raise TypeError("description must be str or None")

        self._name = name
        self._description = description
        self._instances: dict[SourceT, ValueT] = {}
        self._sealed = False

    def _update_instances(
        self,
        instances: Mapping[SourceT, ValueT],
    ) -> None:
        self._require_mutable()
        self._instances.update(instances)

    def _update_ordered_instances(
        self,
        instances: Mapping[SourceT, ValueT],
    ) -> None:
        self._require_mutable()
        for source, value in instances.items():
            self._instances.pop(source, None)
            self._instances[source] = value

    def _seal(self) -> None:
        self._sealed = True

    def _require_mutable(self) -> None:
        if self._sealed:
            raise RuntimeError("submitted contexts are read-only")

    @property
    def _is_sealed(self) -> bool:
        return self._sealed

    @property
    def name(self) -> str | None:
        """Optional context name."""
        return self._name

    @property
    def description(self) -> str | None:
        """Optional context description."""
        return self._description

    @property
    def instances(self) -> Mapping[SourceT, ValueT]:
        """Read-only view of the context's current source-to-value mapping."""
        return MappingProxyType(self._instances)
