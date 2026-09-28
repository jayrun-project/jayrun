from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..persistence import DatabaseReader

from ..authority import Controller, Supervisor
from ..core.artifact.base import Artifact
from ..core.artifact.context import ArtifactContext
from ..core.config.context import ConfigContext
from ..core.config.field import ConfigField
from ..core.context.runtime_data import Data
from ..core.graph.definition.artifact import ArtifactDefinition, ArtifactRole
from ..core.graph.definition.field import ConfigDefinition
from ..core.graph.graph_definition import GraphDefinition
from ..core.graph.graph_registry import GraphRegistry
from ..core.graph.inspection.registry import GraphIdentity
from ..core.graph.registry.artifact import ArtifactRegistry
from ..core.graph.registry.config import ConfigRegistry

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
    if artifacts is None:
        artifacts = ArtifactContext()
    elif not isinstance(artifacts, ArtifactContext):
        raise TypeError("artifacts must be an ArtifactContext instance or None")
    if configs is None:
        configs = ConfigContext()
    elif not isinstance(configs, ConfigContext):
        raise TypeError("configs must be a ConfigContext instance or None")
    if artifacts._is_sealed:
        raise RuntimeError("artifacts must be a mutable builder context")
    if configs._is_sealed:
        raise RuntimeError("configs must be a mutable builder context")
    if not graph.confirmed:
        raise RuntimeError("The graph must be confirmed before submission.")
    graph._compiled_graph
    artifact_registry = graph._specification.artifacts
    config_registry = graph._specification.configs
    normalized_artifacts = _normalize_artifacts(artifacts, artifact_registry)
    normalized_configs = _normalize_configs(configs, config_registry)

    return _NormalizedSubmission(
        graph=graph,
        graph_scope=graph_scope,
        artifacts=ArtifactContext._from_normalized(
            artifacts,
            artifact_registry,
            normalized_artifacts,
        ),
        configs=ConfigContext._from_normalized(
            configs,
            config_registry,
            normalized_configs,
        ),
    )


def _normalize_artifacts(
    context: ArtifactContext,
    registry: ArtifactRegistry,
) -> dict[Artifact, Data[object]]:
    resolved: dict[Artifact, Data[object]] = {}

    for reference, data in context.instances.items():
        artifact = _resolve_artifact(reference, registry)
        if not isinstance(data, Data):
            raise TypeError("artifact context values must be Data instances")
        resolved[artifact] = data

    missing = tuple(
        registry.source_for(definition)
        for definition in registry.definitions
        if definition.role is ArtifactRole.ENTRY
        and registry.source_for(definition) not in resolved
    )
    if missing:
        raise ValueError(f"Required entry artifacts are missing: {missing!r}.")

    return {
        artifact: resolved[artifact]
        for artifact in registry.sources
        if artifact in resolved
    }


def _normalize_configs(
    context: ConfigContext,
    registry: ConfigRegistry,
) -> dict[ConfigField, Data[object]]:
    resolved: dict[ConfigField, Data[object]] = {}

    for reference, data in context.instances.items():
        field = _resolve_config(reference, registry)
        if not isinstance(data, Data):
            raise TypeError("config context values must be Data instances")
        resolved[field] = data

    for field, data in resolved.items():
        ConfigContext._validate_value(field, data.value)

    for field in registry.sources:
        if field in resolved:
            continue
        if field.default is not None:
            ConfigContext._validate_value(field, field.default)
            resolved[field] = Data(value=field.default)

    missing = tuple(
        field
        for field in registry.sources
        if field.required and field not in resolved
    )
    if missing:
        raise ValueError(f"Required configs are missing: {missing!r}.")

    return {
        field: resolved[field]
        for field in registry.sources
        if field in resolved
    }


def _resolve_artifact(
    reference: object,
    registry: ArtifactRegistry,
) -> Artifact:
    if isinstance(reference, Artifact):
        if reference not in registry.sources:
            raise KeyError("The Artifact does not belong to the submitted graph.")
        return reference

    if type(reference) is int:
        for definition in registry.definitions:
            if definition.artifact_id == reference:
                return registry.source_for(definition)
        raise KeyError(f"Unknown artifact ID: {reference!r}.")

    if isinstance(reference, ArtifactDefinition):
        for definition in registry.definitions:
            if definition is reference:
                return registry.source_for(definition)
        raise KeyError(
            "The ArtifactDefinition does not belong to the submitted graph."
        )

    raise TypeError(
        "Artifact context references must be int, Artifact, or ArtifactDefinition"
    )


def _resolve_config(
    reference: object,
    registry: ConfigRegistry,
) -> ConfigField:
    if isinstance(reference, ConfigField):
        if reference not in registry.sources:
            raise KeyError("The ConfigField does not belong to the submitted graph.")
        return reference

    if type(reference) is int:
        for definition in registry.definitions:
            if definition.config_id == reference:
                return registry.source_for(definition)
        raise KeyError(f"Unknown config ID: {reference!r}.")

    if isinstance(reference, ConfigDefinition):
        for definition in registry.definitions:
            if definition is reference:
                return registry.source_for(definition)
        raise KeyError(
            "The ConfigDefinition does not belong to the submitted graph."
        )

    raise TypeError(
        "Config context references must be int, ConfigField, or ConfigDefinition"
    )


def _normalize_authority(
    authority: Supervisor | Controller | None,
    graph_registry: GraphRegistry | None = None,
) -> _NormalizedAuthority:
    if authority is None:
        return _NormalizedAuthority(supervises=(), controller=False)
    if isinstance(authority, Controller):
        if authority.history is not None:
            authority.history._check_access()
        return _NormalizedAuthority(supervises=None, controller=True, history=authority.history)
    if not isinstance(authority, Supervisor):
        raise TypeError("authority must be a Supervisor, Controller, or None")

    graphs = authority.graphs
    if not graphs:
        return _NormalizedAuthority(supervises=None, controller=False)
    if any(not isinstance(graph, GraphDefinition) for graph in graphs):
        raise TypeError("Supervisor must contain only GraphDefinition instances")
    if len({id(graph) for graph in graphs}) != len(graphs):
        raise ValueError("Supervisor cannot contain duplicate graph instances")
    if any(not graph.confirmed for graph in graphs):
        raise RuntimeError("every supervised graph must be confirmed")
    if graph_registry is None:
        supervises: _SupervisionScope = graphs
    else:
        supervises = tuple(graph_registry.identity_for(graph) for graph in graphs)
    return _NormalizedAuthority(supervises=supervises, controller=False)
