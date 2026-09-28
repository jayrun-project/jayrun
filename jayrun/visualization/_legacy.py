"""Private bridge for the existing version-1 build/embedding dictionary.

This is a plotting compatibility format, not framework snapshot serialization.
Neither conversion imports Jayrun core types, the engine, or any adapters.
"""
from __future__ import annotations

from copy import deepcopy
from .contract import SCHEMA_VERSION, validate_payload
from .layout import arrange


def attach_presentation(legacy: dict, payload: dict) -> dict:
    """Add the current layout and verified fields to the old public build shape."""
    data, graph = deepcopy(legacy), arrange(payload)
    nodes = {node["id"]: node for node in graph["nodes"]}
    edges = {edge["id"]: edge for edge in graph["edges"]}
    artifact_ids = {artifact["id"]: str(index) for index, artifact in enumerate(graph["artifacts"])}
    for index, artifact in enumerate(data["artifacts"]):
        for key in ("details", "segments", "identity", "description"):
            if key in graph["artifacts"][index]:
                artifact[key] = deepcopy(graph["artifacts"][index][key])
    for node in data["nodes"]:
        source = nodes[f"node-{node['id']}"]
        for key in ("x", "y", "width", "height", "label", "label_lines", "description", "description_lines", "port_top", "progress_y", "resources", "identity"):
            if key in source:
                node[key] = deepcopy(source[key])
        node["inspection"] = deepcopy(source.get("details", {}))
        for side in ("inputs", "outputs"):
            node[side] = deepcopy(source[side])
            for port in node[side]:
                aid = port.get("artifact_id")
                port["artifact_id"] = artifact_ids.get(aid)
                port["color"] = next((a["color"] for a in data["artifacts"] if a["id"] == port["artifact_id"]), None)
                connections = [e for e in graph["edges"] if e["target" if side == "inputs" else "source"]["port"] == port["id"]]
                # Compatibility field only: actual branching still uses ONE
                # port. edge_ids exposes all branches without duplicating it.
                port["edge_ids"] = [e["id"].removeprefix("edge-") for e in connections]
                port["edge_id"] = port["edge_ids"][0] if port["edge_ids"] else None
    for edge in data["edges"]:
        source = edges[f"edge-{edge['id']}"]
        for key in ("points", "label_position", "segment", "identity", "description"):
            if key in source:
                edge[key] = deepcopy(source[key])
        edge["start"], edge["end"] = deepcopy(source["points"][0]), deepcopy(source["points"][-1])
        edge["source_port_id"], edge["target_port_id"] = source["source"]["port"], source["target"]["port"]
        edge["inspection"] = deepcopy(source.get("details", {}))
    for key in ("label", "description", "identity", "details", "reiterations", "reiteration", "findings", "bounds"):
        if key in graph:
            data[key] = deepcopy(graph[key])
    data["presentation_id"] = graph["id"]
    for finding in data.get("findings", []):
        if finding["subject"] == graph["id"]:
            finding["subject"] = data["graph_id"]
    return data


def normalize_legacy(data: dict) -> dict:
    """Validate an existing build dictionary as the current portable graph.

    Archived pre-extraction data has edge-associated ports only. Preserve those
    supplied endpoints; missing declaration/field evidence is never inferred from
    names or coordinates. New builds supply the actual source/target port IDs.
    """
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Expected legacy viewer schema_version 1")
    if data.get("mode") not in ("validation", "dashboard"):
        raise ValueError("mode must be validation or dashboard")
    artifacts = [dict(deepcopy(a), id=f"artifact-{a['id']}") for a in data["artifacts"]]
    nodes, port_map = [], {}
    for item in data["nodes"]:
        node = deepcopy(item)
        node["id"] = f"node-{item['id']}"
        # Boundary identity must use the same namespace as its ports and paths.
        # Zero is a real legacy artifact ID; absent metadata remains absent.
        if node.get("artifact_id") is not None:
            node["artifact_id"] = f"artifact-{node['artifact_id']}"
        node["details"] = node.pop("inspection", {"Structure": node.get("details", "")})
        node.setdefault("resources", [])
        node.setdefault("identity", {"Validation node": item["id"], "Layout position": item.get("layout_position")})
        for side in ("inputs", "outputs"):
            for index, port in enumerate(node[side]):
                port.setdefault("id", f"{node['id']}/{side}/{index}")
                port["artifact_id"] = f"artifact-{port['artifact_id']}" if port.get("artifact_id") is not None else None
                if port.get("edge_id") is not None:
                    port_map[(item["id"], side, port["edge_id"])] = port["id"]
        nodes.append(node)
    edges = []
    for item in data["edges"]:
        edge = deepcopy(item)
        edge.update(id=f"edge-{item['id']}", artifact_id=f"artifact-{item['artifact_id']}",
                    source={"node": f"node-{item['source']}", "port": item.get("source_port_id") or port_map[(item["source"], "outputs", item["id"])]},
                    target={"node": f"node-{item['target']}", "port": item.get("target_port_id") or port_map[(item["target"], "inputs", item["id"])]},
                    status=item["validation"] if item.get("validation") in {"match", "mismatch", "unknown"} else "unchecked")
        edge["details"] = edge.pop("inspection", {"Structure": item.get("details", "")})
        edges.append(edge)
    graph = {"schema_version": SCHEMA_VERSION, "kind": "graph", "id": data["graph_id"], "graph_id": data["graph_id"],
             "label": data.get("label", "Graph definition"), "description": data.get("description", ""),
             "nodes": nodes, "edges": edges, "artifacts": artifacts,
             "reiterations": deepcopy(data.get("reiterations", [])), "reiteration": deepcopy(data.get("reiteration", {"eligibility": "unknown", "reason": "Legacy data does not supply re-iteration eligibility."})),
             "findings": deepcopy(data.get("findings", [])), "details": deepcopy(data.get("details", {})), "identity": deepcopy(data.get("identity", {}))}
    graph["identity"].setdefault("Graph version", data.get("graph_version"))
    return validate_payload(graph)
