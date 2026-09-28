"""Detached history and query contracts. None of these values restores authority."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Generic, TypeVar

from .errors import StorageContractError
from .values import ValueLimits, ValueMarker, ValueSnapshot, encode_value

_MISSING = encode_value(ValueMarker("missing", "not captured"))
_OUTCOMES = frozenset({"finished", "failed", "stopped", "aborted", "rejected"})
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _text(value: object, name: str, maximum: int = 256, *, optional: bool = False, empty: bool = False) -> None:
    if optional and value is None:
        return
    if type(value) is not str or (not value and not empty) or len(value.encode("utf-8", "surrogatepass")) > maximum:
        raise StorageContractError(f"{name} must be bounded {'optional ' if optional else ''}text ({maximum} bytes)")
    if any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise StorageContractError(f"{name} contains a Unicode surrogate")


def _graph_id(value: str | None) -> None:
    if value is not None and (type(value) is not str or re.fullmatch(r"jrg[1-9][0-9]{0,3}:[0-9a-f]{64}", value) is None):
        raise StorageContractError("graph_id must be an explicit versioned intrinsic ID or None for missing/legacy identity")


def _time(value: datetime, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or type(value.tzinfo) is not timezone:
        raise StorageContractError(f"{name} must be a datetime with an explicit fixed UTC offset")
    if value.utcoffset() is None:
        raise StorageContractError(f"{name} must be timezone-aware")


def _micros(value: datetime) -> int:
    _time(value, "timestamp")
    delta = value - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def _datetime(value: int) -> datetime:
    from datetime import timedelta
    return EPOCH + timedelta(microseconds=value)


def _coverage(value: tuple[str, ...]) -> None:
    if type(value) is not tuple or len(value) > 128:
        raise StorageContractError("coverage must be a tuple of at most 128 messages")
    for item in value:
        _text(item, "coverage", 512)


def _sequence(value: int) -> None:
    if type(value) is not int or not 0 <= value < 2**63:
        raise StorageContractError("publication must be a nonnegative signed-64 integer")


def _json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


@dataclass(frozen=True, slots=True)
class SerializedLayout:
    """A minimal durable envelope around the unchanged portable viewer JSON.

    body is retained byte-for-byte. Unknown schema versions remain inspectable as
    bytes; payload() reports them unavailable rather than synthesizing a graph.
    """

    graph_id: str | None
    graph_version: str | None
    schema_version: str
    body: bytes

    def __post_init__(self) -> None:
        _graph_id(self.graph_id); _text(self.graph_version, "graph version", optional=True, empty=True)
        _text(self.schema_version, "layout schema", 128)
        if type(self.body) is not bytes or len(self.body) > 32 * 1024 * 1024:
            raise StorageContractError("layout body must be bytes within the viewer export ceiling")
        try:
            # Reuse the existing safe JSON structural contract, including depth,
            # scalar and node limits; no application imports or live graph access.
            from ..visualization.contract import SCHEMA_VERSION, _json_copy, validate_payload
            raw = json.loads(self.body)
            if type(raw) is not dict or raw.get("schema_version") != self.schema_version:
                raise ValueError("layout envelope/schema mismatch")
            if self.schema_version == SCHEMA_VERSION:
                validate_payload(raw)
            else:
                _json_copy(raw)
        except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as error:
            raise StorageContractError("invalid serialized graph layout") from error

    @classmethod
    def from_payload(cls, graph_id: str | None, graph_version: str | None, payload: dict) -> SerializedLayout:
        from ..visualization.contract import validate_payload
        try:
            checked = validate_payload(payload)
        except (TypeError, ValueError, RecursionError) as error:
            raise StorageContractError("invalid portable graph payload") from error
        return cls(graph_id, graph_version, checked["schema_version"], _json(checked))

    @property
    def available(self) -> bool:
        from ..visualization.contract import SCHEMA_VERSION
        return self.schema_version == SCHEMA_VERSION

    def payload(self) -> dict:
        """Return a fresh checked viewer payload; no executable type is instantiated."""
        if not self.available:
            raise StorageContractError(f"rendering unavailable for layout schema {self.schema_version}")
        from ..visualization.contract import validate_payload
        return validate_payload(json.loads(self.body))

    @property
    def _key(self) -> str:
        metadata = _json([self.graph_id, self.graph_version, self.schema_version])
        return hashlib.sha256(metadata + b"\0" + self.body).hexdigest()


@dataclass(frozen=True, slots=True)
class ContextHistoryHeader:
    session_id: str
    context_id: str
    graph_id: str | None
    graph_version: str | None
    outcome: str
    finalized_at: datetime | None
    publication: int = 0
    layout_schema: str | None = None
    captured_at: datetime | None = None

    def __post_init__(self) -> None:
        _text(self.session_id, "session_id"); _text(self.context_id, "context_id", 128)
        _graph_id(self.graph_id); _text(self.graph_version, "graph_version", optional=True, empty=True)
        if self.outcome not in _OUTCOMES:
            raise StorageContractError("only finalized context outcomes can be recorded")
        if self.finalized_at is not None:
            _time(self.finalized_at, "finalized_at")
        if self.captured_at is not None:
            _time(self.captured_at, "captured_at")
        if self.finalized_at is None and self.captured_at is None:
            raise StorageContractError("a legacy context without finalization time requires its recorded capture time")
        _sequence(self.publication)
        _text(self.layout_schema, "layout_schema", 128, optional=True)


@dataclass(frozen=True, slots=True)
class ContextHistoryEntry:
    """One finalized diagnostic account; values and layout are immutable byte snapshots."""

    header: ContextHistoryHeader
    configurations: ValueSnapshot = _MISSING
    requested_settings: ValueSnapshot = _MISSING
    effective_settings: ValueSnapshot = _MISSING
    provenance: ValueSnapshot = _MISSING
    evidence: ValueSnapshot = _MISSING
    coverage: tuple[str, ...] = ()
    layout: SerializedLayout | None = None
    # Reader availability is not part of stored, immutable execution evidence.
    layout_unavailable_reason: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if type(self.header) is not ContextHistoryHeader:
            raise StorageContractError("context header is required")
        for name in ("configurations", "requested_settings", "effective_settings", "provenance", "evidence"):
            if type(getattr(self, name)) is not ValueSnapshot:
                raise StorageContractError(f"{name} must be a detached ValueSnapshot")
        _coverage(self.coverage)
        if self.layout is not None:
            if type(self.layout) is not SerializedLayout:
                raise StorageContractError("layout must be SerializedLayout or None")
            if (self.layout.graph_id, self.layout.graph_version) != (self.header.graph_id, self.header.graph_version):
                raise StorageContractError("context and exact layout identity/version disagree")
            if self.header.layout_schema not in (None, self.layout.schema_version):
                raise StorageContractError("context and layout schema disagree")
            object.__setattr__(self, "header", replace(self.header, layout_schema=self.layout.schema_version))
            if not self.layout.available:
                object.__setattr__(self, "layout_unavailable_reason", "layout: unsupported schema; outcome remains readable")
        else:
            object.__setattr__(self, "layout_unavailable_reason", "layout: not captured")


@dataclass(frozen=True, slots=True)
class EngineSessionHeader:
    session_id: str
    started_at: datetime | None
    engine_name: str | None = None
    engine_id: str | None = None
    shutdown_at: datetime | None = None
    publication: int = 0

    def __post_init__(self) -> None:
        _text(self.session_id, "session_id")
        if self.started_at is not None:
            _time(self.started_at, "started_at")
        _text(self.engine_name, "engine_name", optional=True)
        _text(self.engine_id, "engine_id", optional=True)
        _sequence(self.publication)
        if self.shutdown_at is not None:
            _time(self.shutdown_at, "shutdown_at")
            if self.started_at is not None and self.shutdown_at < self.started_at:
                raise StorageContractError("shutdown precedes session startup")


@dataclass(frozen=True, slots=True)
class EngineSessionRecord:
    header: EngineSessionHeader
    settings: ValueSnapshot = _MISSING
    environment: ValueSnapshot = _MISSING
    shutdown: ValueSnapshot = _MISSING
    coverage: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.header) is not EngineSessionHeader:
            raise StorageContractError("session header is required")
        for name in ("settings", "environment", "shutdown"):
            if type(getattr(self, name)) is not ValueSnapshot:
                raise StorageContractError(f"{name} must be a detached ValueSnapshot")
        _coverage(self.coverage)


@dataclass(frozen=True, slots=True)
class HistoryQuery:
    """Committed-publication pages; concurrent pruning may remove rows.

    descending reverses publication order, not timestamps. search is a literal,
    case-sensitive substring of context/session/graph IDs or graph version; it
    never reads diagnostic bodies or matches opaque configuration values."""

    graph_id: str | None = None
    graph_version: str | None = None
    session_id: str | None = None
    outcome: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 50
    cursor: str | None = None
    descending: bool = False
    search: str | None = None

    def __post_init__(self) -> None:
        _text(self.search, "search", 256, optional=True)
        _graph_id(self.graph_id); _text(self.graph_version, "graph_version", optional=True, empty=True)
        _text(self.session_id, "session_id", optional=True)
        if self.outcome is not None and self.outcome not in _OUTCOMES:
            raise StorageContractError("unknown outcome filter")
        if type(self.descending) is not bool:
            raise StorageContractError("descending must be a bool")
        _query_bounds(self.since, self.until, self.limit, self.cursor)


@dataclass(frozen=True, slots=True)
class SessionQuery:
    engine_name: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 50
    cursor: str | None = None
    descending: bool = False

    def __post_init__(self) -> None:
        _text(self.engine_name, "engine_name", optional=True)
        if type(self.descending) is not bool:
            raise StorageContractError("descending must be a bool")
        _query_bounds(self.since, self.until, self.limit, self.cursor)


def _query_bounds(since: datetime | None, until: datetime | None, limit: int, cursor: str | None) -> None:
    if since is not None: _time(since, "since")
    if until is not None: _time(until, "until")
    if since is not None and until is not None and since > until:
        raise StorageContractError("since cannot exceed until")
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise StorageContractError("page limit must be between 1 and 1000")
    _text(cursor, "cursor", 2048, optional=True)


Header = TypeVar("Header", ContextHistoryHeader, EngineSessionHeader)


@dataclass(frozen=True, slots=True)
class HistoryPage(Generic[Header]):
    items: tuple[Header, ...]
    next_cursor: str | None
    boundary: int


def _context_body(entry: ContextHistoryEntry) -> bytes:
    return _json({"schema": "jayrun.context/1", "coverage": entry.coverage,
                  **{n: getattr(entry, n).data.decode("ascii") for n in
                     ("configurations", "requested_settings", "effective_settings", "provenance", "evidence")}})


def _context_read(header: ContextHistoryHeader, body: bytes, layout: SerializedLayout | None,
                  layout_error: str | None = None, *, value_limits: ValueLimits = ValueLimits()) -> ContextHistoryEntry:
    try:
        raw = json.loads(body)
        if raw["schema"] != "jayrun.context/1":
            raise ValueError("unsupported context body")
        coverage = tuple(raw["coverage"])
        entry = ContextHistoryEntry(header, **{n: ValueSnapshot(raw[n].encode("ascii"), value_limits) for n in
            ("configurations", "requested_settings", "effective_settings", "provenance", "evidence")},
            coverage=coverage, layout=layout)
        if layout_error:
            _text(layout_error, "layout availability", 512)
            object.__setattr__(entry, "layout_unavailable_reason", layout_error)
        return entry
    except (KeyError, TypeError, ValueError, RecursionError, UnicodeError) as error:
        raise StorageContractError("invalid context diagnostic body") from error


def _session_body(entry: EngineSessionRecord) -> bytes:
    return _json({"schema": "jayrun.session/1", "coverage": entry.coverage,
                  **{n: getattr(entry, n).data.decode("ascii") for n in ("settings", "environment", "shutdown")}})


def _session_read(header: EngineSessionHeader, body: bytes, *, value_limits: ValueLimits = ValueLimits()) -> EngineSessionRecord:
    try:
        raw = json.loads(body)
        if raw["schema"] != "jayrun.session/1": raise ValueError("unsupported session body")
        return EngineSessionRecord(header, **{n: ValueSnapshot(raw[n].encode("ascii"), value_limits) for n in ("settings", "environment", "shutdown")},
                                   coverage=tuple(raw["coverage"]))
    except (KeyError, TypeError, ValueError, RecursionError, UnicodeError) as error:
        raise StorageContractError("invalid session diagnostic body") from error

def _layout_size(layout: SerializedLayout) -> int:
    return len(layout.body) + len(_json([layout._key, layout.graph_id, layout.graph_version, layout.schema_version]))


def _context_identity(entry: ContextHistoryEntry) -> bytes:
    h = entry.header
    values = [h.session_id, h.context_id, h.graph_id, h.graph_version,
              h.outcome, _micros(h.finalized_at) if h.finalized_at is not None else None,
              entry.layout._key if entry.layout else None,
              entry.layout.schema_version if entry.layout else h.layout_schema]
    # Existing current-context identities/digests are byte-for-byte unchanged.
    if h.captured_at is not None:
        values.append(_micros(h.captured_at))
    return _json(values)


def _session_identity(entry: EngineSessionRecord, *, startup: bool = False) -> bytes:
    h = entry.header
    return _json([h.session_id, _micros(h.started_at) if h.started_at is not None else None, h.engine_name, h.engine_id,
                  None if startup or h.shutdown_at is None else _micros(h.shutdown_at)])



def _check_values(entry: ContextHistoryEntry | EngineSessionRecord, limits: ValueLimits) -> None:
    names = (("configurations", "requested_settings", "effective_settings", "provenance", "evidence")
             if type(entry) is ContextHistoryEntry else ("settings", "environment", "shutdown"))
    for name in names:
        ValueSnapshot(getattr(entry, name).data, limits)


def _header_size(header: ContextHistoryHeader | EngineSessionHeader) -> int:
    if type(header) is ContextHistoryHeader:
        values = (header.session_id, header.context_id, header.graph_id, header.graph_version,
                  header.outcome, _micros(header.finalized_at) if header.finalized_at is not None else None, header.publication, header.layout_schema)
        if header.captured_at is not None:
            values += (_micros(header.captured_at),)
    else:
        values = (header.session_id, _micros(header.started_at) if header.started_at is not None else None,
                  _micros(header.shutdown_at) if header.shutdown_at is not None else None,
                  header.engine_name, header.engine_id, header.publication)
    return len(_json(values))


@dataclass(frozen=True, slots=True)
class LegacyImportRecord:
    """Detached progress of one content-addressed, explicit legacy import.

    created_at is the import's start, never an invented engine or execution time.
    Profiles in evidence are legacy/nonmatching diagnostics, not active learning.
    The retained ledger is bounded and is not expired when imported contexts age
    out: retrying a completed import must not resurrect pruned history.
    """

    import_id: str
    source_sha256: str
    source_kind: str
    created_at: datetime
    encoding_key: str
    processed: int = 0
    imported_contexts: int = 0
    unmatched_profiles: int = 0
    skipped: int = 0
    complete: bool = False
    cursor: tuple[str, str] | None = None
    evidence: ValueSnapshot = _MISSING
    issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (type(self.source_sha256) is not str
                or re.fullmatch(r"[0-9a-f]{64}", self.source_sha256) is None
                or self.source_kind not in ("dashboard", "profiles")):
            raise StorageContractError("invalid legacy source identity/kind")
        expected = "jri1:" + hashlib.sha256(_json(["jayrun.legacy-import/1", self.source_kind, self.source_sha256])).hexdigest()
        if self.import_id != expected:
            raise StorageContractError("legacy import identity does not match its source")
        _time(self.created_at, "import creation")
        if type(self.encoding_key) is not str or re.fullmatch(r"[0-9a-f]{64}", self.encoding_key) is None:
            raise StorageContractError("invalid legacy encoding/redaction policy identity")
        for name in ("processed", "imported_contexts", "unmatched_profiles", "skipped"):
            _sequence(getattr(self, name))
        if self.imported_contexts + self.unmatched_profiles + self.skipped != self.processed:
            raise StorageContractError("legacy import counts disagree")
        if type(self.complete) is not bool or type(self.evidence) is not ValueSnapshot:
            raise StorageContractError("invalid legacy import state/evidence")
        _coverage(self.issues)
        if len(self.issues) > 32:
            raise StorageContractError("legacy import retains at most 32 recent issues")
        if self.cursor is not None:
            if type(self.cursor) is not tuple or len(self.cursor) != 2:
                raise StorageContractError("invalid legacy import cursor")
            _text(self.cursor[0], "legacy partition")
            _text(self.cursor[1], "legacy context", 128)
        if (self.source_kind == "dashboard" and self.unmatched_profiles
                or self.source_kind == "profiles" and (self.cursor is not None or self.imported_contexts)):
            raise StorageContractError("legacy import counts/cursor disagree with its source kind")


def _legacy_import_body(record: LegacyImportRecord) -> bytes:
    return _json({"schema": "jayrun.legacy-import/1", "import_id": record.import_id,
        "source_sha256": record.source_sha256, "source_kind": record.source_kind,
        "created_at": _micros(record.created_at), "encoding_key": record.encoding_key, "processed": record.processed,
        "imported_contexts": record.imported_contexts, "unmatched_profiles": record.unmatched_profiles,
        "skipped": record.skipped, "complete": record.complete, "cursor": record.cursor,
        "evidence": record.evidence.data.decode("ascii"), "issues": record.issues})


def _legacy_import_read(body: bytes, limits: ValueLimits = ValueLimits()) -> LegacyImportRecord:
    try:
        raw = json.loads(body)
        if raw.pop("schema") != "jayrun.legacy-import/1":
            raise ValueError("unsupported legacy import record")
        raw["created_at"] = _datetime(raw["created_at"])
        raw["cursor"] = None if raw["cursor"] is None else tuple(raw["cursor"])
        raw["issues"] = tuple(raw["issues"])
        raw["evidence"] = ValueSnapshot(raw["evidence"].encode("ascii"), limits)
        return LegacyImportRecord(**raw)
    except (TypeError, KeyError, ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise StorageContractError("invalid legacy import record") from error
