"""Bounded exact timing keys; no storage, application codecs or executable hashing.

ConfigContext has already resolved defaults. Only exact immutable builtin values
are grouped. Unsupported values make history unavailable, never a shared marker.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import platform
import sys
from typing import TYPE_CHECKING

from .. import __version__
from ..core.graph.compiled_graph import CompiledOperatorStep, CompiledResourceStep

if TYPE_CHECKING:
    from ..core.graph.graph_definition import GraphDefinition
    from .settings.combined_context import CombinedContextSettings
    from .settings.engine import EngineSettings
    from .submission import _NormalizedSubmission


_CONFIG_PREFIX = "jtc1:"
_COMPATIBILITY_PREFIX = "jtp1:"
_MAX_KEY_BYTES = 65_536
_MAX_NODES = 4096
_MAX_DEPTH = 16


@dataclass(frozen=True, slots=True)
class _TimingKey:
    graph_id: str
    graph_version: str
    configuration_key: str
    compatibility_key: str
    step_count: int

    @property
    def charge(self) -> int:
        # Conservative charged numeric-buffer envelope, not a Python RSS promise.
        return 2048 + 6 * len(self.graph_version) + 256 * self.step_count


class _Unmatchable(ValueError):
    pass


class _ExactValues:
    """Small exact encoding for hashable configuration values, not diagnostics."""

    def __init__(self) -> None:
        self.nodes = 0
        self.bytes = 0

    def encode(self, value: object, depth: int = 0) -> object:
        self.nodes += 1
        self.bytes += 16
        if self.nodes > _MAX_NODES or depth > _MAX_DEPTH or self.bytes > _MAX_KEY_BYTES:
            raise _Unmatchable("timing configuration exceeds exact key bounds")
        kind = type(value)
        if value is None:
            return ["null"]
        if kind is bool:
            return ["bool", value]
        if kind is int:
            if value.bit_length() > 4096:
                raise _Unmatchable("timing integer exceeds exact key bounds")
            token = str(value)
            self.bytes += len(token)
            return ["int", token]
        if kind is float:
            if not math.isfinite(value):
                raise _Unmatchable("nonfinite timing configuration")
            return ["float", value.hex()]
        if kind is str:
            if len(value) > 16_384:
                raise _Unmatchable("timing string exceeds exact key bounds")
            self.bytes += 6 * len(value)
            return ["str", value]
        if kind is bytes:
            if len(value) > 16_384:
                raise _Unmatchable("timing bytes exceed exact key bounds")
            self.bytes += 2 * len(value)
            return ["bytes", value.hex()]
        if kind in (tuple, frozenset):
            if len(value) > _MAX_NODES:
                raise _Unmatchable("timing collection exceeds exact key bounds")
            children = [self.encode(child, depth + 1) for child in value]
            if kind is frozenset:
                children.sort(key=_json)
            return ["tuple" if kind is tuple else "frozenset", children]
        raise _Unmatchable("unsupported timing configuration type")


def _json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def _digest(value: object) -> str:
    # Bound descriptors before json allocates their encoded representation.
    remaining = _MAX_KEY_BYTES
    nodes = 0
    def check(item: object, depth: int = 0) -> None:
        nonlocal remaining, nodes
        nodes += 1
        remaining -= 8
        if nodes > 16_384 or remaining < 0 or depth > 32:
            raise _Unmatchable("timing descriptor exceeds exact key bounds")
        if type(item) is str:
            remaining -= 6 * len(item)
        elif type(item) in (tuple, list):
            if len(item) > 4096:
                raise _Unmatchable("timing descriptor collection is oversized")
            for child in item:
                check(child, depth + 1)
        elif item is not None and type(item) not in (int, float, bool):
            raise _Unmatchable("unknown timing descriptor type")
        elif type(item) is int and item.bit_length() > 4096:
            raise _Unmatchable("timing descriptor integer is oversized")
        if remaining < 0:
            raise _Unmatchable("timing descriptor exceeds exact key bounds")
    check(value)
    encoded = _json(value)
    if len(encoded) > _MAX_KEY_BYTES:
        raise _Unmatchable("timing descriptor exceeds exact key bounds")
    return hashlib.sha256(encoded).hexdigest()


def _qualified(cls: type) -> str:
    module = type.__getattribute__(cls, "__module__")
    name = type.__getattribute__(cls, "__qualname__")
    if (type(module) is not str or type(name) is not str
            or len(module) + len(name) > 4096):
        raise _Unmatchable("unsupported qualified timing descriptor")
    return module + "." + name


def _environment(settings: EngineSettings) -> tuple[object, ...]:
    """Supported execution descriptors, not physical-hardware discovery."""
    return (__version__, sys.implementation.name, sys.version_info[:2], platform.system(),
            platform.machine(), settings.max_workers, settings.max_tasks,
            tuple((d.device.value, tuple(b.value for b in d.backends), d.device_id,
                   d.memory_limit_gb, d.exclusive_only) for d in settings.runtime_devices))


def _ordered_plan(graph: GraphDefinition) -> tuple[str, tuple[int, ...]]:
    plan = graph._compiled_graph
    registry = graph._specification.configs
    if (len(registry.sources) > _MAX_NODES or len(plan.steps) > _MAX_NODES
            or len(graph._artifacts) > _MAX_NODES or len(plan.serializers) > _MAX_NODES):
        raise _Unmatchable("timing plan exceeds exact descriptor bounds")
    # Bound the total relation population before building descriptor rows. A
    # single wide operator must not bypass the step-count bound.
    relations = 0
    for step in plan.steps:
        relations += (len(step.group_indices) + len(step.successor_indices)
                      + len(step.output_mask) + len(step.requirements) + len(step.config_fields))
        if isinstance(step, CompiledOperatorStep):
            relations += len(step.bound_artifact_fields) + len(step.output_fields) + len(step.bound_resources)
        if relations > 16_384:
            raise _Unmatchable("timing plan relation population exceeds bounds")
    config_ids = {id(field): registry.definition_for(field).config_id for field in registry.sources}
    artifact_ids = {id(field): definition.artifact_id for field, definition in graph._artifacts.items()}
    selected = graph._timing_config_fields
    selected_ids = tuple(config_ids[id(field)] for field in registry.sources
                         if selected is None or field in selected)
    if len(selected_ids) > _MAX_NODES or len(plan.steps) > _MAX_NODES:
        raise _Unmatchable("timing plan exceeds exact descriptor bounds")
    resources: dict[int, int] = {}
    rows = []
    for step in plan.steps:
        common = (step.execution_mode.value, step.layout_position, step.group_indices,
                  tuple(sorted(step.successor_indices)), step.initial_dependency_count,
                  step.output_mask, tuple(str(r) for r in step.requirements),
                  tuple((field.attribute_name, config_ids[id(field)]) for field in step.config_fields))
        if isinstance(step, CompiledResourceStep):
            identity = resources.setdefault(id(step.resource), len(resources))
            row = ("resource", identity, _qualified(type(step.resource)),
                   step.resource_field.attribute_name, step.resource_field.parallel_safe, common)
        elif isinstance(step, CompiledOperatorStep):
            inputs = tuple((f.attribute_name, artifact_ids.get(id(f.artifact))) for f in step.bound_artifact_fields)
            outputs = tuple(artifact_ids.get(id(f.artifact)) for f in step.output_fields)
            bindings = tuple((f.attribute_name, resources.setdefault(id(r), len(resources)),
                              _qualified(type(r)), f.parallel_safe) for f, r in step.bound_resources)
            row = ("operator", inputs, outputs, bindings, common)
        else:
            raise _Unmatchable("unknown compiled step kind")
        rows.append(row)
    fields = tuple((d.config_id, d.layout_position, d.attribute_name, _qualified(d.value_type), d.required)
                   for d in registry.definitions)
    serializers = tuple((artifact_ids[id(artifact)], _qualified(type(serializer)))
                        for artifact, serializer in plan.serializers)
    return _digest(("ordered-timing-plan-1", rows, fields, serializers)), selected_ids


def _key(submission: _NormalizedSubmission, settings: CombinedContextSettings,
         environment: tuple[object, ...], plan: tuple[str, tuple[int, ...]],
         redactions: tuple[tuple[str | int, ...], ...] = ()) -> _TimingKey:
    graph = submission.graph
    signature, selected = plan
    # A redacted selected field (including a nested value) never becomes a hash
    # of a secret. Explicitly excluding that field remains the author's option.
    for path in redactions:
        if not path or (path[0] == "configurations" and (len(path) == 1 or path[1] in selected)):
            raise _Unmatchable("selected timing configuration is redacted")
    registry = graph._specification.configs
    by_id = {registry.definition_for(field).config_id: field for field in registry.sources}
    encoder = _ExactValues()
    values = []
    for config_id in selected:
        data = submission.configs.instances.get(by_id[config_id])
        values.append((config_id, ["missing"] if data is None else encoder.encode(data.value)))
    configuration_key = _CONFIG_PREFIX + _digest(("selected-resolved-configs-1", selected, values))
    execution = ({"standard": "production", "diagnostic": "debug", "minimal": "performance"}[settings.recording_mode.value], settings.failure_mode.value,
                 settings.max_iterations, settings.max_repeats, settings.retry_policy.max_attempts,
                 tuple(_qualified(cls) for cls in settings.retry_policy.retry_on),
                 settings.record_history_limit, settings.record_max_keys, settings.record_max_value_bytes,
                 settings.record_max_total_bytes, settings.artifact_policy.release_entry_artifacts,
                 tuple(graph._specification.artifacts.definition_for(a).artifact_id
                       for a in settings.artifact_policy.retained_artifacts))
    compatibility_key = _COMPATIBILITY_PREFIX + _digest(("active-step-and-local-wall-1", signature, environment, execution))
    return _TimingKey(graph.graph_id, graph.version, configuration_key, compatibility_key, len(graph._compiled_graph.steps))
