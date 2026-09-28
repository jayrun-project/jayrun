"""Connected path segments, computed only from explicit artifact endpoints."""
from __future__ import annotations


def annotate_segments(graph: dict, *, provenance: str, lifecycle: bool = False) -> None:
    """Annotate disjoint segments without connecting them or changing identity.

    A shared artifact at both sides of an occurrence connects its paths, not its
    runtime values. Numbering follows the supplied edge order, never coordinates.
    Only the Jayrun adapter calls these availability/lifecycle segments; portable
    callers get structural path segments unless they supply stronger evidence.
    """
    for artifact in graph["artifacts"]:
        edges = [edge for edge in graph["edges"] if edge["artifact_id"] == artifact["id"]]
        parents: dict[str, str] = {}

        def find(node: str) -> str:
            parents.setdefault(node, node)
            while parents[node] != node:
                parents[node] = parents[parents[node]]
                node = parents[node]
            return node

        for edge in edges:
            a, b = find(edge["source"]["node"]), find(edge["target"]["node"])
            parents[b] = a
        groups: dict[str, list[dict]] = {}
        for edge in edges:
            groups.setdefault(find(edge["source"]["node"]), []).append(edge)
        segments = []
        for index, group in enumerate(groups.values(), 1):
            segment_id = f"{artifact['id']}/segment/{index}"
            segments.append({"id": segment_id, "index": index, "edges": [e["id"] for e in group]})
            for edge in group:
                edge["segment"] = {"id": segment_id, "index": index, "count": len(groups)}
        if len(groups) > 1:
            artifact.setdefault("description", f"{len(groups)} separate {'lifecycle' if lifecycle else 'path'} segments. Matching colors identify the artifact; they do not connect the gaps or establish the same runtime value.")
            artifact.setdefault("details", {})["Lifecycle segments" if lifecycle else "Path segments"] = {
                "Count": len(groups),
                "Meaning": "Separate availability segments of the same artifact declaration. The value is consumed and unavailable until an operator produces it again; no connection spans the gap." if lifecycle else "Separate connected path components for this explicit artifact identity. No continuity across the gaps is asserted.",
                "Value identity": "The same color denotes the artifact declaration, not an unchanged runtime value.",
                "Provenance": provenance,
            }
        artifact["segments"] = segments
