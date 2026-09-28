from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING

from ...resource.base import BaseResource
from ...resource.context import ResourceContext
from ..definition import ResourceDefinition
from ..registry import ResourceRegistry
from .field import FieldInspection

if TYPE_CHECKING:
    from ..graph_registry import GraphRegistry
    from .registry import GraphIdentity


class ResourceInspection(FieldInspection[ResourceDefinition]):
    """Resource declarations and current bindings in graph order."""

    def __init__(
        self, registry: ResourceRegistry, context: ResourceContext
    ) -> None:
        super().__init__(registry.definitions)
        self._registry = registry
        self._context = context

    @property
    def bindings(self) -> Mapping[ResourceDefinition, BaseResource]:
        """Read-only snapshot mapping bound declarations to resource instances."""
        instances = self._context.instances
        return MappingProxyType({
            self._registry.definition_for(field): instances[field]
            for field in self._registry.sources
            if field in instances
        })

    @property
    def unbound(self) -> tuple[ResourceDefinition, ...]:
        """Required and optional fields without a selected resource."""
        bindings = self.bindings
        return tuple(field for field in self.all if field not in bindings)

    @property
    def missing(self) -> tuple[ResourceDefinition, ...]:
        """Required fields without a selected resource."""
        return tuple(field for field in self.unbound if field.required)

    @property
    def shared(self) -> tuple[tuple[ResourceDefinition, ...], ...]:
        """Field groups bound to the same instance, with at least two fields.

        Groups follow first binding order. Identity, rather than equality or
        resource name, determines membership. This describes graph bindings,
        not runtime value reuse or concurrent execution safety.
        """
        groups: dict[int, list[ResourceDefinition]] = {}
        for field, resource in self.bindings.items():
            groups.setdefault(id(resource), []).append(field)
        return tuple(tuple(fields) for fields in groups.values() if len(fields) > 1)


class RegistryResourceInspection:
    """Resource bindings and sharing across registered graph identities."""

    def __init__(self, registry: GraphRegistry) -> None:
        self._registry = registry

    @property
    def bindings(
        self,
    ) -> Mapping[GraphIdentity, Mapping[ResourceDefinition, BaseResource]]:
        """Read-only binding snapshots grouped in registration order."""
        return MappingProxyType({
            identity: graph.inspect.resources.bindings
            for identity, graph in self._registry._entries()
        })

    @property
    def unbound(self) -> Mapping[GraphIdentity, tuple[ResourceDefinition, ...]]:
        """Unbound fields grouped by graph, including empty groups."""
        return MappingProxyType({
            identity: graph.inspect.resources.unbound
            for identity, graph in self._registry._entries()
        })

    @property
    def missing(self) -> Mapping[GraphIdentity, tuple[ResourceDefinition, ...]]:
        """Missing required fields grouped by graph, including empty groups."""
        return MappingProxyType({
            identity: graph.inspect.resources.missing
            for identity, graph in self._registry._entries()
        })

    @property
    def shared(
        self,
    ) -> tuple[Mapping[GraphIdentity, tuple[ResourceDefinition, ...]], ...]:
        """Groups using one resource instance in at least two graphs.

        Each read-only group maps graph identities to their participating
        resource fields. Groups follow first binding order. Local-only sharing
        remains available through each graph's inspection. These are binding
        facts, not guarantees about sharing runtime values across machines.
        """
        groups: dict[int, dict[GraphIdentity, list[ResourceDefinition]]] = {}
        for identity, bindings in self.bindings.items():
            for field, resource in bindings.items():
                groups.setdefault(id(resource), {}).setdefault(identity, []).append(field)
        return tuple(
            MappingProxyType({identity: tuple(fields) for identity, fields in group.items()})
            for group in groups.values()
            if len(group) > 1
        )
