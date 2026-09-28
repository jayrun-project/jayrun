"""Translate authoritative declaration/validation evidence, never runtime guesses."""
from __future__ import annotations

from collections import Counter
import colorsys
import hashlib
import webbrowser
from copy import deepcopy
from functools import cached_property
from html import escape
from pathlib import Path
from typing import Literal
from ...core.graph.compiled_graph import CompiledOperatorStep, CompiledResourceStep
import json
from typing import TYPE_CHECKING

from .._segments import annotate_segments
from ..colors import artifact_color
from ..contract import SCHEMA_VERSION, summarize, validate_payload

if TYPE_CHECKING:
    from ...core.artifact.base import Artifact
    from ...core.graph.graph_definition import GraphDefinition
    from ...core.validation.graph import GraphValidationReport


def _configs(fields: tuple, *, include_defaults: bool = True) -> dict:
    return {field.attribute_name: {
        "Description": field.description,
        "Value type": summarize(field.value_type),
        "Required": field.required,
        "Declared default": (next(iter(summarize({field.attribute_name: field.default}).values()))
                             if include_defaults else "Not stored in layout; see resolved configurations"),
    } for field in fields}


def _properties(fields: tuple) -> dict:
    return {type(prop).__name__: summarize(prop.value) for prop in fields}


def _validation(value: object) -> dict:
    if value is None:
        return {"Compatibility": "Unchecked: boundary connection has no source/target property comparison."}
    return {report.property_name: {
        "Status": report.status.value.upper(),
        "Producer declares": report.source_declared,
        "Producer contract": summarize(report.source_value) if report.source_declared else "Not declared",
        "Consumer declares": report.target_declared,
        "Consumer contract": summarize(report.target_value) if report.target_declared else "Not declared",
        "Reason": report.reason or "Both declared contracts are compatible.",
    } for report in value.property_reports} or {"Compatibility": "UNKNOWN: no comparable property contracts declared."}


def definition_payload(graph: GraphDefinition) -> dict:
    """Capture a definition without compilation, execution, or resource setup.

    Construction/binding must finish before sharing a graph across threads, as
    required by GraphDefinition. A cached plot facade does not cache bindings.
    """
    from ...core.graph.graph_definition import GraphDefinition
    if not isinstance(graph, GraphDefinition):
        raise TypeError("graph must be a GraphDefinition")
    return _report_payload(graph.validate(), graph.artifacts, graph=graph)


def _report_payload(report: GraphValidationReport, artifacts: tuple[Artifact, ...], *, graph: GraphDefinition | None = None, include_config_defaults: bool = True) -> dict:
    from ...core.validation.graph import EntryNode, ExitNode, OperatorNode

    artifact_ids = {artifact: f"artifact-{i}" for i, artifact in enumerate(artifacts)}
    artifact_data = [{"id": artifact_ids[artifact], "label": artifact.name or "Artifact",
                      "description": artifact.description or "", "color": artifact_color(i)}
                     for i, artifact in enumerate(artifacts)]
    declarations = {}
    for node in report.nodes:
        if isinstance(node, OperatorNode) and id(node.operator) not in declarations:
            declarations[id(node.operator)] = f"declaration-{len(declarations)}"
    occurrence_counts = Counter(id(node.operator) for node in report.nodes if isinstance(node, OperatorNode))
    occurrence_indices = Counter()
    field_definitions, bindings = {}, {}
    resource_ids, field_ids = {}, {}
    if graph is not None:
        # ResourceDefinition records the declaration's first occurrence and
        # attribute name. Resolve that selector through the actual immutable
        # OperatorReference, then use ResourceField *object identity* throughout.
        references = {ref.layout_position: ref for ref in graph.inspect.operators}
        for definition in graph.inspect.resources.all:
            reference = references.get(definition.layout_position)
            if reference is None:
                continue
            for field in reference.resource_fields:
                if field.owner is reference.operator and field.attribute_name == definition.attribute_name:
                    field_definitions[field] = definition
                    break
        bindings = dict(graph.inspect.resources.bindings)
    nodes, port_ids, findings = [], {}, []
    for node in report.nodes:
        nid = f"node-{node.node_id}"
        item = {"id": nid, "kind": node.node_type.value, "label": node.label,
                "column": node.x_position, "row": node.y_position,
                "inputs": [], "outputs": [], "resources": [],
                "identity": {"Validation node": str(node.node_id)}}
        if isinstance(node, OperatorNode):
            operator = node.operator
            occurrence_indices[id(operator)] += 1
            occurrence = occurrence_indices[id(operator)]
            count = occurrence_counts[id(operator)]
            item["label"] = operator.display_name + (f" · {occurrence}" if count > 1 else "")
            item["description"] = operator.description or ""
            item["identity"].update({"Declaration": declarations[id(operator)], "Occurrence": nid,
                                     "Core layout position": list(node.layout_position)})
            item["details"] = {"Configuration declarations": _configs(operator.config_fields, include_defaults=include_config_defaults)}
            if count > 1:
                item["details"]["Occurrence role"] = f"Occurrence {occurrence} of {count} of the same declaration, at execution stage {node.layout_position[1] + 1}. Not a duplicate per flow or resource. All occurrences resolve their own actual resource fields."
            for side, fields in (("inputs", operator.declared_artifact_fields), ("outputs", operator.outputs)):
                for index, field in enumerate(fields):
                    pid = f"{nid}/{side}/{index}"
                    port_ids[(node.node_id, side, field)] = pid
                    item[side].append({"id": pid, "label": field.display_name,
                                       "description": field.description or "",
                                       "artifact_id": artifact_ids.get(field.artifact),
                                       "details": {"Required": field.required,
                                                   "Binding": "Bound" if field.artifact is not None else "Unbound",
                                                   "Contracts": _properties(field.properties)},
                                       "identity": {"Declaration": declarations[id(operator)], "Field": field.attribute_name}})
            for index, field in enumerate(operator.resource_fields):
                definition = field_definitions.get(field)
                resource = bindings.get(definition)
                field_ids.setdefault(field, f"resource-field-{len(field_ids)}")
                if resource is not None:
                    resource_ids.setdefault(id(resource), f"resource-declaration-{len(resource_ids)}")
                state = "unknown" if definition is None else "bound" if resource is not None else "required-unbound" if field.required else "optional-unbound"
                label = f"{field.display_name}: {resource.display_name if resource is not None else state}"
                marker = {"id": f"{nid}/resource/{index}", "label": label, "state": state,
                          "description": field.description or "",
                          "identity": {"Field identity": field_ids[field],
                                       "Inspected resource ID": str(definition.resource_id) if definition else None,
                                       "Resource declaration identity": resource_ids.get(id(resource)) if resource is not None else None},
                          "details": {"Field": field.attribute_name, "Required": field.required,
                                      "Parallel-safe declaration": field.parallel_safe,
                                      "Binding scope": "Graph declaration; this actual immutable field is used by this occurrence.",
                                      "Sharing evidence": "Verified graph-bound declaration object; see its consumers below" if resource is not None else "No verified bound declaration",
                                      "Runtime sharing": "Unknown: declaration identity does not establish cache equivalence, acquisition, shared memory, or engine_id-local instances."}}
                if resource is not None:
                    marker["details"].update({"Resource": resource.display_name,
                                              "Resource description": resource.description,
                                              "Resource configuration declarations": _configs(resource.config_fields, include_defaults=include_config_defaults)})
                if definition is None:
                    findings.append({"id": f"finding-binding-{node.node_id}-{index}", "subject": marker["id"], "severity": "warning",
                                     "message": "Binding evidence unavailable: the actual resource field could not be resolved through declaration inspection."})
                elif resource is None:
                    findings.append({"id": f"finding-binding-{node.node_id}-{index}", "subject": marker["id"],
                                     "severity": "error" if field.required else "info",
                                     "message": f"{field.display_name}: {'required' if field.required else 'optional'} resource is unbound."})
                item["resources"].append(marker)
        elif isinstance(node, (EntryNode, ExitNode)):
            item["label"] = node.artifact.name or "Artifact"
            item["description"] = node.artifact.description or ""
            side = "outputs" if isinstance(node, EntryNode) else "inputs"
            pid = f"{nid}/{side}/boundary"
            port_ids[(node.node_id, side, None)] = pid
            item[side].append({"id": pid, "label": item["label"], "artifact_id": artifact_ids[node.artifact]})
            item["identity"]["Artifact ID"] = str(node.artifact_id)
            item["details"] = {"Boundary": "Application-supplied initial value" if side == "outputs" else "Final produced value; per-run retention policy is separate"}
        else:
            raise TypeError(f"Unsupported validation node: {type(node).__name__}")
        nodes.append(item)
    consumers = {}
    for item in nodes:
        for marker in item.get("resources", []):
            identity = marker["identity"]["Resource declaration identity"]
            if identity is not None:
                consumers.setdefault(identity, []).append(f"{item['label']} / {marker['details']['Field']}")
    for item in nodes:
        for marker in item.get("resources", []):
            identity = marker["identity"]["Resource declaration identity"]
            if identity is not None:
                marker["details"]["Bound consumer occurrences"] = consumers[identity]
    edges = []
    for edge in report.edges:
        status = edge.status.value if edge.status else "unchecked"
        item = {"id": f"edge-{edge.edge_id}", "label": edge.artifact.name or "Artifact",
                "source": {"node": f"node-{edge.source}", "port": port_ids[(edge.source, "outputs", edge.source_field)]},
                "target": {"node": f"node-{edge.target}", "port": port_ids[(edge.target, "inputs", edge.target_field)]},
                "artifact_id": artifact_ids[edge.artifact], "status": status,
                "description": edge.artifact.description or "",
                "details": {"Validation": _validation(edge.validation)},
                "identity": {"Validation edge": str(edge.edge_id), "Role": edge.edge_type.value}}
        edges.append(item)
        if status in {"mismatch", "unknown"}:
            findings.append({"id": f"finding-edge-{edge.edge_id}", "subject": item["id"],
                             "severity": "error" if status == "mismatch" else "info",
                             "message": f"{item['label']}: {status.upper()} on this connection. See its exact property findings."})
    reiterations = []
    if graph is not None:
        # ExecutionContext.initialize chooses entry artifacts whose inspected
        # definition is_exit. ExecutionArtifactStore.update saves OPERATOR writes
        # for those artifacts; repeat restores that checkpoint. See private
        # evidence for source line ranges. This is eligibility, not execution.
        entries = {definition.artifact_id for definition in graph.inspect.artifacts.entry}
        eligible = {definition.artifact_id for definition in graph.inspect.artifacts.exit} & entries
        entry_nodes = {node.artifact_id: node for node in report.nodes if isinstance(node, EntryNode)}
        exit_nodes = {node.artifact_id: node for node in report.nodes if isinstance(node, ExitNode)}
        for aid in sorted(eligible):
            first = [edge for edge in report.edges if edge.source == entry_nodes[aid].node_id]
            last = [edge for edge in report.edges if edge.target == exit_nodes[aid].node_id]
            if len(first) != 1 or len(last) != 1:
                raise ValueError("Core entry/exit evidence does not identify one feedback producer and destination input")
            source, target = last[0], first[0]
            reiterations.append({"id": f"reiteration-{aid}", "label": f"{source.artifact.name or 'Artifact'} → {target.target_field.display_name} · n → n+1",
                                 "artifact_id": artifact_ids[source.artifact],
                                 "source": {"node": f"node-{source.source}", "port": port_ids[(source.source, "outputs", source.source_field)]},
                                 "target": {"node": f"node-{target.target}", "port": port_ids[(target.target, "inputs", target.target_field)]},
                                 "status": "unchecked", "provenance": "ExecutionContext.initialize: entry ∩ exit; ExecutionArtifactStore.update/repeat: operator-written feedback checkpoint restored across iterations.",
                                 "details": {"Boundary": "Iteration n → n+1", "Evidence": "Structural eligibility only; no next iteration is requested or observed. Cross-boundary compatibility is not checked by the definition validator."}})
    version = graph.version if graph is not None else None
    data = {"schema_version": SCHEMA_VERSION, "kind": "graph", "id": "pending",
            "label": f"Graph definition · v{version}" if graph else "Validation report",
            "artifacts": artifact_data, "nodes": nodes, "edges": edges,
            "reiterations": reiterations, "findings": findings,
            "reiteration": {"eligibility": "known" if graph is not None else "unknown",
                            "reason": "Only entry artifacts that are also final produced exits can carry eligible operator-written feedback. Ordinary flow remains visible; this view has no execution evidence." if graph else "A bare validation report does not establish core iteration eligibility or resource bindings."},
            "identity": {"Graph version": version, "Execution graph identity": "Not available in a definition snapshot",
                         "Identity scope": "Presentation content identity only; not a run or compiled-work identity."},
            "details": {"Confirmed": graph.confirmed if graph is not None else "Unknown",
                        "Known mismatches": len(report.mismatched_edges), "Unknown connections": len(report.unknown_edges),
                        "Resources": "Markers describe declarations/bindings, never live resource instances."}}
    if graph is not None:
        data["details"]["Requirements"] = [str(requirement) for requirement in graph.inspect.requirements.all] if graph.inspect.requirements.complete else "Resource selection is incomplete; combined requirements are not available."
        data["details"]["Boundary serializers"] = [{"Artifact ID": str(s.artifact_id), "Name": s.name, "Description": s.description, "Type": s.serializer_type} for s in graph.inspect.serializers.all]
    annotate_segments(data, provenance="GraphDefinition._validate_dataflow and GraphValidation producer consume/register semantics; availability follows actual input/output fields.", lifecycle=True)
    # Presentation content hashing must not be confused with framework identity.
    clean = summarize(data["details"])
    data["details"] = clean
    data["id"] = "view-" + hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()).hexdigest()[:24]
    if graph is not None:
        data["identity"]["Intrinsic graph ID"] = graph.graph_id
        # Keep the established content-ID calculation above byte-for-byte stable.
        # The post-hash display must not call an available intrinsic ID unavailable.
        data["identity"].pop("Execution graph identity", None)
        data["identity"]["Execution context"] = "Not available in a definition snapshot"
        data["identity"]["Identity scope"] = "Intrinsic graph ID identifies declared structure; presentation content ID identifies this view. Neither establishes a context or compiled execution-step identity."
    return validate_payload(data)


def _progress_identities(payload: dict, graph: GraphDefinition, progress: ProgressSnapshot) -> None:
    """Expose checked step-to-component correspondence, never compile definitions for display."""
    nodes = {tuple(node["identity"]["Core layout position"]): node
             for node in payload["nodes"] if node["kind"] == "operator"}
    # GraphPlotter._check_progress already verified this exact compiled plan.
    steps = graph._compiled_graph.steps
    correspondence = payload["identity"].setdefault("Execution step correspondence", {})
    for value in progress.steps:
        step = steps[value.step_index]
        node = nodes.get(step.layout_position)
        if node is None:
            raise ValueError("progress step has no validation occurrence")
        subject = node
        if isinstance(step, CompiledResourceStep):
            markers = [marker for marker in node["resources"]
                       if marker["details"]["Field"] == step.resource_field.attribute_name]
            if len(markers) != 1:
                raise ValueError("progress resource step has no unique consuming field")
            subject = markers[0]
        correspondence.setdefault(subject["id"], []).append({
            "index": value.step_index, "kind": value.step_kind, "name": value.step_name})



class GraphPlotter:
    """Export the portable renderer through the existing plotting interface.

    Node order and actual fields come from validation; the independent renderer
    owns spacing and routes without changing the graph. No visualization dependency is
    required. Dashboard updates never execute work or update profiling history.

    Args:
        report: Structural validation report to visualize.
        artifacts: Graph artifacts in their stable color-assignment order.
        graph: Optional definition for strict progress compatibility checks.
        progress: Optional immutable initial progress snapshot.
    """

    _PALETTE = (
        "#38CDE0",
        "#AC8AFF",
        "#F3BE50",
        "#67D6A3",
        "#EF90BD",
        "#7CAEFF",
        "#EF7B73",
        "#BAD76D",
    )

    def __init__(
        self,
        report: GraphValidationReport,
        artifacts: tuple[Artifact, ...],
        *,
        graph: GraphDefinition | None = None,
        progress: ProgressSnapshot | None = None,
    ) -> None:
        self._report = report
        self._artifacts = artifacts
        self._graph = graph
        self._progress = progress

    def with_progress(self, progress: ProgressSnapshot) -> GraphPlotter:
        """Return a plotter with an immutable initial progress snapshot.

        The snapshot must belong to a structurally compatible graph version.
        No execution state, snapshot, or profiling history is mutated. Without
        an explicit mode, a plotter with progress opens in dashboard mode.

        Raises:
            TypeError: If progress is not a ProgressSnapshot.
            ValueError: If its version or compiled steps do not match the graph.
        """
        self._check_progress(progress)
        result = GraphPlotter(
            self._report, self._artifacts, graph=self._graph, progress=progress
        )
        result.__dict__["_structure"] = self._structure
        return result

    def build(self, *, mode: Literal["validation", "dashboard"] | None = None) -> dict:
        """Return fresh JSON-compatible viewer data, including routed geometry.

        Args:
            mode: ``validation`` shows compatibility badges; ``dashboard`` shows
                execution state. None selects dashboard when progress is bound,
                otherwise validation. Hover details remain available in both.

        Returns:
            A versioned data dictionary accepted by ``jayrun-graph`` elements.
            This replaces the former PyVis Network return type. Node and edge
            IDs are strings; no invisible routing nodes enter the graph model.
        """
        if mode is not None and mode not in ("validation", "dashboard"):
            raise ValueError("mode must be 'validation', 'dashboard', or None")
        selected = mode or ("dashboard" if self._progress is not None else "validation")
        data = deepcopy(self._structure)
        from .._legacy import attach_presentation
        payload = definition_payload(self._graph) if self._graph is not None else _report_payload(self._report, self._artifacts)
        if self._progress is not None:
            self._check_progress(self._progress)
            _progress_identities(payload, self._graph, self._progress)
        data = attach_presentation(data, payload)
        data["mode"] = selected
        data["progress"] = (
            self.progress_data(self._progress) if self._progress is not None else None
        )
        return data

    def progress_data(self, progress: ProgressSnapshot) -> dict:
        """Return a checked JSON-compatible update for ``element.updateProgress``.

        Updates carry graph identity, context identity, and revision. The viewer
        rejects mismatched graphs and ignores older revisions for the same run.
        A different run requires loading graph data again or resetProgress().
        Large context IDs are encoded as strings to preserve JavaScript accuracy.
        """
        from ...core.validation.graph import OperatorNode

        self._check_progress(progress)
        grouped = {}
        for step in progress.steps:
            grouped.setdefault(step.layout_position, []).append(step)
        nodes = []
        for node in self._report.nodes:
            if not isinstance(node, OperatorNode):
                continue
            steps = grouped.get(node.layout_position, [])
            states = {step.state.value for step in steps}
            state = next(
                (
                    s
                    for s in ("failed", "cancelled", "running", "placement_waiting")
                    if s in states
                ),
                None,
            )
            if state is None:
                state = (
                    ("skipped" if states == {"skipped"} else "completed")
                    if states and states <= {"completed", "skipped"}
                    else "pending"
                )
            nodes.append(
                {
                    "id": str(node.node_id),
                    "state": state,
                    "steps": [
                        {
                            "index": step.step_index,
                            "kind": step.step_kind,
                            "name": step.step_name,
                            "state": step.state.value,
                            "iteration": step.iteration,
                            "execution_count": step.execution_count,
                            "elapsed_seconds": step.elapsed_seconds,
                            "estimated_seconds": step.estimated_seconds,
                        }
                        for step in steps
                    ],
                    "elapsed_seconds": sum(step.elapsed_seconds for step in steps),
                }
            )
        return {
            "graph_id": self._structure["graph_id"],
            "context_id": str(progress.context_id),
            "revision": progress.revision,
            "observed_at": progress.observed_at.isoformat(),
            "state": progress.context_state.value,
            "iteration": progress.iteration,
            "max_iterations": progress.max_iterations,
            "elapsed_seconds": progress.elapsed_seconds,
            "estimated_fraction": progress.estimated_fraction,
            "estimated_remaining_seconds": progress.estimated_remaining_seconds,
            "confidence": progress.confidence,
            "sample_count": progress.sample_count,
            "completed_steps": progress.completed_steps,
            "total_steps": len(progress.steps),
            "nodes": nodes,
        }

    def to_html(
        self,
        *,
        mode: Literal["validation", "dashboard"] | None = None,
        embedded: bool = False,
    ) -> str:
        """Return self-contained HTML with node, port, and edge hover details.

        Args:
            mode: Validation/dashboard presentation; see build().
            embedded: Return an embeddable fragment instead of a full document.
                Each viewer uses Shadow DOM for isolated styles and controls.
                The fragment contains inline scripts; hosts using innerHTML must
                load viewer_script() once and assign build() to element.graph.
        """
        from ..renderer import _render_legacy_html

        return _render_legacy_html(self.build(mode=mode), embedded=embedded)

    @staticmethod
    def viewer_script() -> str:
        """Return the standalone script defining the reusable jayrun-graph element.

        Load it once in a dashboard, assign build() data to element.graph, then
        pass progress_data() payloads to element.updateProgress(). No framework,
        network request, polling loop, or third-party JavaScript is required.
        """
        from ..renderer import viewer_script

        return viewer_script()

    def save(
        self,
        path: str | Path | None = None,
        *,
        mode: Literal["validation", "dashboard"] | None = None,
    ) -> Path:
        """Save an offline HTML viewer and return its absolute path.

        mode selects validation or dashboard presentation; None is automatic.
        """
        output = Path(path or "graph_validation.html").expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(self.to_html(mode=mode), encoding="utf-8")
        return output

    def show(
        self,
        name: str = "graph_validation.html",
        notebook: bool = False,
        *,
        mode: Literal["validation", "dashboard"] | None = None,
    ) -> object | None:
        """Save and open the viewer, or return an IPython HTML iframe.

        Args:
            name: Output HTML path.
            notebook: Return an inline iframe; IPython is required only here.
            mode: Validation/dashboard presentation; None selects automatically.
        """
        output = self.save(name, mode=mode)
        if notebook:
            try:
                from IPython.display import HTML
            except ImportError as error:
                raise RuntimeError("IPython is required when notebook=True.") from error
            return HTML(
                '<iframe title="Jayrun graph" style="width:100%;height:850px;border:0" '
                f'srcdoc="{escape(output.read_text(encoding="utf-8"), quote=True)}"></iframe>'
            )
        webbrowser.open(output.as_uri())
        return None

    @cached_property
    def _structure(self) -> dict:
        from ...core.validation.graph import EntryNode, ExitNode, OperatorNode

        artifact_ids = {
            artifact: str(index) for index, artifact in enumerate(self._artifacts)
        }
        artifacts = [
            {
                "id": artifact_ids[a],
                "label": self._name(a),
                "color": self._artifact_color(i),
            }
            for i, a in enumerate(self._artifacts)
        ]
        colors = {a["id"]: a["color"] for a in artifacts}
        nodes = []
        for node in self._report.nodes:
            if not isinstance(node, (OperatorNode, EntryNode, ExitNode)):
                raise TypeError(f"Unsupported graph node: {type(node).__name__}")
            operator = isinstance(node, OperatorNode)
            nodes.append(
                {
                    "id": str(node.node_id),
                    "kind": node.node_type.value,
                    "label": node.label if operator else self._name(node.artifact),
                    "column": node.x_position,
                    "row": node.y_position,
                    "layout_position": list(node.layout_position) if operator else None,
                    "artifact_id": None if operator else artifact_ids[node.artifact],
                    "color": None if operator else colors[artifact_ids[node.artifact]],
                    "details": self._details(node),
                }
            )
        edges = [
            {
                "id": str(edge.edge_id),
                "source": str(edge.source),
                "target": str(edge.target),
                "artifact_id": artifact_ids[edge.artifact],
                "label": self._name(edge.artifact),
                "color": colors[artifact_ids[edge.artifact]],
                "kind": edge.edge_type.value,
                "validation": (
                    edge.status.value if edge.status is not None else "unavailable"
                ),
                "details": self._details(edge),
            }
            for edge in self._report.edges
        ]
        data = {
            "schema_version": 1,
            "graph_version": self._graph.version if self._graph is not None else None,
            "nodes": nodes,
            "edges": edges,
            "artifacts": artifacts,
        }
        data["graph_id"] = hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()
        return data

    @staticmethod
    def _name(value: object) -> str:
        return str(
            getattr(value, "display_name", None)
            or getattr(value, "name", None)
            or type(value).__name__
        )

    @staticmethod
    def _details(value: object) -> str:
        return repr(value).replace("\r\n", "\n").replace("\r", "\n")

    @classmethod
    def _artifact_color(cls, index: int) -> str:
        if index < len(cls._PALETTE):
            return cls._PALETTE[index]
        rgb = colorsys.hls_to_rgb((0.57 + index * 0.618033988749895) % 1, 0.68, 0.65)
        return "#{:02X}{:02X}{:02X}".format(*(round(c * 255) for c in rgb))

    def _check_progress(self, progress: ProgressSnapshot) -> None:
        from ...engine.progress import ProgressSnapshot

        if not isinstance(progress, ProgressSnapshot):
            raise TypeError("progress must be a ProgressSnapshot instance")
        self._validate_progress(progress)

    def _validate_progress(self, progress: ProgressSnapshot) -> None:
        from ...core.validation.graph import OperatorNode

        graph = self._graph
        if graph is None:
            known_positions = {
                node.layout_position
                for node in self._report.nodes
                if isinstance(node, OperatorNode)
            }
            if any(
                step.layout_position not in known_positions for step in progress.steps
            ):
                raise ValueError("progress does not match the plotted graph layout")
            return
        if progress.graph_version != graph.version:
            raise ValueError("progress graph version does not match the plotted graph")
        compiled_steps = graph._compiled_graph.steps
        if len(progress.steps) != len(compiled_steps):
            raise ValueError("progress does not match the plotted graph steps")
        for index, (value, compiled) in enumerate(
            zip(progress.steps, compiled_steps, strict=True)
        ):
            if isinstance(compiled, CompiledOperatorStep):
                kind, name = "operator", compiled.operator_name
            elif isinstance(compiled, CompiledResourceStep):
                kind, name = "resource", compiled.resource_name
            else:
                raise TypeError("compiled graph contains an unsupported step")
            if (
                value.step_index != index
                or value.step_kind != kind
                or value.step_name != name
                or value.layout_position != compiled.layout_position
            ):
                raise ValueError("progress does not match the plotted graph steps")
