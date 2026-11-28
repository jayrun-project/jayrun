"""Reusable, engine-independent input bindings for a fresh graph submission."""
from __future__ import annotations

from typing import TypedDict

from .authority import Controller, Supervisor
from .core.artifact.base import Artifact
from .core.artifact.context import ArtifactContext
from .core.config.context import ConfigContext
from .core.config.field import ConfigField
from .core.context.runtime_data import Data
from .core.graph.definition.artifact import ArtifactRole
from .core.graph.graph_definition import GraphDefinition
from .core.graph.registry.artifact import ArtifactRegistry
from .core.graph.registry.config import ConfigRegistry
from .engine.settings.combined_context import CombinedContextSettings
from .settings import ContextSettings, EngineSettings


class _Arguments(TypedDict):
    graph: GraphDefinition
    artifacts: ArtifactContext
    configs: ConfigContext
    settings: ContextSettings | None
    authority: Supervisor | Controller | None


class Submission:
    """Resolve and retain inputs for repeated submission of a confirmed graph.

    Artifact payloads are shared by reference. Subsequent builder edits affect
    only new preparations. Keep mutable payloads stable while runs read them.

    Args:
        graph: Confirmed graph declaration.
        artifacts: Native entry-artifact builder.
        configs: Native configuration overrides.
        settings: Requested per-context settings.
        authority: Requested authority, checked by the admitting runtime.
    """

    def __init__(
        self, graph: GraphDefinition, artifacts: ArtifactContext | None = None,
        configs: ConfigContext | None = None, *, settings: ContextSettings | None = None,
        authority: Supervisor | Controller | None = None,
    ) -> None:
        if not isinstance(graph, GraphDefinition):
            raise TypeError("graph must be a GraphDefinition")
        _validate_authority_request(authority)
        artifacts = ArtifactContext() if artifacts is None else artifacts
        configs = ConfigContext() if configs is None else configs
        entries, supplied, effective = _resolve_bindings(graph, artifacts, configs)
        if settings is not None and not isinstance(settings, ContextSettings):
            raise TypeError("context_settings must be a ContextSettings instance or None")
        self._context_settings = ContextSettings() if settings is None else settings
        self._retention = CombinedContextSettings._normalize_artifact_policy(
            self._context_settings.artifact_policy, graph._specification.artifacts,
        )
        self._graph = graph
        self._entries = entries
        self._effective = effective
        self._supplied = {field: data for field, data in effective.items() if field in supplied}
        self._artifact_metadata = (artifacts.name, artifacts.description)
        self._config_metadata = (configs.name, configs.description)
        self._settings = settings
        self._authority = authority

    def arguments(self) -> _Arguments:
        """Return fresh editable native keyword arguments for one submission.

        Successful registration can clear the returned artifact builder. Call
        this method separately for each attempt, including concurrent calls.
        """
        name, description = self._artifact_metadata
        artifacts = ArtifactContext(name=name, description=description)
        artifacts._update_instances(self._entries)
        name, description = self._config_metadata
        configs = ConfigContext(name=name, description=description)
        configs._update_instances(self._supplied)
        return {"graph": self._graph, "artifacts": artifacts, "configs": configs,
                "settings": self._settings, "authority": self._authority}

    def inspect(
        self, *, engine_settings: EngineSettings | None = None,
        redact: tuple[tuple[str | int, ...], ...] = (),
    ) -> dict[str, object]:
        """Describe graph-relative bindings and optionally project engine settings.

        The detached report omits artifact payloads. Redaction paths select
        report keys and sequence indices. An empty path redacts the whole report.
        """
        from .reporting._submission import _inspect_submission

        return _inspect_submission(self, engine_settings, redact)


def _resolve_bindings(
    graph: GraphDefinition, artifacts: ArtifactContext, configs: ConfigContext,
) -> tuple[dict[Artifact, Data[object]], dict[ConfigField, Data[object]], dict[ConfigField, Data[object]]]:
    if not isinstance(artifacts, ArtifactContext):
        raise TypeError("artifacts must be an ArtifactContext instance or None")
    if not isinstance(configs, ConfigContext):
        raise TypeError("configs must be a ConfigContext instance or None")
    if artifacts._is_sealed:
        raise RuntimeError("artifacts must be a mutable builder context")
    if configs._is_sealed:
        raise RuntimeError("configs must be a mutable builder context")
    if not graph.confirmed:
        raise RuntimeError("The graph must be confirmed before submission.")
    graph._compiled_graph
    entries = _normalize_artifacts(artifacts, graph._specification.artifacts)
    supplied, effective = _normalize_configs(configs, graph._specification.configs)
    return entries, supplied, effective


def _normalize_artifacts(
    context: ArtifactContext,
    registry: ArtifactRegistry,
) -> dict[Artifact, Data[object]]:
    resolved: dict[Artifact, Data[object]] = {}

    for reference, data in context.instances.items():
        artifact = registry.resolve(reference)
        if registry.definition_for(artifact).role is not ArtifactRole.ENTRY:
            raise ValueError(f"Only entry artifacts may be supplied: {artifact!r}.")
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
) -> tuple[dict[ConfigField, Data[object]], dict[ConfigField, Data[object]]]:
    resolved: dict[ConfigField, Data[object]] = {}

    for reference, data in context.instances.items():
        field = ConfigContext._resolve_with_registry(reference, registry)
        if not isinstance(data, Data):
            raise TypeError("config context values must be Data instances")
        resolved[field] = data

    for field, data in resolved.items():
        ConfigContext._validate_value(field, data.value)

    effective = {}
    missing = []
    for field in registry.sources:
        if field in resolved:
            effective[field] = resolved[field]
        elif field.default is not None:
            ConfigContext._validate_value(field, field.default)
            effective[field] = Data(value=field.default)
        elif field.required:
            missing.append(field)
    if missing:
        raise ValueError(f"Required configs are missing: {tuple(missing)!r}.")
    return resolved, effective


def _validate_authority_request(authority: Supervisor | Controller | None) -> None:
    if authority is None or isinstance(authority, Controller):
        return
    if not isinstance(authority, Supervisor):
        raise TypeError("authority must be a Supervisor, Controller, or None")
    graphs = authority.graphs
    if any(not isinstance(graph, GraphDefinition) for graph in graphs):
        raise TypeError("Supervisor must contain only GraphDefinition instances")
    if len({id(graph) for graph in graphs}) != len(graphs):
        raise ValueError("Supervisor cannot contain duplicate graph instances")
    if any(not graph.confirmed for graph in graphs):
        raise RuntimeError("every supervised graph must be confirmed")
