"""Checked JSON viewer data, deliberately separate from framework serialization."""
from __future__ import annotations

import json
import math
import re

SCHEMA_VERSION = "jayrun.viewer/1"
MAX_GRAPHS = 1000
MAX_NODES = 10000
MAX_CONNECTIONS = 50000
MAX_EXPORT_BYTES = 32 * 1024 * 1024
_STATUSES = {"match", "mismatch", "unknown", "unchecked"}
_SENSITIVE = re.compile(r"password|secret|credential|authorization|access.?token|api.?key|private.?key", re.I)


def summarize(value: object, *, _depth: int = 0, _seen: set[int] | None = None) -> object:
    """Bound metadata without executing user repr/property/iteration methods.

    Only built-in containers/scalars and type names are formatted. Omission is
    explicit, credentials under recognized keys are redacted, and opaque values
    (including model/tensor/control objects) never enter an export.
    """
    if value is None or type(value) is bool:
        return value
    if type(value) is str:
        return value if len(value) <= 2048 else value[:2048] + " … [text omitted]"
    if type(value) is int:
        return value if abs(value) <= 9007199254740991 else str(value) + " [integer]"
    if type(value) is float:
        return value if math.isfinite(value) else "[non-finite number omitted]"
    if isinstance(value, type):
        return type.__getattribute__(value, "__module__") + "." + type.__getattribute__(value, "__qualname__")
    if _depth >= 6:
        return "[depth limit; detail omitted]"
    seen = set() if _seen is None else _seen
    if id(value) in seen:
        return "[cyclic reference omitted]"
    if type(value) not in (dict, list, tuple):
        return "[opaque " + type(value).__name__ + "; value omitted]"
    seen.add(id(value))
    try:
        if type(value) is dict:
            result = {}
            for i, (key, item) in enumerate(value.items()):
                if i >= 64:
                    result["[omitted]"] = f"{len(value) - 64} further fields"
                    break
                label = key[:256] if type(key) is str else "[non-string key omitted]"
                result[label] = "[redacted]" if _SENSITIVE.search(label) else summarize(item, _depth=_depth + 1, _seen=seen)
            return result
        result = [summarize(item, _depth=_depth + 1, _seen=seen) for item in value[:64]]
        if len(value) > 64:
            result.append(f"[{len(value) - 64} further items omitted]")
        return result
    finally:
        seen.remove(id(value))


def _mapping(value: object, at: str) -> dict:
    if type(value) is not dict:
        raise TypeError(f"{at} must be a JSON object")
    return value


def _text(value: object, at: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not value and not empty) or len(value) > 8192:
        raise ValueError(f"{at} must be a {'possibly empty ' if empty else 'nonempty '}string of at most 8192 characters")
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError(f"{at} must not contain unpaired Unicode surrogates")
    return value


def _items(value: object, at: str, limit: int) -> list:
    if type(value) is not list:
        raise TypeError(f"{at} must be an array")
    if len(value) > limit:
        raise ValueError(f"{at} exceeds the explicit limit of {limit}; nothing was omitted/exported")
    return value


def _json_copy(value: object, depth: int = 0, seen: set[int] | None = None, budget: list[int] | None = None) -> object:
    """Reject non-JSON structural values before copying or formatting."""
    if depth > 24:
        raise ValueError("payload exceeds the structural depth limit of 24")
    seen = set() if seen is None else seen
    budget = [1500000] if budget is None else budget
    budget[0] -= 1
    if budget[0] < 0:
        raise ValueError("payload exceeds the structural value limit")
    if value is None or type(value) in (str, bool, int):
        if type(value) is str and len(value) > MAX_EXPORT_BYTES:
            raise ValueError("payload text exceeds the export limit")
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) not in (list, dict):
        raise TypeError("payload must contain only finite JSON-compatible values")
    if id(value) in seen:
        raise ValueError("payload must not contain cycles")
    seen.add(id(value))
    try:
        if type(value) is list:
            return [_json_copy(item, depth + 1, seen, budget) for item in value]
        if any(type(key) is not str for key in value):
            raise TypeError("JSON object keys must be strings")
        return {key: _json_copy(item, depth + 1, seen, budget) for key, item in value.items()}
    finally:
        seen.remove(id(value))


def _metadata(record: dict) -> None:
    for key in ("details", "identity"):
        if key in record:
            record[key] = summarize(record[key])
    if "description" in record:
        _text(record["description"], "description", empty=True)


def _graph(graph: dict) -> dict:
    if graph.get("kind") != "graph":
        raise ValueError("included payloads must have kind='graph'")
    _text(graph.get("id"), "graph.id")
    _text(graph.get("label"), "graph.label")
    _metadata(graph)
    artifacts = {}
    for item in _items(graph.get("artifacts"), "artifacts", MAX_CONNECTIONS):
        _mapping(item, "artifact")
        aid = _text(item.get("id"), "artifact.id")
        if aid in artifacts:
            raise ValueError(f"duplicate artifact identity {aid!r}")
        _text(item.get("label"), "artifact.label")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", item.get("color", "")):
            raise ValueError("artifact.color must be a six-digit hexadecimal color")
        _metadata(item)
        artifacts[aid] = item
    identifiers: set[str] = {graph["id"]}
    def identity(record: dict) -> str:
        ident = _text(record.get("id"), "entity.id")
        if ident in identifiers:
            raise ValueError(f"duplicate presentation identity {ident!r}")
        identifiers.add(ident)
        _metadata(record)
        return ident
    nodes, ports = {}, {}
    for node in _items(graph.get("nodes"), "nodes", MAX_NODES):
        _mapping(node, "node")
        nid = identity(node)
        _text(node.get("label"), "node.label")
        if node.get("kind") not in {"operator", "entry", "exit"}:
            raise ValueError("nodes must be operators or explicit entry/exit boundaries; resources are markers")
        for coord in ("column", "row"):
            if coord in node and (type(node[coord]) is not int or not 0 <= node[coord] <= MAX_NODES):
                raise ValueError(f"node.{coord} must be a bounded nonnegative integer")
        nodes[nid] = node
        for side in ("inputs", "outputs"):
            for port in _items(node.get(side), f"node.{side}", MAX_CONNECTIONS):
                _mapping(port, "port")
                pid = identity(port)
                _text(port.get("label"), "port.label")
                if port.get("artifact_id") is not None and port["artifact_id"] not in artifacts:
                    raise ValueError("port references an unknown artifact")
                ports[pid] = (nid, side, port.get("artifact_id"))
        for marker in _items(node.get("resources", []), "node.resources", MAX_CONNECTIONS):
            if node["kind"] != "operator":
                raise ValueError("resource markers must be attached to consuming operators")
            _mapping(marker, "resource marker")
            identity(marker)
            _text(marker.get("label"), "resource.label")
            if marker.get("state") not in {"bound", "required-unbound", "optional-unbound", "unknown"}:
                raise ValueError("invalid resource binding state")
    def endpoint(value: object, side: str, artifact: str) -> None:
        value = _mapping(value, "connection endpoint")
        if value.get("node") not in nodes or value.get("port") not in ports:
            raise ValueError("connection endpoint references an unknown node or actual port")
        if ports[value["port"]] != (value["node"], side, artifact):
            raise ValueError("connection endpoint has the wrong owner, direction, or artifact")
    for key in ("edges", "reiterations"):
        for edge in _items(graph.get(key, []), key, MAX_CONNECTIONS):
            _mapping(edge, "connection")
            identity(edge)
            aid = edge.get("artifact_id")
            if aid not in artifacts:
                raise ValueError("connection references an unknown artifact")
            endpoint(edge.get("source"), "outputs", aid)
            endpoint(edge.get("target"), "inputs", aid)
            if edge.get("status", "unchecked") not in _STATUSES:
                raise ValueError("status must distinguish match, mismatch, unknown, and unchecked")
            edge.setdefault("status", "unchecked")
            _text(edge.get("label", artifacts[aid]["label"]), "edge.label")
            if key == "reiterations":
                _text(edge.get("provenance"), "reiteration.provenance")
                if nodes[edge["target"]["node"]]["kind"] != "operator":
                    raise ValueError("re-iteration must identify an actual destination input, not a synthetic entry loop")
    # Segment annotations are structural references, not new artifact edges.
    # When supplied, each ordinary connection belongs to exactly one declared
    # component for its own artifact. Re-iteration is deliberately separate.
    ordinary = {edge["id"]: edge for edge in graph.get("edges", [])}
    annotated = set()
    segment_ids = set()
    for aid, artifact in artifacts.items():
        if "segments" not in artifact:
            continue
        segments = _items(artifact["segments"], "artifact.segments", MAX_CONNECTIONS)
        owned = {eid for eid, edge in ordinary.items() if edge["artifact_id"] == aid}
        covered = set()
        for index, segment in enumerate(segments, 1):
            _mapping(segment, "artifact segment")
            sid = _text(segment.get("id"), "segment.id")
            if sid in segment_ids or type(segment.get("index")) is not int or segment["index"] != index:
                raise ValueError("segment identities and sequential indices must be unique")
            segment_ids.add(sid)
            members = _items(segment.get("edges"), "segment.edges", MAX_CONNECTIONS)
            if not members:
                raise ValueError("a segment must contain at least one ordinary connection")
            expected = {"id": sid, "index": index, "count": len(segments)}
            for eid in members:
                _text(eid, "segment edge reference")
                if eid not in owned or eid in covered:
                    raise ValueError("segment references an unknown, repeated, or different artifact connection")
                if ordinary[eid].get("segment") != expected:
                    raise ValueError("connection segment annotation disagrees with its artifact")
                covered.add(eid)
        if covered != owned:
            raise ValueError("artifact segments must cover every ordinary connection exactly once")
        annotated.update(covered)
    if any("segment" in edge and eid not in annotated for eid, edge in ordinary.items()):
        raise ValueError("connection segment annotation requires matching artifact segments")
    reiteration = _mapping(graph.get("reiteration", {"eligibility": "unknown", "reason": "No eligibility evidence supplied."}), "reiteration")
    if reiteration.get("eligibility") not in {"known", "unknown"}:
        raise ValueError("reiteration eligibility must be known or unknown")
    if graph.get("reiterations") and reiteration["eligibility"] != "known":
        raise ValueError("explicit re-iteration mappings require known eligibility and provenance")
    graph["reiteration"] = reiteration
    subjects = frozenset(identifiers)
    for finding in _items(graph.get("findings", []), "findings", MAX_CONNECTIONS):
        _mapping(finding, "finding")
        identity(finding)
        if finding.get("subject") not in subjects:
            raise ValueError("finding references an unknown entity")
        _text(finding.get("message"), "finding.message")
        if finding.get("severity") not in {"error", "warning", "info"}:
            raise ValueError("finding.severity must be error, warning, or info")
    graph.setdefault("edges", [])
    graph.setdefault("reiterations", [])
    graph.setdefault("findings", [])
    if 'completed' in graph:
        _completed(graph)
    return graph


def _completed(graph: dict) -> None:
    evidence = _mapping(graph['completed'], 'completed')
    if evidence.get('outcome') not in {'finished', 'stopped', 'failed', 'aborted', 'rejected'}:
        raise ValueError('completed outcome must be a supported terminal state')
    _text(evidence.get('context_id'), 'completed.context_id')
    for name in ('iteration_count', 'completed_iterations'):
        value = evidence.get(name)
        if type(value) is not int or not 0 <= value <= 50000:
            raise ValueError('completed iteration counts must be bounded nonnegative integers')
    if evidence['completed_iterations'] > evidence['iteration_count']:
        raise ValueError('completed iterations exceed started iterations')
    _mapping(evidence.get('coverage'), 'completed.coverage')
    steps = set()
    sessions = set()
    for session in _items(evidence.get('executions'), 'completed.executions', 50000):
        _mapping(session, 'completed session')
        sid = _text(session.get('id'), 'session.id')
        if sid in sessions:
            raise ValueError('duplicate completed session identity')
        sessions.add(sid)
        index = session.get('step_index')
        if type(index) is not int or index < 0:
            raise ValueError('invalid completed step index')
        steps.add(index)
        if session.get('kind') not in {'operator','resource'} or session.get('outcome') not in {'finished','failed','cancelled','skipped'}:
            raise ValueError('invalid completed session kind/outcome')
        duration = session.get('active_seconds')
        if type(duration) not in (int,float) or not math.isfinite(duration) or duration < 0:
            raise ValueError('invalid active duration')
        iteration = session.get('iteration')
        if type(iteration) is not int or not 1 <= iteration <= evidence['iteration_count']:
            raise ValueError('session iteration is outside finalized run')
        attempts = set()
        for attempt in _items(session.get('attempts'), 'session.attempts', 50000):
            _mapping(attempt, 'session attempt')
            identity = (attempt.get('execution'), attempt.get('attempt'))
            if any(type(value) is not int or value < 1 for value in identity) or identity in attempts:
                raise ValueError('invalid or duplicate execution/attempt identity')
            attempts.add(identity)
            for record in _items(attempt.get('records'), 'attempt.records', 50000):
                _mapping(record, 'attempt record')
    for name in ('records','artifacts','history'):
        _items(evidence.get(name), 'completed.'+name, 50000)
    artifact_histories = {}
    for artifact in evidence['artifacts']:
        _mapping(artifact, 'completed artifact')
        aid = _text(artifact.get('id'), 'completed artifact.id')
        indices = set()
        for record in _items(artifact.get('history'), 'artifact.history', 50000):
            _mapping(record, 'artifact history entry')
            index = record.get('retained_index')
            if type(index) is not int or index < 1 or index in indices:
                raise ValueError('invalid artifact retained index')
            indices.add(index)
        if aid in artifact_histories:
            raise ValueError('duplicate completed artifact identity')
        artifact_histories[aid] = indices
    edge_ids = {edge['id']: edge['artifact_id'] for edge in graph['edges']}
    connection_ids = set()
    for connection in _items(evidence.get('connections', []), 'completed.connections', 50000):
        _mapping(connection, 'completed connection')
        cid, aid = connection.get('id'), connection.get('artifact_id')
        if type(cid) is not str or cid in connection_ids or edge_ids.get(cid) != aid or aid not in artifact_histories:
            raise ValueError('completed connection identity disagrees with declaration')
        connection_ids.add(cid)
        for index in _items(connection.get('producer_history_indices'), 'connection history references', 50000):
            if type(index) is not int or index not in artifact_histories[aid]:
                raise ValueError('connection references unavailable artifact history')
        for sid in _items(connection.get('consumer_sessions'), 'connection consumer sessions', 50000):
            if type(sid) is not str or sid not in sessions:
                raise ValueError('connection references unavailable consumer session')
    for node in graph['nodes']:
        for entity in (node, *node.get('resources', [])):
            for index in _items(entity.setdefault('execution_steps', []), 'execution_steps', 50000):
                if type(index) is not int or index not in steps:
                    raise ValueError('entity references unavailable execution step')


def _requirements(value: object, graph_ids: set[str]) -> None:
    data = _mapping(value, "requirements")
    _text(data.get("source"), "requirements.source")
    rows = {}
    for row in _items(data.get("graphs"), "requirements.graphs", MAX_GRAPHS):
        _mapping(row, "requirements.graph")
        ident = _text(row.get("graph_id"), "requirements.graph_id")
        if ident not in graph_ids or ident in rows:
            raise ValueError("requirement rows must refer to distinct included graphs")
        if row.get("status") not in {"consistent", "invalid", "unavailable"}:
            raise ValueError("invalid individual requirement status")
        declarations = _items(row.get("declarations"), "requirement declarations", MAX_CONNECTIONS)
        for declaration in declarations:
            _text(declaration, "requirement declaration")
        if "error" in row:
            _text(row["error"], "requirement error")
        rows[ident] = set(declarations)
    if set(rows) != graph_ids:
        raise ValueError("requirement rows must cover every included graph")
    combined = _mapping(data.get("combined"), "combined requirements")
    if combined.get("status") not in {"consistent", "conflict", "unavailable"}:
        raise ValueError("invalid combined requirement status")
    for text in _items(combined.get("constraints"), "combined constraints", MAX_CONNECTIONS):
        _text(text, "combined constraint")
    conflicts = _items(combined.get("conflicts"), "requirement conflicts", MAX_CONNECTIONS)
    if (combined["status"] == "consistent" and conflicts) or (combined["status"] == "conflict" and not conflicts):
        raise ValueError("combined status does not agree with supplied conflicts")
    if combined["status"] != "unavailable" and any(row["status"] != "consistent" for row in data["graphs"]):
        raise ValueError("individually invalid/unavailable requirements cannot establish combined compatibility")
    for conflict in conflicts:
        _mapping(conflict, "requirement conflict")
        _text(conflict.get("name"), "conflict package")
        if conflict.get("marker") is not None:
            _text(conflict["marker"], "conflict marker")
        _text(conflict.get("message"), "conflict message")
        contributors = _items(conflict.get("contributors"), "conflict contributors", MAX_CONNECTIONS)
        if not contributors:
            raise ValueError("a conflict needs attributable contributors")
        for item in contributors:
            _mapping(item, "conflict contributor")
            ident = _text(item.get("graph_id"), "contributor graph_id")
            declaration = _text(item.get("requirement"), "contributor requirement")
            if ident not in rows or declaration not in rows[ident]:
                raise ValueError("conflict contributor must reference a captured graph requirement")
    for text in _items(data.get("coverage"), "requirement coverage", 64):
        _text(text, "requirement coverage")


def validate_payload(payload: dict) -> dict:
    """Validate and detach one portable graph or a coherent registry snapshot.

    Oversized structures fail explicitly rather than dropping graphs or edges.
    Metadata is bounded/redacted; topology, port IDs, colors, and bindings are
    never inferred from names, layout, or matching numeric identities.
    """
    data = _mapping(_json_copy(payload), "payload")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION!r} (not a framework snapshot version)")
    if data.get("kind") == "graph":
        _graph(data)
    elif data.get("kind") == "registry":
        _text(data.get("id"), "registry.id")
        _text(data.get("label"), "registry.label")
        _metadata(data)
        ids = set()
        for graph in _items(data.get("graphs"), "registry.graphs", MAX_GRAPHS):
            _mapping(graph, "graph")
            if graph.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("every included graph needs the viewer schema version")
            _graph(graph)
            if graph["id"] in ids:
                raise ValueError("registry graph presentation IDs must be distinct")
            ids.add(graph["id"])
        data.setdefault("selected_graph", data["graphs"][0]["id"] if ids else None)
        if data["selected_graph"] not in ids and (ids or data["selected_graph"] is not None):
            raise ValueError("selected_graph does not belong to the registry snapshot")
        if "requirements" in data:
            _requirements(data["requirements"], ids)
    else:
        raise ValueError("payload.kind must be graph or registry")
    if len(json.dumps(data, ensure_ascii=True, allow_nan=False).encode()) > MAX_EXPORT_BYTES:
        raise ValueError(f"payload exceeds the explicit {MAX_EXPORT_BYTES}-byte export limit; nothing exported")
    return data
