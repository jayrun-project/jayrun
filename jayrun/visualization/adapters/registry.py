"""Coherent append-only registry snapshots using public registry lookup semantics."""
from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from .._facade import Plot
from ..contract import MAX_GRAPHS, SCHEMA_VERSION, validate_payload
from .definition import definition_payload
from ._requirements import requirement_evidence

if TYPE_CHECKING:
    from ...core.graph.graph_registry import GraphRegistry


def registry_payload(registry: GraphRegistry) -> dict:
    from ...core.graph.graph_registry import GraphRegistry
    if not isinstance(registry, GraphRegistry):
        raise TypeError("registry must be a GraphRegistry")
    # identities returns a lock-protected tuple. Registrations are immutable and
    # append-only, so subsequent public lookups recover precisely that snapshot,
    # even if a new registration occurs during conversion. No private lock/store.
    identities = registry.identities
    if len(identities) > MAX_GRAPHS:
        raise ValueError(f"registry contains {len(identities)} graphs; explicit export limit is {MAX_GRAPHS}. Nothing exported or silently omitted.")
    graphs = []
    requirements = []
    for key, version in identities:
        definition = registry.graph_for(key, version)
        graph = definition_payload(definition)
        graph["label"] = f"{key} · v{version}"
        graph["identity"].update({"Registry key": key, "Registry version": version})
        graph["id"] = "registered-" + hashlib.sha256(json.dumps([key, version, graph["id"]], ensure_ascii=True).encode()).hexdigest()[:24]
        graphs.append(graph)
        requirements.append((graph["id"], tuple(str(item) for item in definition.inspect.requirements.all)))
    identity = hashlib.sha256(json.dumps([g["id"] for g in graphs]).encode()).hexdigest()[:24]
    return validate_payload({"schema_version": SCHEMA_VERSION, "kind": "registry", "id": "registry-view-" + identity,
                             "label": "Graph registry", "graphs": graphs,
                             "requirements": requirement_evidence(requirements),
                             "selected_graph": graphs[0]["id"] if graphs else None,
                             "identity": {"Scope": "Presentation snapshot; not a runtime registry identity"},
                             "details": {"Included graphs": len(graphs), "Omitted graphs": 0,
                                         "Refresh": "Every show/save captures a new snapshot. Existing HTML does not monitor later registrations.",
                                         "Selection": "Each graph retains its own topology, bindings, validation, and eligible re-iteration mappings."}})


def registry_plot(registry: GraphRegistry) -> Plot:
    return Plot(lambda: registry_payload(registry))
