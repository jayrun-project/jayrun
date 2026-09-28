"""Attribution of retained legacy display data to its exact stored declaration.

No live graph, application module, registry, or timing profile is consulted.
Invalid execution correspondence never makes an otherwise valid layout vanish.
"""
from __future__ import annotations

from copy import deepcopy

from ..contract import validate_payload


def validate_bindings(payload: dict, bindings: dict) -> None:
    """Validate the old explicit step/connection map against the stored ports."""
    if payload.get("kind") != "graph" or "completed" in payload or "progress" in payload:
        raise ValueError("legacy layout must contain only a graph declaration")
    if type(bindings) is not dict or set(bindings) != {"steps", "connections"}:
        raise ValueError("invalid legacy declaration correspondence")
    steps, connections = bindings["steps"], bindings["connections"]
    if type(steps) is not dict or type(connections) is not list:
        raise ValueError("invalid legacy step/connection maps")
    subjects = {}
    for node in payload["nodes"]:
        position = node["identity"].get("Core layout position", [])
        subjects[node["id"]] = (node["kind"], position)
        for resource in node["resources"]:
            subjects[resource["id"]] = ("resource", position)
    for index, target in steps.items():
        if (type(index) is not str or not index.isdecimal() or len(index) > 8
                or str(int(index)) != index or type(target) is not dict
                or not {"id", "kind", "name", "layout_position"} <= target.keys()
                or target["kind"] not in ("operator", "resource")
                or type(target["name"]) is not str or type(target["layout_position"]) is not list
                or any(type(i) is not int or i < 0 for i in target["layout_position"])
                or subjects.get(target["id"]) != (target["kind"], target["layout_position"])):
            raise ValueError("legacy step does not identify its exact layout occurrence")
    edges = {edge["id"]: edge for edge in payload["edges"]}
    nodes = {node["id"]: node for node in payload["nodes"]}
    seen = set()
    for row in connections:
        if (type(row) is not dict or not {"id", "artifact_id", "verified_output", "producer_step", "consumer_step"} <= row.keys()
                or type(row["id"]) is not str or row["id"] in seen or row["id"] not in edges
                or row["artifact_id"] != edges[row["id"]]["artifact_id"] or type(row["verified_output"]) is not bool):
            raise ValueError("invalid legacy connection correspondence")
        seen.add(row["id"])
        edge = edges[row["id"]]
        for field, side in (("producer_step", "source"), ("consumer_step", "target")):
            index = row[field]
            if index is not None:
                if type(index) is not int or str(index) not in steps:
                    raise ValueError("unknown legacy connection step")
                target = steps[str(index)]
                if target["kind"] != "operator" or target["id"] != edge[side]["node"]:
                    raise ValueError("legacy connection references a different operator")
        if row["verified_output"] and (row["producer_step"] is None or not any(
                port["id"] == edge["source"]["port"] and port.get("artifact_id") == row["artifact_id"]
                for port in nodes[edge["source"]["node"]]["outputs"])):
            raise ValueError("legacy output does not identify the actual artifact port")


def legacy_payload(payload: dict, source: dict, bindings: dict | None, outcome: str) -> dict:
    """Overlay only original validated evidence; retain missing coverage explicitly."""
    payload["details"]["Legacy history"] = {
        "Coverage": "Imported display-oriented archive; no resolved-configuration or full-execution completeness is inferred",
        "Intrinsic graph identity": "Unavailable; the original viewer identifier is not a graph fingerprint",
    }
    completed = source.get("completed_evidence") if type(source) is dict else None
    if completed is None:
        payload["details"]["Completed overlay"] = "Not retained in the legacy archive"
        return validate_payload(payload)
    try:
        validate_bindings(payload, bindings)
        if (type(completed) is not dict or source.get("finalized") is not True
                or str(completed.get("context_id")) != str(source.get("context_id"))
                or completed.get("outcome") != outcome):
            raise ValueError("legacy completed evidence belongs to another context/outcome")
        candidate = deepcopy(payload)
        subjects = {subject["id"]: subject for node in candidate["nodes"] for subject in (node, *node["resources"])}
        for subject in subjects.values():
            subject["execution_steps"] = []
        for session in completed["executions"]:
            target = bindings["steps"].get(str(session["step_index"]))
            if target is None or any(session[key] != target[key] for key in ("kind", "name", "layout_position")):
                raise ValueError("legacy execution disagrees with the captured step")
            indices = subjects[target["id"]]["execution_steps"]
            if session["step_index"] not in indices:
                indices.append(session["step_index"])
        connections = {edge["id"]: edge for edge in bindings["connections"]}
        for connection in completed["connections"]:
            target = connections.get(connection["id"])
            if target is None or any(connection[key] != target[key] for key in ("artifact_id", "producer_step", "consumer_step")):
                raise ValueError("legacy execution connection disagrees with its port map")
            if not target["verified_output"] and connection.get("producer_history_indices"):
                raise ValueError("legacy output lifecycle correspondence was not verified")
        candidate["completed"] = deepcopy(completed)
        for edge in candidate["edges"]:
            edge["completed_connection"] = edge["id"]
        candidate["details"]["Execution coverage"] = completed["coverage"]
        return validate_payload(candidate)
    except (TypeError, KeyError, ValueError, OverflowError):
        payload["details"]["Completed overlay"] = "Unavailable: legacy execution identity or schema cannot be attributed safely"
        return validate_payload(payload)
