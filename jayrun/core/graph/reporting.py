from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from inspect import iscoroutinefunction
from pathlib import Path
from typing import TYPE_CHECKING

from ..validation.graph import OperatorNode

if TYPE_CHECKING:
    from .graph_definition import GraphDefinition
    from .graph_registry import GraphRegistry


class GraphReporter:
    """Render a graph or registry with a shared text-report interface."""

    def __init__(self, formatter: Callable[[bool], str], default_filename: str) -> None:
        self._formatter = formatter
        self._default_filename = default_filename

    def __str__(self) -> str:
        return self.format()

    def format(self, *, compact: bool = False) -> str:
        """Return current declarations and cached validation as readable text.

        Compact output preserves every node, edge, binding, and validation
        finding, but omits individual operator field declarations. Full output
        includes unbound fields, field descriptions, and declared contracts.
        """
        if not isinstance(compact, bool):
            raise TypeError("compact must be a bool")
        from ...visualization.contract import MAX_EXPORT_BYTES
        text = self._formatter(compact)
        if len(text.encode('utf-8')) > MAX_EXPORT_BYTES:
            raise ValueError('declaration report exceeds export byte limit; nothing exported')
        return text

    def print(self, *, compact: bool = False) -> None:
        """Print the selected report format to standard output."""
        print(self.format(compact=compact))

    def save(self, path: str | Path | None = None, *, compact: bool = False) -> Path:
        """Write UTF-8 text with a trailing newline and return its absolute path.

        Missing parent directories are created and an existing file is replaced.
        """
        text = self.format(compact=compact)
        output = Path(path if path is not None else self._default_filename).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
        return output


def _text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _description(value: object) -> str:
    description = getattr(value, "description", None)
    return "" if description is None else f"; description={_text(description)}"


def _value(value: object) -> str:
    from ...visualization.contract import summarize
    if isinstance(value, type):
        return summarize(value)
    return repr(summarize(value)).replace("\r", "\\r").replace("\n", "\\n")


def _default(field: object) -> str:
    from ...visualization.contract import summarize
    # Apply the same key-aware redaction as declaration plots, without calling
    # user object repr, properties, or serializers.
    return _value(next(iter(summarize({field.attribute_name: field.default}).values())))


def _type(value: object) -> str:
    return _value(type(value))


def _section(title: str, rows: Iterable[str]) -> list[str]:
    return ["", title, "-" * len(title), *(tuple(rows) or ("None",))]


def _refs(prefix: str, values: Iterable[int]) -> str:
    return ", ".join(f"{prefix}{value}" for value in values) or "none"


def _format_graph(graph: GraphDefinition, compact: bool = False) -> str:
    inspection = graph.inspect
    result = graph.validate()
    artifact_ids = {
        artifact: definition.artifact_id
        for artifact, definition in zip(graph.artifacts, inspection.artifacts, strict=True)
    }
    operators = [node for node in result.nodes if isinstance(node, OperatorNode)]
    incoming = defaultdict(list)
    outgoing = defaultdict(list)
    for edge in result.edges:
        outgoing[edge.source].append(edge)
        incoming[edge.target].append(edge)
    counts = Counter(edge.status.value if edge.status else "not compared" for edge in result.edges)
    empty_contracts = sum(
        edge.validation is not None and not edge.validation.property_reports
        for edge in result.edges
    )
    status = "COMPLETE" if inspection.complete else "PENDING RESOURCE SELECTION"
    serializers = inspection.serializers
    lines = [
        f"Graph report | version={_text(graph.version)} | {'COMPACT' if compact else 'FULL'}",
        f"Definition: {status}; confirmed={graph.confirmed}",
        f"Validation: {'VALID' if result.valid else 'INVALID'} (declared artifact contracts only)",
        f"Nodes: {len(result.nodes)}; operators: {len(operators)}; edges: {len(result.edges)}; artifacts: {len(artifact_ids)}",
        f"Descriptions supplied: operators {sum(n.operator.description is not None for n in operators)}/{len(operators)}; artifacts {sum(a.description is not None for a in inspection.artifacts)}/{len(artifact_ids)}",
        f"Entries: {_refs('A', (a.artifact_id for a in inspection.artifacts.entry))}",
        f"Exits: {_refs('A', (a.artifact_id for a in inspection.artifacts.exit))}",
        f"Contracts: {counts['match']} match; {counts['mismatch']} mismatch; {counts['unknown']} unknown; {counts['not compared']} boundary edges not compared",
        f"Comparisons with no declared properties: {empty_contracts}",
        f"Resources: {len(inspection.resources.bindings)}/{len(inspection.resources)} bound; shared instances: {len(inspection.resources.shared)}",
        f"Missing required resources: {len(inspection.resources.missing)}; optional unbound: {sum(not r.required for r in inspection.resources.unbound)}",
        f"Serializers: enabled={serializers.enabled}; finalized={serializers.bound}; boundary coverage={len(serializers)}/{len(serializers.boundary)}",
        "Scope: static declarations and bindings; runtime values, execution success, and performance are not established.",
        "IDs N=node, E=edge, A=artifact, R=resource field, C=config, S=resource instance; local to this graph report.",
        "Artifact role describes origin: unused means no consuming flow. exit identifies boundary outputs; run policy selects retained values.",
        "Descriptions are quoted metadata, omitted when absent. UNBOUND means no declaration binding, never a runtime None value.",
    ]
    columns = defaultdict(list)
    for node in operators:
        columns[node.layout_position[1]].append(node.node_id)
    lines.extend(_section("STRUCTURE OVERVIEW", (
        f"Column {column}: {_refs('N', nodes)} ({len(nodes)} operators)"
        for column, nodes in sorted(columns.items())
    )))
    lines.append("Columns describe graph layout, not execution timing or guaranteed parallelism.")
    diagnostic_rows = []
    for edge in result.edges:
        if not (edge.mismatched or edge.unknown):
            continue
        diagnostic_rows.append(
            f"E{edge.edge_id}: N{edge.source} -> N{edge.target} / A{artifact_ids[edge.artifact]} / {edge.status.value.upper()}"
        )
        for prop in edge.validation.property_reports:
            diagnostic_rows.append(
                f"  {prop.property_name}: {prop.status.value.upper()}; "
                f"produced={_value(prop.source_value) if prop.source_declared else 'NOT DECLARED'}; "
                f"required={_value(prop.target_value) if prop.target_declared else 'NOT DECLARED'}; reason={_text(prop.reason)}"
            )
    lines.extend(_section("VALIDATION FINDINGS", diagnostic_rows))
    lines.extend(_section("ARTIFACTS", (
        f"A{artifact.artifact_id}: name={_text(artifact.name)}; role={artifact.role.value}; exit={artifact.is_exit}"
        + _description(artifact)
        for artifact in inspection.artifacts
    )))
    node_rows = []
    for node in result.nodes:
        predecessors = sorted({edge.source for edge in incoming[node.node_id]})
        successors = sorted({edge.target for edge in outgoing[node.node_id]})
        if isinstance(node, OperatorNode):
            operator = node.operator
            node_rows.append(
                f"N{node.node_id} OPERATOR: name={_text(operator.display_name)}; implementation={_type(operator)}; "
                f"execution={'async' if iscoroutinefunction(operator.execute) else 'sync'}; "
                f"layout={node.layout_position}; predecessors=[{_refs('N', predecessors)}]; successors=[{_refs('N', successors)}]"
                + _description(operator)
            )
            if compact:
                continue
            for side, fields in (("input", operator.declared_artifact_fields), ("output", operator.outputs)):
                for field in fields:
                    binding = "UNBOUND" if field.artifact is None else f"A{artifact_ids[field.artifact]}"
                    properties = ", ".join(f"{type(prop).__name__}={_value(prop.value)}" for prop in field.properties) or "none declared"
                    node_rows.append(
                        f"  {side} field={_text(field.attribute_name)}; binding={binding}; required={field.required}; "
                        f"properties=[{properties}]" + _description(field)
                    )
            for field in operator.resource_fields:
                definition = graph._specification.resources.definition_for(field)
                node_rows.append(f"  resource field={_text(field.attribute_name)} -> R{definition.resource_id}")
            for field in operator.config_fields:
                reference = (
                    f"C{graph._specification.configs.definition_for(field).config_id}"
                    if inspection.complete else "ID pending resource selection"
                )
                node_rows.append(
                    f"  config field={_text(field.attribute_name)} -> {reference}; type={_value(field.value_type)}; "
                    f"required={field.required}; default={_default(field)}" + _description(field)
                )
        else:
            kind = node.node_type.value.upper()
            if kind == "EXIT" and incoming[node.node_id][0].edge_type.value == "unused":
                kind = "UNUSED OUTPUT"
            node_rows.append(
                f"N{node.node_id} {kind}: A{node.artifact_id}; "
                f"predecessors=[{_refs('N', predecessors)}]; successors=[{_refs('N', successors)}]"
            )
    lines.extend(_section("NODES", node_rows))
    edge_rows = []
    for edge in result.edges:
        source = f"N{edge.source}" + (f".output[{_text(edge.source_field.attribute_name)}]" if edge.source_field else "")
        target = f"N{edge.target}" + (f".input[{_text(edge.target_field.attribute_name)}]" if edge.target_field else "")
        outcome = edge.status.value.upper() if edge.status else "NOT COMPARED (boundary)"
        if edge.validation is not None and not edge.validation.property_reports:
            outcome += " (no declared properties)"
        edge_rows.append(f"E{edge.edge_id}: {source} -> {target}; A{artifact_ids[edge.artifact]}; kind={edge.edge_type.value}; {outcome}")
    lines.extend(_section("EDGES", edge_rows))
    resources = inspection.resources.bindings
    instance_ids = {identity: index for index, identity in enumerate(dict.fromkeys(id(r) for r in resources.values()))}
    resource_rows = []
    for field in inspection.resources:
        resource = resources.get(field)
        binding = f"S{instance_ids[id(resource)]}" if resource is not None else "UNBOUND"
        resource_rows.append(
            f"R{field.resource_id}: owner={_text(field.owner)}; field={_text(field.attribute_name)}; "
            f"binding={binding}; required={field.required}; parallel_safe={field.parallel_safe}" + _description(field)
        )
    seen = set()
    for resource in resources.values():
        if id(resource) in seen:
            continue
        seen.add(id(resource))
        fields = [field.resource_id for field, bound in resources.items() if bound is resource]
        resource_rows.append(
            f"S{instance_ids[id(resource)]}: name={_text(resource.display_name)}; implementation={_type(resource)}; "
            f"fields=[{_refs('R', fields)}]; requirements={_text(list(resource.requirements))}" + _description(resource)
        )
        if inspection.complete:
            configs = (graph._specification.configs.definition_for(f).config_id for f in resource.config_fields)
            resource_rows.append(f"  configs=[{_refs('C', configs)}]")
        if not inspection.complete:
            for config in resource.config_fields:
                resource_rows.append(f"  pending config={_text(config.attribute_name)}; type={_value(config.value_type)}" + _description(config))
    lines.extend(_section("RESOURCES", resource_rows))
    lines.append("Shared S IDs identify the same declared instance; runtime reuse and concurrency depend on configuration, placement, and parallel_safe.")
    lines.extend(_section("CONFIGS", (
        f"C{field.config_id}: owner={_text(field.owner)}; field={_text(field.attribute_name)}; "
        f"type={_value(field.value_type)}; required={field.required}; default={_default(field)}" + _description(field)
        for field in inspection.configs
    ) if inspection.complete else ("PENDING RESOURCE SELECTION; operator declarations appear under NODES.",)))
    codecs = {codec.artifact_id: codec for codec in serializers}
    lines.extend(_section("SERIALIZERS", (
        f"A{artifact.artifact_id}: " + (
            f"implementation={codecs[artifact.artifact_id].serializer_type}; name={_text(codecs[artifact.artifact_id].name)}; "
            f"requirements={_text([str(r) for r in codecs[artifact.artifact_id].requirements])}"
            + _description(codecs[artifact.artifact_id])
            if artifact.artifact_id in codecs else "UNBOUND (serialization optional)"
        )
        for artifact in serializers.boundary
    )))
    requirements = inspection.requirements
    rows = [f"Operator: {item}" for item in requirements.operators]
    rows.extend(f"Serializer: {item}" for item in requirements.serializers)
    if inspection.complete:
        rows.extend(f"Resource: {item}" for item in requirements.resources)
        rows.extend(f"Combined: {item}" for item in requirements.all)
    else:
        rows.append("Resource and combined requirements: PENDING RESOURCE SELECTION")
    lines.extend(_section("REQUIREMENTS", rows))
    return "\n".join(lines).rstrip()


def _format_registry(registry: GraphRegistry, compact: bool = False) -> str:
    with registry._lock:
        entries = registry._entries()
        shared = registry.inspect.resources.shared
        conflicts = registry.inspect.conflicts
    lines = [
        f"Graph registry report: {len(entries)} graphs | {'COMPACT' if compact else 'FULL'}",
        f"Shared resource instances across graphs: {len(shared)}; graph pairs with requirement conflicts: {len(conflicts)}",
        "Graph identity is (key, version). N/E/A/R/C/S identifiers are scoped to each graph section.",
    ]
    lines.extend(_section("GRAPH OVERVIEW", (
        f"{identity!r}: operators={len(graph.inspect.operators)}; artifacts={len(graph.artifacts)}; "
        f"validation={'VALID' if graph.validate().valid else 'INVALID'}; "
        f"serializers={'enabled' if graph.inspect.serializers.enabled else 'disabled'}"
        for identity, graph in entries
    )))
    lines.extend(_section("SHARED RESOURCES", (
        " | ".join(f"{identity!r}: {_refs('R', (f.resource_id for f in fields))}" for identity, fields in group.items())
        for group in shared
    )))
    lines.extend(_section("REQUIREMENT CONFLICTS", (
        f"{comparison.left!r} / {comparison.right!r}: {conflict.left} versus {conflict.right}"
        for comparison in conflicts for conflict in comparison.conflicts
    )))
    for identity, graph in entries:
        lines.extend(_section(f"GRAPH {identity!r}", (_format_graph(graph, compact),)))
    return "\n".join(lines).rstrip()
