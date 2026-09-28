"""Presentation of detached durable evidence; no runtime or application imports.

The P3/P4 envelope omitted completed_iterations and record class discriminants.
Those omissions remain explicit. P5-a captures the former additively; old records
are never reconstructed as executable reports or filled from current profiles.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import math
from uuid import UUID

from ..persistence.records import ContextHistoryEntry
from ..persistence.values import ValueMarker


def _display(value: object, *, depth: int = 0, budget: list[int] | None = None) -> object:
    """Bounded JSON display of decoded primitives, without application codecs."""
    if budget is None:
        budget = [65_536]
    budget[0] -= 1
    if budget[0] < 0 or depth > 20:
        return {"availability": "omitted", "reason": "historical display bound"}
    cls = type(value)
    if value is None or cls in (bool, str):
        if cls is str and len(value) > 8192:
            return {"availability": "omitted", "prefix": value[:8192], "reason": "display text bound"}
        return value
    if cls is int:
        return value if abs(value) <= 2**53 - 1 else str(value)
    if cls is float:
        return value if math.isfinite(value) else {"availability": "unsupported", "reason": "nonfinite float"}
    if cls in (datetime, date):
        return value.isoformat()
    if cls is timedelta:
        return {"type": "timedelta", "seconds": value.total_seconds()}
    if cls is UUID:
        return str(value)
    if cls is bytes:
        return {"type": "bytes", "length": len(value), "availability": "not displayed"}
    if cls is ValueMarker:
        result = {"availability": value.kind, "reason": value.reason}
        if value.codec is not None:
            result.update(codec=value.codec, version=value.version)
        return result
    if cls is dict:
        if all(type(key) is str for key in value):
            return {key: _display(child, depth=depth+1, budget=budget) for key, child in value.items()}
        return {"type": "mapping", "entries": [[_display(key, depth=depth+1, budget=budget),
            _display(child, depth=depth+1, budget=budget)] for key, child in value.items()]}
    if cls in (tuple, list, set, frozenset):
        return [_display(child, depth=depth+1, budget=budget) for child in value]
    return {"availability": "unsupported", "reason": "not a supported detached value"}


def _configuration(entry: ContextHistoryEntry) -> list[dict]:
    raw = entry.configurations.decode()
    if type(raw) is not dict:
        return [{"id": "unavailable", "owner": "Unavailable", "effective": _display(raw),
                 "provenance": "Stored diagnostic configuration is unavailable"}]
    result = []
    for key, item in raw.items():
        if type(item) is not dict:
            result.append({"id": str(key), "owner": "Unavailable", "effective": _display(item)})
            continue
        result.append({"id": str(key), "name": item.get("name"), "owner": item.get("owner"),
            "position": _display(item.get("layout_position")), "effective": _display(item.get("value")),
            "provenance": "Resolved configuration detached before execution; explicit storage redaction applies"})
    return result


def history_evidence(entry: ContextHistoryEntry) -> dict | None:
    """Normalize the supported captured report, without needing a graph/layout.

    None means the stored report format/coverage is unavailable, not a successful
    empty execution. Graph correspondence is validated by the layout adapter.
    """
    if type(entry) is not ContextHistoryEntry:
        raise TypeError("entry must be a ContextHistoryEntry")
    raw = entry.evidence.decode()
    if type(raw) is not dict or raw.get("schema") != "jayrun.execution-history/1":
        return None
    report = raw.get("report")
    provenance = entry.provenance.decode()
    if type(report) is not dict or type(provenance) is not dict:
        return None
    if report.get("state") != entry.header.outcome:
        raise ValueError("stored report outcome disagrees with its header")
    if str(report.get("context_id")) != str(provenance.get("runtime_context_id")):
        raise ValueError("stored report context disagrees with its provenance")
    progress = raw.get("progress")
    progress_valid = (type(progress) is dict
        and progress.get("context_id") == report.get("context_id")
        and progress.get("context_state") == entry.header.outcome)
    if not progress_valid:
        progress = {}
    completed = raw.get("completed_iterations")
    iterations = report.get("iteration_count")
    if type(iterations) is not int or iterations < 0:
        raise ValueError("invalid stored iteration count")
    if completed is not None and (type(completed) is not int or not 0 <= completed <= iterations):
        raise ValueError("invalid stored completed iteration count")
    executions = []
    for index, session in enumerate(report.get("executions", ())):
        if type(session) is not dict or session.get("context_id") != report["context_id"]:
            raise ValueError("execution belongs to another stored context")
        attempts = []
        for attempt in session["attempts"]:
            records = [{"type": "Captured record (original class not recorded)", **_display(record)}
                       for record in attempt["records"]]
            attempts.append({"execution": attempt["execution"], "attempt": attempt["attempt"], "records": records})
        executions.append({"id": f"session-{index}", "step_index": session["step_index"],
            "kind": session["step_kind"], "name": session["step_name"],
            "layout_position": list(session["layout_position"]), "iteration": session["iteration"],
            "outcome": session["outcome"], "skip_reason": _display(session["skip_reason"]),
            "active_seconds": session["duration_seconds"], "execution_count": session["execution_count"],
            "attempts": attempts})
    records = []
    for item in raw.get("records", ()):
        record = _display(item)
        record.update(id=f'{entry.header.context_id}:{item["sequence"]}', sequence=str(item["sequence"]),
                      numeric=type(item.get("value")) in (int, float) and type(record.get("value")) in (int, float),
                      value_type=type(item.get("value")).__name__)
        records.append(record)
    artifacts = []
    for item in raw.get("artifacts", ()):
        artifacts.append({"id": f'artifact-{item["artifact_id"]}', "name": f'Artifact {item["artifact_id"]}',
            "availability": "payload excluded", "placement": _display(item.get("placement")),
            "history": [{**_display(record), "retained_index": index}
                        for index, record in enumerate(item["history"], 1)],
            "history_coverage": "Retained transitions only; no inferred consumer event or value continuity"})
    created, finished = report.get("created_at"), report.get("finished_at")
    elapsed = (finished-created).total_seconds() if type(created) is datetime and type(finished) is datetime else None
    key = provenance.get("graph_key")
    coverage = {"source": "Finalized engine Database entry; not dashboard polling or replay",
        "stored": list(entry.coverage), "records_complete": raw.get("records_complete"),
        "artifact_values": "Excluded", "timing": "Frozen factual progress and selected estimates; never today's profiles",
        "completed_iterations": "Captured" if completed is not None else "Not captured by the older producer; not inferred",
        "progress": "Captured matching final snapshot" if progress_valid else "Absent or inconsistent snapshot; no progress inferred",
        "record_types": "Original record class discriminants were not stored; field values are retained",
        "connections": "Only explicit stored ports, step correspondence and matching artifact history are attributed"}
    return {"context_id": entry.header.context_id, "runtime_context_id": str(report["context_id"]),
        "graph_key": key[0] if type(key) in (tuple, list) and key else None,
        "graph_version": entry.header.graph_version, "intrinsic_graph_id": entry.header.graph_id,
        "engine_id": provenance.get("execution_engine_id"), "generation": provenance.get("generation"),
        "revision": provenance.get("revision"), "report_revision": report.get("revision"),
        "outcome": entry.header.outcome, "iteration_count": iterations, "completed_iterations": completed,
        "stop_requested": report.get("stop_requested"), "created_at": _display(created), "finished_at": _display(finished),
        "elapsed_wall_seconds": elapsed, "failure": _display(report.get("failure")),
        "failed_step": _display(report.get("failed_step")), "executions": executions, "records": records,
        "record_sequence": str(raw.get("record_sequence", "unknown")), "records_complete": raw.get("records_complete"),
        "artifacts": artifacts, "connections": [], "history": _display(report.get("history", ())), "coverage": coverage,
        "configuration": _configuration(entry), "configuration_omitted": 0,
        "settings": {"values": _display(entry.effective_settings.decode()),
            "requested": _display(entry.requested_settings.decode()),
            "provenance": "Stored requested overrides and resolved effective execution settings",
            "gap": "Storage redaction/coverage markers remain explicit"},
        "frozen_progress": _display(progress), "timing": _display(raw.get("timing")),
        "step_correspondence": raw.get("step_correspondence", ())}
