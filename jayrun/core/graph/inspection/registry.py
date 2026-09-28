from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from itertools import combinations
from types import MappingProxyType
from typing import TYPE_CHECKING, TypeAlias

from ..definition import RequirementDefinition
from ..graph_definition import GraphDefinition
from ..requirements import (
    RequirementConflictError,
    merge_requirements,
    requirement_key,
)
from .graph import GraphInspection
from .resource import RegistryResourceInspection
from .serializer import SerializerInspection

if TYPE_CHECKING:
    from ..graph_registry import GraphRegistry


GraphIdentity: TypeAlias = tuple[str, str]


@dataclass(frozen=True, slots=True)
class GraphRequirements:
    """Complete package requirements for one registered graph."""

    identity: GraphIdentity
    requirements: tuple[RequirementDefinition, ...]


@dataclass(frozen=True, slots=True)
class RequirementConflict:
    """Incompatible constraints shared by two registered graphs."""

    name: str
    marker: str | None
    left: RequirementDefinition
    right: RequirementDefinition


@dataclass(frozen=True, slots=True)
class GraphRequirementComparison:
    """Pairwise package-requirement comparison for two registered graphs."""

    left: GraphIdentity
    right: GraphIdentity
    matches: tuple[RequirementDefinition, ...]
    conflicts: tuple[RequirementConflict, ...]

    @property
    def compatible(self) -> bool:
        """Whether the two graphs have no contradictory package constraints."""
        return not self.conflicts


class GraphRegistryInspection:
    """Inspect graph bindings and requirements across a live registry."""

    def __init__(self, registry: GraphRegistry) -> None:
        self._registry = registry
        self._resources = RegistryResourceInspection(registry)

    @property
    def graphs(self) -> Mapping[GraphIdentity, GraphInspection]:
        """Read-only graph inspection lookup in registration order."""
        return MappingProxyType({
            identity: graph.inspect for identity, graph in self._registry._entries()
        })

    @property
    def resources(self) -> RegistryResourceInspection:
        """Resource bindings, unbound fields, and sharing across graphs."""
        return self._resources

    @property
    def serializers(self) -> Mapping[GraphIdentity, SerializerInspection]:
        """Serializer declarations and boundary coverage grouped by graph."""
        return MappingProxyType({
            identity: graph.serializers for identity, graph in self.graphs.items()
        })

    @property
    def requirements(self) -> tuple[GraphRequirements, ...]:
        """Complete requirements grouped by registered graph identity."""
        return tuple(
            GraphRequirements(
                identity=identity,
                requirements=graph.inspect.requirements.all,
            )
            for identity, graph in self._registry._entries()
        )

    @property
    def comparisons(self) -> tuple[GraphRequirementComparison, ...]:
        """Pairwise requirement comparisons in registration order."""
        return tuple(
            self.compare(left_graph, right_graph)
            for (_, left_graph), (_, right_graph) in combinations(
                self._registry._entries(),
                2,
            )
        )

    @property
    def matches(self) -> tuple[GraphRequirementComparison, ...]:
        """Compatible graph pairs sharing at least one package requirement."""
        return tuple(
            comparison
            for comparison in self.comparisons
            if comparison.compatible and comparison.matches
        )

    @property
    def conflicts(self) -> tuple[GraphRequirementComparison, ...]:
        """Graph pairs containing contradictory package requirements."""
        return tuple(
            comparison for comparison in self.comparisons if comparison.conflicts
        )

    def compare(
        self,
        left: GraphDefinition,
        right: GraphDefinition,
    ) -> GraphRequirementComparison:
        """Compare shared package constraints for two registered graphs."""
        left_identity = self._registry.identity_for(left)
        right_identity = self._registry.identity_for(right)
        left_requirements = {
            requirement_key(str(requirement)): requirement
            for requirement in left.inspect.requirements.all
        }
        right_requirements = {
            requirement_key(str(requirement)): requirement
            for requirement in right.inspect.requirements.all
        }
        matches: list[RequirementDefinition] = []
        conflicts: list[RequirementConflict] = []

        for key in left_requirements:
            if key not in right_requirements:
                continue
            left_requirement = left_requirements[key]
            right_requirement = right_requirements[key]
            try:
                merged = merge_requirements(
                    (str(left_requirement), str(right_requirement))
                )
            except RequirementConflictError:
                conflicts.append(
                    RequirementConflict(
                        name=key[0],
                        marker=key[1],
                        left=left_requirement,
                        right=right_requirement,
                    )
                )
            else:
                matches.extend(merged)

        return GraphRequirementComparison(
            left=left_identity,
            right=right_identity,
            matches=tuple(matches),
            conflicts=tuple(conflicts),
        )

    def requirements_for(
        self,
        *graphs: GraphDefinition,
    ) -> tuple[RequirementDefinition, ...]:
        """Merge requirements for selected graphs, or every graph when omitted.

        Raises:
            KeyError: If a selected graph does not belong to this registry.
            ValueError: If graph requirements contradict each other.
        """
        selected = graphs or self._registry.graphs
        for graph in selected:
            self._registry.identity_for(graph)
        return merge_requirements(
            str(requirement)
            for graph in selected
            for requirement in graph.inspect.requirements.all
        )
