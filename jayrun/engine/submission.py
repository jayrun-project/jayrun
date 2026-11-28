from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..persistence import DatabaseReader

from ..authority import Controller, Supervisor
from ..core.artifact.context import ArtifactContext
from ..core.config.context import ConfigContext
from ..core.graph.graph_definition import GraphDefinition
from ..core.graph.graph_registry import GraphRegistry
from ..core.graph.inspection.registry import GraphIdentity
from ..submission import _resolve_bindings, _validate_authority_request

_GraphScope = GraphDefinition | GraphIdentity
_SupervisionScope = tuple[_GraphScope, ...] | None


@dataclass(frozen=True, slots=True)
class _NormalizedSubmission:
    graph: GraphDefinition
    graph_scope: _GraphScope
    artifacts: ArtifactContext
    configs: ConfigContext


@dataclass(frozen=True, slots=True)
class _NormalizedAuthority:
    supervises: _SupervisionScope
    controller: bool
    history: DatabaseReader | None = None


def _normalize_submission(
    graph: GraphDefinition | GraphIdentity,
    artifacts: ArtifactContext | None = None,
    configs: ConfigContext | None = None,
    graph_registry: GraphRegistry | None = None,
) -> _NormalizedSubmission:
    graph_scope: _GraphScope
    if isinstance(graph, tuple):
        if graph_registry is None:
            raise RuntimeError("a graph key requires an engine graph registry")
        if len(graph) != 2 or not all(isinstance(value, str) for value in graph):
            raise TypeError("graph key must be a (key, version) tuple")
        graph_scope = graph
        graph = graph_registry[graph]
    elif isinstance(graph, GraphDefinition):
        graph_scope = graph
        if graph_registry is not None:
            graph_scope = graph_registry.identity_for(graph)
    else:
        raise TypeError(
            "graph must be a GraphDefinition or (key, version) tuple"
        )
    artifacts = ArtifactContext() if artifacts is None else artifacts
    configs = ConfigContext() if configs is None else configs
    entries, _, effective = _resolve_bindings(graph, artifacts, configs)
    return _NormalizedSubmission(
        graph=graph,
        graph_scope=graph_scope,
        artifacts=ArtifactContext._from_normalized(
            artifacts,
            graph._specification.artifacts,
            entries,
        ),
        configs=ConfigContext._from_normalized(
            configs,
            graph._specification.configs,
            effective,
        ),
    )


def _normalize_authority(
    authority: Supervisor | Controller | None,
    graph_registry: GraphRegistry | None = None,
) -> _NormalizedAuthority:
    _validate_authority_request(authority)
    if authority is None:
        return _NormalizedAuthority(supervises=(), controller=False)
    if isinstance(authority, Controller):
        if authority.history is not None:
            authority.history._check_access()
        return _NormalizedAuthority(supervises=None, controller=True, history=authority.history)

    graphs = authority.graphs
    if not graphs:
        return _NormalizedAuthority(supervises=None, controller=False)
    if graph_registry is None:
        supervises: _SupervisionScope = graphs
    else:
        supervises = tuple(graph_registry.identity_for(graph) for graph in graphs)
    return _NormalizedAuthority(supervises=supervises, controller=False)
