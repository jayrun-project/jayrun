"""Assemble ordinary ArtifactFlows using one translation scope per attachment call."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Literal

from ..artifact.base import Artifact
from ..operator._binding import _BoundOperator
from ..operator.base import BaseOperator
from ..serializer.base import BaseSerializer
from .artifact_flow import ArtifactFlow
from .definition.artifact import ArtifactDefinition

if TYPE_CHECKING:
    from .graph_definition import GraphDefinition

ArtifactRef = int | Artifact | ArtifactDefinition
Attachment = tuple[ArtifactFlow, ArtifactRef | None, Literal["start", "end"]]


def _translations(graph: GraphDefinition, attachments: tuple[Attachment, ...],
                  translations: Mapping[Artifact, ArtifactRef] | None) -> dict[int, Artifact]:
    if not attachments:
        raise ValueError("Supply at least one flow attachment.")
    registry = graph._specification.artifacts
    mapping: dict[int, Artifact] = {}
    sources: set[int] = set()
    imported: set[int] = set()

    def translate(source: Artifact, target: Artifact) -> None:
        if id(source) in mapping and mapping[id(source)] is not target:
            raise ValueError(f"Conflicting translations of {source!r} in one attachment.")
        mapping[id(source)] = target

    for item in attachments:
        if not isinstance(item, tuple) or len(item) != 3:
            raise TypeError("Each attachment must be a (flow, destination, position) tuple.")
        flow, destination, position = item
        if not isinstance(flow, ArtifactFlow):
            raise TypeError("The attachment source must be an ArtifactFlow.")
        if position not in ("start", "end"):
            raise ValueError("Attachment position must be 'start' or 'end'.")
        if id(flow) in imported:
            raise ValueError("The same source flow appears twice; author repetition in the flow.")
        imported.add(id(flow))
        if flow.artifact is not None:
            sources.add(id(flow.artifact))
        for operator in flow.operators:
            sources.update(map(id, operator.input_artifacts))
            sources.update(map(id, operator.output_artifacts))
        if destination is not None:
            if flow.artifact is None:
                raise ValueError("An artifact-free root has no artifact to translate.")
            translate(flow.artifact, registry.resolve(destination))

    if translations is not None:
        if not isinstance(translations, Mapping):
            raise TypeError("translations must be a mapping of source artifacts to destinations")
        for source, target in translations.items():
            if not isinstance(source, Artifact) or id(source) not in sources:
                raise KeyError("Translation source does not belong to the attached flows.")
            translate(source, target if isinstance(target, Artifact) else registry.resolve(target))

    return mapping


def _assemble_rows(graph: GraphDefinition, attachments: tuple[Attachment, ...],
                   mapping: Mapping[int, Artifact]) -> dict[int, ArtifactFlow]:
    operators: dict[int, BaseOperator] = {}
    translated: dict[int, ArtifactFlow] = {}

    def import_flow(flow: ArtifactFlow) -> ArtifactFlow:
        if id(flow) not in translated:
            components = []
            for component in flow.components:
                if isinstance(component, ArtifactFlow):
                    components.append(import_flow(component))
                else:
                    if id(component) not in operators:
                        operators[id(component)] = _BoundOperator.translating(component, mapping)
                    components.append(operators[id(component)])
            translated[id(flow)] = ArtifactFlow(*components, artifact=mapping.get(id(flow.artifact), flow.artifact),
                                            name=flow.name, description=flow.description)
        return translated[id(flow)]

    def row_key(flow: ArtifactFlow) -> int:
        return id(flow.artifact) if flow.artifact is not None else id(flow)

    existing = {row_key(flow): flow for flow in graph.flows}
    additions: dict[int, tuple[list[ArtifactFlow], list[ArtifactFlow]]] = {key: ([], []) for key in existing}
    for source, _, position in attachments:
        flow = import_flow(source)
        prefix, suffix = additions.setdefault(row_key(flow), ([], []))
        (prefix if position == "start" else suffix).append(flow)

    rows = {}
    for key, (prefix, suffix) in additions.items():
        original = existing.get(key)
        if original is None:
            parts = prefix + suffix
            rows[key] = parts[0] if len(parts) == 1 else ArtifactFlow(*parts, artifact=parts[0].artifact)
        elif prefix or suffix:
            # Splice into the existing root. Repeated attachment does not create
            # an ever-deeper tree of artificial containers around the old row.
            rows[key] = ArtifactFlow(*prefix, *original.components, *suffix, artifact=original.artifact,
                                     name=original.name, description=original.description)
        else:
            rows[key] = original
    return rows


def attach_flows(
    graph: GraphDefinition,
    attachments: tuple[Attachment, ...],
    translations: Mapping[Artifact, ArtifactRef] | None,
    entry_artifacts: Iterable[ArtifactRef] | None,
    serializers: Mapping[ArtifactRef, BaseSerializer] | None,
) -> GraphDefinition:
    from .graph_definition import GraphDefinition

    registry = graph._specification.artifacts
    mapping = _translations(graph, attachments, translations)
    rows = _assemble_rows(graph, attachments, mapping)

    def outer_artifact(reference: ArtifactRef) -> Artifact:
        # IDs and definitions always refer to the receiver. A new boundary
        # can be named explicitly by its actual Artifact.
        return reference if isinstance(reference, Artifact) else registry.resolve(reference)

    entries = (tuple(flow.artifact for flow in graph._entry_flows) if entry_artifacts is None
               else tuple(map(outer_artifact, entry_artifacts)))
    if len(set(map(id, entries))) != len(entries):
        raise ValueError("Multiple entry references resolve to the same artifact.")
    if any(id(artifact) not in rows for artifact in entries):
        raise ValueError("Every selected entry artifact needs a consumer flow in the resulting graph.")
    result = GraphDefinition(*rows.values(), entry_flows=tuple(rows[id(artifact)] for artifact in entries),
                             version=graph.version, name=graph.name, description=graph.description)
    validation = result.validate()
    if not validation.valid:
        raise ValueError(f"Attachment produces {len(validation.mismatched_edges)} incompatible artifact edge(s).")
    # Destination declarations stay in the new graph. A flow carries no
    # resource selection, timing policy or boundary codec from another graph.
    result._resource_context.set(graph._resource_context.instances)
    result._timing_config_fields = graph._timing_config_fields
    if serializers is not None:
        if not isinstance(serializers, Mapping):
            raise TypeError("serializers must be a mapping")
        bindings = {}
        for reference, serializer in serializers.items():
            artifact = outer_artifact(reference)
            if artifact in bindings:
                raise ValueError("Multiple serializer references resolve to the same artifact.")
            bindings[artifact] = serializer
        result.bind_serializers(bindings)
    elif graph._serializer_bindings:
        boundary = {a for a, d in result._artifacts.items() if d.is_exit or a in entries}
        inherited = {a: codec for a, codec in graph._serializer_bindings.items() if a in boundary}
        if inherited.keys() != boundary:
            raise ValueError("Attachment changes serializer coverage. Supply the complete outer serializers "
                             "mapping, or serializers={} to select local execution without codecs.")
        result.bind_serializers(inherited)
    return result
