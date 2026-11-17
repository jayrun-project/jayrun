"""Detached declaration evidence; never reconstructs or executes user components."""
from __future__ import annotations

import inspect
import json
import math
import re
from typing import TYPE_CHECKING

from ..artifact.field import ArtifactField
from ..config.field import ConfigField
from ..declaration.field import DeclarativeField
from ..operator.base import BaseOperator
from ..resource.base import BaseResource
from .artifact_flow import ArtifactFlow

if TYPE_CHECKING:
    from .graph_definition import GraphDefinition

SCHEMA = "jayrun.declaration/1"
MAX_BYTES = 32 * 1024 * 1024
_SENSITIVE = re.compile(r"password|secret|credential|authorization|access.?token|api.?key|private.?key", re.I)


def _type_name(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _metadata(item: object) -> dict[str, object]:
    return {"name": item.name, "description": item.description}


def declaration_report(graph: GraphDefinition) -> dict[str, object]:
    """Export confirmed declarations; unsupported state is explicitly disclosed."""
    if not graph.confirmed:
        raise RuntimeError("confirm the graph before exporting its declaration report")
    limitations: list[dict[str, str]] = []

    def missing(path: str, reason: str) -> None:
        limitations.append({"path": path, "reason": reason})

    def value(item: object, path: str, depth: int = 0) -> object:
        if depth > 64:
            raise ValueError("declaration value nesting exceeds 64 levels")
        kind = type(item)
        if item is None or kind in (str, bool, int):
            return item
        if kind is float and math.isfinite(item):
            return item
        if kind is tuple:
            return {"tuple": [value(v, f"{path}/{i}", depth + 1) for i, v in enumerate(item)]}
        if kind is type:
            return {"python_type": _type_name(item)}
        missing(path, "unsupported value; supply its construction contract externally")
        return {"unavailable_type": _type_name(kind)}

    artifacts = {artifact: f"a{i}" for i, artifact in enumerate(graph.artifacts)}
    operators: dict[BaseOperator, str] = {}
    flows: dict[ArtifactFlow, str] = {}

    def discover(flow: ArtifactFlow) -> None:
        if flow in flows:
            return
        flows[flow] = f"f{len(flows)}"
        for child in flow.components:
            if isinstance(child, ArtifactFlow):
                discover(child)
            elif child not in operators:
                operators[child] = f"o{len(operators)}"

    for flow in graph.flows:
        discover(flow)
    resources: dict[object, str] = {}
    for operator in operators:
        for field in operator.resource_fields:
            bound = graph._resource_context.instances.get(field)
            if bound is not None and bound not in resources:
                resources[bound] = f"r{len(resources)}"
    serializers: dict[object, str] = {}
    for artifact in artifacts:
        bound = graph._serializer_bindings.get(artifact)
        if bound is not None and bound not in serializers:
            serializers[bound] = f"s{len(serializers)}"

    owners = {**operators, **resources}
    components: dict[type, str] = {}
    component_data: dict[str, object] = {}

    def declaration(instance: object, local_id: str, allowed: set[str]) -> dict[str, object]:
        cls = type(instance)
        if cls not in components:
            cid = f"t{len(components)}"
            components[cls] = cid
            version_owner = next((base for base in cls.__mro__ if "__version__" in vars(base)), None)
            component_data[cid] = {
                "type": _type_name(cls),
                "version": value(getattr(cls, "__version__", None), f"components/{cid}/version"),
                "version_declared_by": None if version_owner is None else _type_name(version_owner),
                "requirements": value(getattr(cls, "requirements", ()), f"components/{cid}/requirements"),
            }
        try:
            parameters = inspect.signature(cls.__init__).parameters
        except (TypeError, ValueError):
            missing(local_id, "constructor signature unavailable")
            parameters = {}
        for name, parameter in parameters.items():
            if name not in allowed and parameter.kind not in (parameter.VAR_KEYWORD, parameter.VAR_POSITIONAL):
                missing(f"{local_id}/constructor/{name}", "constructor argument not retained by declaration API")
        ignored = {"_name", "_description"}
        if isinstance(instance, BaseOperator):
            ignored.update(("_operator_initialized", "outputs"))
        elif isinstance(instance, BaseResource):
            ignored.add("_resource_initialized")
        for name, state in vars(instance).items():
            if name not in ignored and not isinstance(state, DeclarativeField):
                missing(f"{local_id}/state/{name}", "extra instance state is outside the declaration contract")
        return {"component": components[cls], **_metadata(instance)}

    config_data = {}
    config_ids = {}
    registry = graph._specification.configs
    for field, definition in zip(registry.sources, registry.definitions, strict=True):
        key = f"c{definition.config_id}"
        config_ids[field] = key
        path = f"configs/{key}/default"
        if field.default is not None and _SENSITIVE.search(field.attribute_name or ""):
            default = {"redacted": True}
            missing(path, "sensitive default; supply externally")
        else:
            default = value(field.default, path)
        config_data[key] = {"config_id": definition.config_id, "owner": owners[field.owner],
                            "field": field.attribute_name, **_metadata(field), "required": field.required,
                            "value_type": _type_name(field.value_type), "default": default}

    def artifact_field(field: ArtifactField, path: str) -> dict[str, object]:
        properties = []
        for i, prop in enumerate(field.properties):
            location = f"{path}/properties/{i}"
            if "_value" in vars(prop):
                declared = value(vars(prop)["_value"], location)
            else:
                missing(location, "property has no retained declaration value")
                declared = {"unavailable_type": _type_name(type(prop))}
            properties.append({"type": _type_name(type(prop)), "value": declared})
        return {**_metadata(field), "required": field.required,
                "bound": field.is_bound, "artifact": artifacts.get(field.artifact),
                "properties": properties}

    operator_data = {}
    for operator, key in operators.items():
        item = declaration(operator, key, {"self", "name", "description", "outputs",
                                          *(f.attribute_name for f in operator.declared_artifact_fields)})
        item["execution"] = "async" if inspect.iscoroutinefunction(type(operator).execute) else "sync"
        item["inputs"] = {field.attribute_name: artifact_field(field, f"operators/{key}/inputs/{field.attribute_name}")
                          for field in operator.declared_artifact_fields}
        item["outputs"] = [artifact_field(field, f"operators/{key}/outputs/{i}") for i, field in enumerate(operator.outputs)]
        item["resources"] = {
            field.attribute_name: {**_metadata(field), "required": field.required,
                                   "parallel_safe": field.parallel_safe,
                                   "binding": resources.get(graph._resource_context.instances.get(field))}
            for field in operator.resource_fields}
        operator_data[key] = item
    resource_data = {key: declaration(resource, key, {"self", "name", "description"})
                     for resource, key in resources.items()}
    serializer_data = {key: declaration(serializer, key, {"self", "name", "description"})
                       for serializer, key in serializers.items()}
    artifact_data = {}
    for artifact, key in artifacts.items():
        definition = graph._artifacts[artifact]
        artifact_data[key] = {**_metadata(artifact), "artifact_id": definition.artifact_id,
                              "role": definition.role.value, "exit": definition.is_exit,
                              "serializer": serializers.get(graph._serializer_bindings.get(artifact))}
    result = {
        "schema": SCHEMA,
        "graph": {"graph_id": graph.graph_id, "version": graph.version, **_metadata(graph)},
        "components": component_data,
        "artifacts": artifact_data,
        "operators": operator_data,
        "resources": resource_data,
        "serializers": serializer_data,
        "configs": config_data,
        "flows": {key: {**_metadata(flow), "artifact": artifacts.get(flow.artifact),
                         "components": [flows[c] if isinstance(c, ArtifactFlow) else operators[c] for c in flow.components]}
                  for flow, key in flows.items()},
        "root_flows": [flows[f] for f in graph.flows],
        "entry_flows": [flows[f] for f in graph._entry_flows],
        "timing_configs": None if graph._timing_config_fields is None else [config_ids[f] for f in graph._timing_config_fields],
        "limitations": limitations,
        "scope": "Declared structure and authored intent; component code, closure/class state, selected run values and execution outcomes are external. Null metadata means not supplied. An empty limitations list does not prove behavioral completeness.",
    }
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_BYTES:
        raise ValueError("declaration report exceeds 32 MiB; nothing exported")
    return result
