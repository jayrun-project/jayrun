"""Render one exact stored layout and its retained evidence, without live graphs."""
from __future__ import annotations

from ...persistence.records import ContextHistoryEntry
from ...reporting._history import history_evidence
from ..contract import validate_payload


def history_payload(entry: ContextHistoryEntry, *, evidence: dict | None = None) -> dict:
    """Return the existing portable payload, never a reconstructed executable graph.

    Missing/unsupported layouts raise ValueError. A known layout remains visible
    when its execution evidence is incomplete; coverage is attached explicitly.
    ``evidence`` is the private normalized presentation cache used by consumers.
    """
    if type(entry) is not ContextHistoryEntry:
        raise TypeError("entry must be a ContextHistoryEntry")
    if entry.layout is None or not entry.layout.available:
        raise ValueError(entry.layout_unavailable_reason or "stored layout unavailable")
    payload = entry.layout.payload()
    # The retained header owns correlation identity, including its absence.
    payload["identity"]["Intrinsic graph ID"] = entry.header.graph_id
    payload["identity"]["Engine session"] = entry.header.session_id
    payload["identity"]["Context"] = entry.header.context_id
    payload["details"]["Stored execution"] = {"Context": entry.header.context_id,
        "Engine session": entry.header.session_id, "Intrinsic graph ID": entry.header.graph_id,
        "Coverage": list(entry.coverage), "Authority": "Historical evidence is read-only"}
    raw = entry.evidence.decode()
    if type(raw) is dict and raw.get("schema") == "jayrun.legacy-dashboard/1":
        from ._legacy_history import legacy_payload
        return legacy_payload(payload, raw.get("source"), raw.get("bindings"), entry.header.outcome)
    if evidence is None:
        evidence = history_evidence(entry)
    if evidence is None:
        payload["details"]["Execution evidence"] = "Unavailable or unsupported stored report; no execution inferred"
        return payload
    if evidence["context_id"] != entry.header.context_id:
        raise ValueError("historical evidence belongs to another context")
    subjects = {}
    for node in payload["nodes"]:
        position = tuple(node["identity"].get("Core layout position", ()))
        for subject in (node, *node["resources"]):
            subjects[position, subject["id"]] = subject
    targets = {}
    operators = {}
    for item in evidence["step_correspondence"]:
        if type(item) not in (tuple, list) or len(item) != 5:
            raise ValueError("invalid stored step correspondence")
        index, kind, name, position, ident = item
        if type(index) is not int or index < 0 or index in targets or kind not in ("operator", "resource"):
            raise ValueError("invalid stored step identity")
        subject = subjects.get((tuple(position), ident))
        if subject is None or index not in subject.get("execution_steps", ()):
            raise ValueError("stored step does not belong to its exact layout subject")
        if kind == "operator" and subject.get("kind") != "operator":
            raise ValueError("stored operator step targets another kind")
        if kind == "resource" and subject.get("kind") is not None:
            raise ValueError("stored resource step targets an operator")
        targets[index] = (kind, name, list(position), subject)
        subject["identity"].setdefault("Execution steps", []).append({"index": index, "kind": kind, "name": name})
        if kind == "operator":
            operators[ident] = index
    used = set()
    for session in evidence["executions"]:
        target = targets.get(session["step_index"])
        if target is None or (session["kind"], session["name"], session["layout_position"]) != target[:3]:
            raise ValueError("stored execution disagrees with its captured step")
        used.add(session["step_index"])
        subject = target[3]
        subject["details"].setdefault("Retained step sessions", []).append(session)
        if session["outcome"] == "failed":
            payload["findings"].append({"id": "history-failure-"+session["id"], "subject": subject["id"],
                "severity": "error", "message": f'{session["kind"].title()} failed in iteration {session["iteration"]}; see retained attempts'})
    histories = {value["id"]: value for value in evidence["artifacts"]}
    connections = []
    nodes = {node["id"]: node for node in payload["nodes"]}
    for edge in payload["edges"]:
        artifact = histories.get(edge["artifact_id"])
        if artifact is None:
            continue
        producer = operators.get(edge["source"]["node"])
        consumer = operators.get(edge["target"]["node"])
        verified = any(port["id"] == edge["source"]["port"] and port.get("artifact_id") == edge["artifact_id"]
                       for port in nodes[edge["source"]["node"]]["outputs"])
        connections.append({"id": edge["id"], "artifact_id": edge["artifact_id"],
            "producer_step": producer, "consumer_step": consumer,
            "producer_history_indices": [row["retained_index"] for row in artifact["history"]
                if producer is not None and verified and row.get("actor") == "operator" and row.get("step_index") == producer],
            "consumer_sessions": [session["id"] for session in evidence["executions"]
                                  if consumer is not None and session["step_index"] == consumer],
            "coverage": "Explicit stored port/artifact/step references only; no discrete-segment continuity inferred"})
    # The old producer omitted completed_iterations. Do not invent a value to
    # satisfy the portable completed contract; exact step findings still render.
    if evidence["completed_iterations"] is not None:
        completed = {key: value for key, value in evidence.items() if key != "step_correspondence"}
        completed["connections"] = connections
        payload["completed"] = completed
        for subject in subjects.values():
            subject["execution_steps"] = [index for index in subject.get("execution_steps", ()) if index in used]
        for edge in payload["edges"]:
            edge["completed_connection"] = edge["id"]
    else:
        payload["details"]["Completed overlay"] = "Exact completed-iteration count was not captured; retained step details/findings are shown instead"
    payload["details"]["Execution coverage"] = evidence["coverage"]
    return validate_payload(payload)
