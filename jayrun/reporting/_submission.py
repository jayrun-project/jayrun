"""Detached descriptions of native submission inputs and settings."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ..authority import Controller, Supervisor
from ..core.graph.compiled_graph import CompiledOperatorStep
from ..core.graph.declaration_report import MAX_BYTES, _SENSITIVE, _config_value
from ..engine.settings.combined_context import CombinedContextSettings
from ..engine.settings.context import ArtifactPolicy, ContextSettings
from ..engine.settings.engine import EngineSettings, RetryPolicy
from ..visualization.contract import summarize

if TYPE_CHECKING:
    from ..core.artifact.base import Artifact
    from ..core.graph.graph_definition import GraphDefinition
    from ..submission import Submission


def _qualified(cls: type) -> str:
    module = type.__getattribute__(cls, "__module__")
    name = type.__getattribute__(cls, "__qualname__")
    return f"{module}.{name}" if type(module) is str and type(name) is str else "unknown type"


def _retry(policy: RetryPolicy) -> dict[str, object]:
    return {"max_attempts": policy.max_attempts,
            "retry_on": tuple(_qualified(cls) for cls in policy.retry_on)}


def _settings_report(
    settings: ContextSettings | CombinedContextSettings, graph: GraphDefinition,
    *, artifact_policy: ArtifactPolicy | None = None,
) -> dict[str, object]:
    registry = graph._specification.artifacts
    policy = settings.artifact_policy if artifact_policy is None else artifact_policy
    retained = policy.retained_artifacts
    ids = None if retained is None else tuple(
        registry.definition_for(registry.resolve(reference)).artifact_id for reference in retained
    )
    record = settings.record_policy
    result: dict[str, object] = {
        "artifact_policy": {"retained_artifacts": ids, "release_entry_artifacts": policy.release_entry_artifacts},
        "max_iterations": settings.max_iterations,
        "max_repeats": settings.max_repeats,
        "execution_history_limit": settings.execution_history_limit,
        "record_policy": {
            "history_per_key": record.history_per_key,
            "max_keys": record.max_keys,
            "max_value_bytes": record.max_value_bytes,
            "max_total_bytes": record.max_total_bytes,
        },
    }
    result["retry_policy"] = None if settings.retry_policy is None else _retry(settings.retry_policy)
    if isinstance(settings, CombinedContextSettings):
        result["recording_mode"] = settings.recording_mode.value
        result["failure_mode"] = settings.failure_mode.value
    return result


def _redact_path(value: object, path: tuple[str | int, ...]) -> object:
    """Apply one validated path to detached report containers."""
    if not path:
        return {"redacted": True}
    key, rest = path[0], path[1:]
    if isinstance(value, dict) and key in value:
        value[key] = _redact_path(value[key], rest)
    elif isinstance(value, (tuple, list)) and type(key) is int and 0 <= key < len(value):
        if isinstance(value, tuple):
            value = list(value)
        value[key] = _redact_path(value[key], rest)
    return value


def _exact_policy_integers(policy: dict) -> None:
    """Keep large policy counters exact in JSON without decimal conversion."""
    for key, value in policy.items():
        if isinstance(value, dict):
            _exact_policy_integers(value)
        elif isinstance(value, int) and int.bit_length(value) > 53:
            if int.bit_length(value) > 4 * MAX_BYTES:
                raise ValueError("submission inspection exceeds 32 MiB")
            policy[key] = {"int": hex(value)}


def _checked_size(value: object, used: int = 0) -> int:
    """Bound cumulative JSON bytes without materializing the complete encoding."""
    encoder = json.JSONEncoder(ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    for chunk in encoder.iterencode(value):
        used += len(chunk)
        if used > MAX_BYTES:
            raise ValueError("submission inspection exceeds 32 MiB")
    return used


def _config_rows(submission: Submission, hidden: frozenset[tuple[str | int, ...]]) -> list:
    registry = submission._graph._specification.configs
    rows = []
    paths_by_id = {}
    for path in sorted(hidden, key=len, reverse=True):
        if len(path) > 2 and path[0] == "configs" and type(path[1]) is int:
            paths_by_id.setdefault(path[1], []).append(path[2:])
    size = 0
    for field, definition in zip(registry.sources, registry.definitions, strict=True):
        key = definition.config_id
        if ("configs", key) in hidden:
            rows.append({"redacted": True})
            continue
        row = {"id": key, "field": definition.attribute_name, "name": summarize(definition.name),
               "owner": summarize(definition.owner), "position": list(definition.layout_position),
               "type": definition.value_type.__name__, "required": definition.required}
        data = submission._effective.get(field)
        row["origin"] = ("explicit" if field in submission._supplied else
                         "default" if data is not None else "omitted")
        if data is not None:
            sensitive = _SENSITIVE.search(definition.attribute_name) or _SENSITIVE.search(definition.name or "")
            if sensitive or ("configs", key, "value") in hidden:
                row["value"] = {"redacted": True}
            else:
                row["value"] = _config_value(data.value)
        for path in paths_by_id.get(key, ()):
            _redact_path(row, path)
        rows.append(row)
        size = _checked_size(row, size)
    return rows


def _resources(graph: GraphDefinition) -> list:
    bound = graph.inspect.resources.bindings
    registry = graph._specification.configs
    selections = {}
    rows = []
    for field in graph.inspect.resources:
        resource = bound.get(field)
        row = {"id": field.resource_id, "field": field.attribute_name,
               "position": list(field.layout_position), "required": field.required,
               "parallel_safe": field.parallel_safe, "selection": None}
        if resource is not None:
            row["selection"] = selections.setdefault(id(resource), field.resource_id)
            row["type"] = _qualified(type(resource))
            row["requirements"] = list(resource.requirements)
            row["config_ids"] = [registry.definition_for(f).config_id for f in resource.config_fields]
        rows.append(row)
    return rows


def _inspect_submission(submission: Submission, engine_settings: EngineSettings | None,
                       redact: tuple[tuple[str | int, ...], ...]) -> dict[str, object]:
    graph = submission._graph
    spec = graph._specification
    scenario = None
    if engine_settings is not None:
        combined = CombinedContextSettings.from_settings(engine_settings, submission._settings, spec.artifacts)
        scenario = _settings_report(combined, graph)

    hidden = frozenset()
    if type(redact) is not tuple or redact:
        from ..persistence.values import ValueLimits, _redactions
        hidden = _redactions(redact, ValueLimits())
    if () in hidden:
        return {"redacted": True}

    def artifact_id(artifact: Artifact) -> int:
        return spec.artifacts.definition_for(artifact).artifact_id

    authority = submission._authority
    requested_authority = None
    if isinstance(authority, Controller):
        requested_authority = {"kind": "controller", "history_requested": authority.history is not None}
    elif isinstance(authority, Supervisor):
        requested_authority = {"kind": "supervisor", "graphs": [g.graph_id for g in authority.graphs] or None}

    diagnostics = graph.validate()
    timing = graph._timing_config_fields
    serializers = graph.inspect.serializers
    selections = {}
    bindings = []
    for codec in serializers:
        source = spec.artifacts.resolve(codec.artifact_id)
        selection = selections.setdefault(id(graph._serializer_bindings[source]), codec.artifact_id)
        bindings.append({"artifact_id": codec.artifact_id, "selection": selection,
                         "name": summarize(codec.name), "type": codec.serializer_type,
                         "requirements": [str(r) for r in codec.requirements]})

    requested = submission._settings
    graph_settings = _settings_report(
        submission._context_settings, graph, artifact_policy=submission._retention,
    )
    report = {
        "schema": "jayrun.submission-inspection/1",
        "graph": {"graph_id": graph.graph_id, "version": graph.version,
                  "name": summarize(graph.name), "confirmed": graph.confirmed},
        "entries": [{"id": artifact_id(a), "name": summarize(a.name), "supplied": True,
                     "missing_value": data.value is None} for a, data in submission._entries.items()],
        "configs": [] if ("configs",) in hidden else _config_rows(submission, hidden),
        "resources": _resources(graph),
        "serializers": {"enabled": serializers.enabled, "complete": serializers.complete,
                        "bindings": bindings, "unbound_ids": [a.artifact_id for a in serializers.unbound]},
        "requested_settings": None if requested is None else _settings_report(requested, graph),
        "graph_settings": graph_settings, "engine_scenario": scenario,
        "timing_config_ids": None if timing is None else [spec.configs.definition_for(f).config_id for f in timing],
        "requested_authority": requested_authority,
        "diagnostics": {
            "valid": diagnostics.valid,
            "edges": [{"id": e.edge_id, "artifact_id": artifact_id(e.artifact),
                       "status": e.status.value if e.status is not None else None} for e in diagnostics.edges],
            "next_iteration_mismatches": [artifact_id(a) for a in diagnostics.feedback_mismatches],
            "operator_repeat_mismatches": [
                {"position": list(step.layout_position), "artifact_ids": [artifact_id(a) for a in step.repeat_mismatches]}
                for step in graph._compiled_graph.steps if isinstance(step, CompiledOperatorStep) and step.repeat_mismatches],
        },
        "at_admission_or_execution": ["registry membership", "effective engine settings", "live authority",
                                      "history capture", "timing history", "routing and capacity",
                                      "placement", "resource acquisition", "serializer execution"],
    }
    for path in sorted(hidden, key=len, reverse=True):
        if path[0] != "configs" or len(path) == 1:
            _redact_path(report, path)
    for key in ("requested_settings", "graph_settings", "engine_scenario"):
        policy = report[key]
        if isinstance(policy, dict):
            _exact_policy_integers(policy)
    _checked_size(report)
    return report
