from __future__ import annotations

from collections.abc import Mapping

from ..context.base import DataContext
from .base import BaseResource
from .field import ResourceField


class ResourceContext(DataContext[ResourceField, BaseResource]):
    def set(
        self,
        resources: Mapping[ResourceField, BaseResource],
    ) -> None:
        if not isinstance(resources, Mapping):
            raise TypeError("Expected a mapping of ResourceField to BaseResource.")

        instances: dict[ResourceField, BaseResource] = {}

        for field, resource in resources.items():
            if not isinstance(field, ResourceField):
                raise TypeError(
                    f"Expected ResourceField key, got {type(field).__name__!r}."
                )

            if not isinstance(resource, BaseResource):
                raise TypeError(
                    f"Expected BaseResource value for {field!r}, "
                    f"got {type(resource).__name__!r}."
                )

            instances[field] = resource

        self._update_instances(instances)

    def get(
        self,
        field: ResourceField,
    ) -> BaseResource | None:
        if not isinstance(field, ResourceField):
            raise TypeError(f"Expected ResourceField, got {type(field).__name__!r}.")

        return self._instances.get(field)
