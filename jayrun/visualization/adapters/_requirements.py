"""Requirement evidence for a captured registry; uses only the core resolver."""
from __future__ import annotations

from collections.abc import Sequence

from ...core.graph.requirements import RequirementConflictError, merge_requirements, requirement_key


_COVERAGE = (
    "Direct declarations only, including declared operator/resource/serializer requirements. "
    "No package index, transitive dependency resolution, installed-version or platform check.",
    "The core resolver groups by normalized package name and identical marker text. "
    "Overlapping but differently written markers are not combined or evaluated for a target environment.",
    "Combined conflicts mean the included graphs cannot share the reported constraint group. "
    "They do not make each graph individually invalid. Contributors identify the group, not a minimal unsatisfiable set.",
    "Ordinary Jayrun construction/registration rejects individually inconsistent declarations. "
    "This view does not register graphs, install packages or change requirements.",
)


def requirement_evidence(rows: Sequence[tuple[str, tuple[str, ...]]]) -> dict:
    """Evaluate one immutable list of presentation graph IDs and declarations.

    Grouped all-graph checks also detect multi-way conflicts that pairwise-only
    comparisons can miss. Invalid input remains distinct from a combined clash.
    Unexpected resolver failures propagate; none are converted into compatibility.
    """
    graphs: list[dict] = []
    groups: dict[tuple[str, str | None], list[dict[str, str]]] = {}
    for graph_id, declarations in rows:
        row = {"graph_id": graph_id, "declarations": list(declarations), "status": "consistent"}
        try:
            merge_requirements(declarations)
        except (TypeError, ValueError) as failure:
            row.update(status="invalid", error=str(failure))
        else:
            for declaration in declarations:
                groups.setdefault(requirement_key(declaration), []).append(
                    {"graph_id": graph_id, "requirement": declaration})
        graphs.append(row)
    conflicts = []
    combined = []
    for (name, marker), contributors in groups.items():
        try:
            merged = merge_requirements(item["requirement"] for item in contributors)
        except RequirementConflictError as failure:
            conflicts.append({"name": name, "marker": marker,
                "contributors": contributors, "message": str(failure)})
        else:
            combined.extend(str(item) for item in merged)
    invalid = any(row["status"] != "consistent" for row in graphs)
    return {"source": "Jayrun core declaration resolver", "graphs": graphs,
        "combined": {"status": "unavailable" if invalid else "conflict" if conflicts else "consistent",
            "constraints": combined, "conflicts": conflicts}, "coverage": list(_COVERAGE)}
