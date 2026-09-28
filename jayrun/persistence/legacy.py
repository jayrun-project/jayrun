"""Explicit, bounded conversion of the retired dashboard and timing-file formats.

Sources are offline, read-only snapshots, never engines or executable graphs.
An import owns a closed Database for one bounded interval. Its per-source cursor
commits atomically with converted records; a retained ledger prevents repeated
imports from resurrecting contexts removed by retention. No ordinary open,
engine startup, or dashboard refresh invokes this module.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Iterator, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

from ._database import Database, _Reservation
from .backend import TimingStatistics
from .errors import PersistenceBackpressure, StorageContractError, StorageUnavailable
from .records import (ContextHistoryEntry, ContextHistoryHeader, EngineSessionHeader,
                      EngineSessionRecord, LegacyImportRecord, SerializedLayout,
                      _json, _text)
from .values import ValueMarker, ValueSnapshot, encode_value

_DASHBOARD_BYTES = 64 * 1024 * 1024
_PROFILE_BYTES = 4 * 1024 * 1024
_ROW_BYTES = 512 * 1024
_GRAPH_BYTES = 2 * 1024 * 1024
_FORMATS = frozenset(("dashboard", "profiles"))


def _pairs(items: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in items:
        if key in result:
            raise StorageContractError("duplicate member in legacy JSON")
        result[key] = value
    return result


def _nonfinite(value: str) -> object:
    raise StorageContractError("nonfinite legacy JSON number")


def _read_json(body: bytes | str, maximum: int) -> dict:
    if type(body) not in (bytes, str) or len(body if type(body) is bytes else body.encode("utf-8")) > maximum:
        raise StorageContractError("legacy JSON exceeds its source item bound")
    try:
        value = json.loads(body, object_pairs_hook=_pairs, parse_constant=_nonfinite)
        from ..visualization.contract import _json_copy
        # The existing safe primitive validator bounds depth/nodes/scalars. It
        # imports no adapters, user modules, codecs, or executable graph types.
        value = _json_copy(value)
        if type(value) is not dict:
            raise ValueError("not an object")
        return value
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as error:
        raise StorageContractError("invalid or oversized legacy JSON") from error


def _fingerprint(path: Path, maximum: int) -> tuple[str, os.stat_result]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not 0 < before.st_size <= maximum:
            raise StorageContractError("legacy source exceeds the supported file size")
        total = 0
        while block := stream.read(64 * 1024):
            total += len(block)
            if total > maximum:
                raise StorageContractError("legacy source grew beyond its byte bound")
            digest.update(block)
        after = os.fstat(stream.fileno())
    if _signature(before) != _signature(after) or _signature(after) != _signature(path.stat()):
        raise StorageContractError("legacy source changed while being fingerprinted")
    return digest.hexdigest(), after


def _signature(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _offline(path: Path) -> None:
    # Avoid SQLite recovery, WAL shared-memory creation, or reading an unmerged
    # source. An application must stop its old writer and provide an offline copy.
    if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise StorageContractError("legacy SQLite source must be offline with no journal/WAL sidecars")
    with path.open("rb") as stream:
        header = stream.read(100)
    if header[:16] != b"SQLite format 3\0" or header[18:20] != b"\x01\x01":
        raise StorageContractError("legacy source must be a rollback-journal SQLite snapshot")


@contextmanager
def _dashboard_source(path: Path) -> Iterator[tuple[sqlite3.Connection, os.stat_result]]:
    import sqlite3
    _offline(path)
    initial = path.stat()
    if path.stat().st_size > _DASHBOARD_BYTES:
        raise StorageContractError("legacy dashboard source exceeds 64 MiB")
    con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, isolation_level=None, timeout=0.25)
    try:
        con.execute("PRAGMA query_only=ON")
        con.execute("PRAGMA trusted_schema=OFF")
        con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 3 * 1024 * 1024)
        con.execute("BEGIN")
        objects = con.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 17").fetchall()
        tables = {row[1] for row in objects if row[0] == "table"}
        allowed = {"dashboard_history", "dashboard_graph_snapshots"}
        if (len(objects) > 16 or "dashboard_history" not in tables or not tables <= allowed
                or any(row[0] not in ("table", "index") for row in objects)
                or any(row[0] == "index" and row[1] != "dashboard_history_captured" for row in objects)):
            raise StorageContractError("foreign or unsupported legacy dashboard schema")
        expected = {
            "dashboard_history": [("partition", "TEXT", 1), ("context", "TEXT", 2), ("captured", "REAL", 0), ("body", "TEXT", 0)],
            "dashboard_graph_snapshots": [("snapshot", "TEXT", 1), ("viewer_schema", "TEXT", 0), ("body", "TEXT", 0)],
        }
        for table in tables:
            columns = [(row[1], row[2].upper(), row[5]) for row in con.execute("PRAGMA table_info(" + table + ")")]
            if columns != expected[table]:
                raise StorageContractError("altered legacy dashboard column contract")
        if con.execute("PRAGMA user_version").fetchone()[0] != 0 or con.execute("PRAGMA application_id").fetchone()[0] != 0:
            raise StorageContractError("unsupported legacy dashboard database version")
        if _signature(path.stat()) != _signature(initial):
            raise StorageContractError("legacy source changed while acquiring its snapshot")
        yield con, initial
    except sqlite3.Error as error:
        raise StorageContractError("legacy SQLite read failed; source left unchanged") from error
    finally:
        con.close()


def _snapshot(value: object, database: Database) -> ValueSnapshot:
    # Only already bounded JSON primitives are imported. Application codecs never
    # run. Existing explicit redaction paths apply to the original source object.
    try:
        snapshot = encode_value(value, limits=database.value_limits, redact=database.redact)
    except StorageContractError as error:
        raise PersistenceBackpressure("legacy evidence exceeds configured encoding limits") from error
    return _checked(snapshot)


def _checked(snapshot: ValueSnapshot) -> ValueSnapshot:
    if not snapshot.complete:
        def valid(item: object) -> bool:
            if type(item) is ValueMarker:
                return item.kind == "redacted"
            if type(item) is dict:
                return all(valid(key) and valid(child) for key, child in item.items())
            if type(item) in (list, tuple):
                return all(valid(child) for child in item)
            return True
        if not valid(snapshot.decode()):
            raise PersistenceBackpressure("legacy evidence cannot be retained within the configured value limits")
    return snapshot


def _layout(con: sqlite3.Connection, raw: dict) -> tuple[SerializedLayout | None, dict | None, str | None]:
    import sqlite3
    reference = raw.get("graph_snapshot")
    if reference is None:
        return None, None, "Legacy layout was not captured"
    if type(reference) is not str or len(reference) != 73 or not reference.startswith("graph-v1-"):
        return None, None, "Invalid legacy layout reference; diagnostic context remains readable"
    try:
        row = con.execute("SELECT viewer_schema,CASE WHEN length(CAST(body AS BLOB))<=? THEN body END FROM dashboard_graph_snapshots WHERE snapshot=?", (_GRAPH_BYTES, reference)).fetchone()
        if row is None or row[1] is None or "graph-v1-" + hashlib.sha256(row[1].encode("utf-8")).hexdigest() != reference:
            raise ValueError("missing, oversized or changed layout")
        envelope = _read_json(row[1], _GRAPH_BYTES)
        if set(envelope) != {"definition", "bindings"}:
            raise ValueError("invalid captured layout envelope")
        definition = envelope["definition"]
        if type(definition) is not dict or definition.get("schema_version") != row[0]:
            raise ValueError("schema mismatch")
        # Preserve unknown but bounded schema bodies as explicitly unavailable.
        layout = SerializedLayout(None, None, row[0], _json(definition))
        if layout.available:
            from ..visualization.adapters._legacy_history import validate_bindings
            validate_bindings(layout.payload(), envelope["bindings"])
        return layout, envelope["bindings"], (None if layout.available else "Legacy layout uses an unsupported viewer schema")
    except (StorageContractError, sqlite3.Error, ValueError, KeyError, TypeError, OverflowError):
        return None, None, "Invalid or missing legacy layout; diagnostic context remains readable"


def _converted(con: sqlite3.Connection, row: tuple, record: LegacyImportRecord, database: Database
               ) -> tuple[ContextHistoryEntry | None, EngineSessionRecord | None, str | None]:
    partition, context, captured, body = row
    _text(partition, "legacy partition"); _text(context, "legacy context", 128)
    raw = _read_json(body, _ROW_BYTES)
    version = raw.get("archive_schema_version", 1)
    if type(version) is not int or version not in (1, 2):
        raise StorageContractError("unsupported legacy dashboard entry version")
    if raw.get("finalized") is not True:
        return None, None, "Skipped a legacy row without a finalized outcome"
    if type(raw.get("row")) is not dict:
        raise StorageContractError("legacy row lacks an outcome header")
    outcome = raw["row"].get("state")
    if type(captured) not in (int, float) or not math.isfinite(captured):
        raise StorageContractError("invalid legacy capture timestamp")
    try:
        instant = datetime.fromtimestamp(captured, timezone.utc)
    except (ValueError, OverflowError, OSError) as error:
        raise StorageContractError("legacy capture time outside supported range") from error
    sid = "legacy-" + record.import_id[5:] + ":" + hashlib.sha256(partition.encode()).hexdigest()
    # Source key identifies the original archive row. Display/runtime IDs in the
    # body may differ and remain original, rather than being promoted to authority.
    header = ContextHistoryHeader(sid, context, None, None, outcome, None, captured_at=instant)
    layout, bindings, gap = _layout(con, raw)
    source = _snapshot(raw, database)
    metadata = {"schema": "jayrun.legacy-dashboard/1", "source": source.decode(), "bindings": bindings}
    evidence = _checked(encode_value(metadata, limits=database.value_limits))
    # Re-encoding ValueMarker deliberately preserves explicit redaction; the
    # second envelope is still bounded and must not silently lose other detail.
    coverage = ("Legacy display-oriented evidence; resolved configuration/settings and execution completeness are not established",
                "Intrinsic graph identity and finalization/session timestamps are unavailable; captured_at is an observation time")
    if database.redact:
        coverage += ("Explicit import redaction applies to original source paths; no secret detection is claimed",)
    if gap:
        coverage += (gap,)
    entry = ContextHistoryEntry(header, evidence=evidence,
        provenance=encode_value({"schema": "jayrun.legacy-origin/1", "import_id": record.import_id,
            "source_partition": partition, "source_context": context, "capture_kind": "legacy-observation"}),
        coverage=coverage, layout=layout)
    session = EngineSessionRecord(EngineSessionHeader(sid, None),
        environment=encode_value({"legacy_import_id": record.import_id, "source_partition": partition}),
        coverage=("Legacy archive partition is a diagnostic namespace, not a known engine session or an authority grant",
                  "Original engine startup, shutdown, settings and engine_id identity were not captured"))
    return entry, session, gap


def _profiles(path: Path) -> dict:
    with path.open("rb") as stream:
        body = stream.read(_PROFILE_BYTES + 1)
    document = _read_json(body, _PROFILE_BYTES)
    if set(document) != {"schema_version", "graphs"} or type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise StorageContractError("unsupported legacy timing-file format")
    graphs = document["graphs"]
    if type(graphs) is not list or len(graphs) > 4096:
        raise StorageContractError("legacy timing population exceeds 4096 graphs")
    seen = set()
    for graph in graphs:
        if type(graph) is not dict or set(graph) != {"key", "version", "run_count", "steps"}:
            raise StorageContractError("invalid legacy graph aggregate")
        for name in ("key", "version"):
            _text(graph[name], "legacy graph " + name)
        key = graph["key"], graph["version"]
        if key in seen:
            raise StorageContractError("duplicate legacy graph identity")
        seen.add(key)
        if type(graph["run_count"]) is not int or not 0 <= graph["run_count"] < 2**63:
            raise StorageContractError("invalid legacy run count")
        if type(graph["steps"]) is not list or len(graph["steps"]) > 65_536:
            raise StorageContractError("invalid legacy step vector")
        for step in graph["steps"]:
            if type(step) is not dict or set(step) != {"observation_count", "completion_count", "skipped_count", "failure_count", "mean_seconds", "squared_deviation"}:
                raise StorageContractError("invalid legacy step statistics")
            TimingStatistics(**step)
    return document


def _commit(database: Database, record: LegacyImportRecord, previous: LegacyImportRecord | None,
            reservation: _Reservation, *, entry: ContextHistoryEntry | None = None, session: EngineSessionRecord | None = None) -> None:
    database._publish(database._manual, reservation, contexts=(() if entry is None else (entry,)),
        sessions=(() if session is None else (session,)), legacy_import=record,
        legacy_expected=previous.processed if previous is not None else None)
    # Never return or advance a cursor before commit acknowledgement. A failed
    # barrier still reports gaps when engine execution continues.
    database.flush()


def import_legacy(source: str | os.PathLike[str], database: Database, *,
                  format: Literal["dashboard", "profiles"], max_items: int = 256) -> LegacyImportRecord:
    """Import at most ``max_items`` source rows, with a durable resumable result.

    ``database`` must be closed and is opened/closed by this call. Existing schema
    v1 destinations require an explicit ``database.upgrade()`` first. Sources are
    never modified. Repeating a completed identical source returns its retained
    ledger, even after destination contexts expire. Changed source bytes constitute
    a different import. No automatic semantic deduplication is promised.

    Dashboard finalization/startup times and intrinsic IDs stay unknown. Retained
    numeric timing files are diagnostic/nonmatching: they never teach a current
    graph. Redaction paths address original source JSON; application codecs are
    not invoked. This synchronous operation must run off an asyncio loop thread.
    """
    if type(database) is not Database or format not in _FORMATS:
        raise TypeError("supply a Database and format='dashboard' or 'profiles'")
    if type(max_items) is not int or not 1 <= max_items <= 1024:
        raise ValueError("max_items must be between 1 and 1024")
    if database._owner is not None:
        raise StorageContractError("legacy import requires an independently owned closed Database")
    path = Path(source).expanduser().resolve(strict=True)
    target = database.path
    if target is not None and (path == target.resolve() or target.exists() and path.samefile(target)):
        raise StorageContractError("legacy source and destination must be different files")
    if not path.is_file():
        raise StorageContractError("legacy source must be a regular file")

    @contextmanager
    def opened_source() -> Iterator[tuple[sqlite3.Connection | None, dict | None, str, os.stat_result]]:
        if format == "dashboard":
            with _dashboard_source(path) as (con, initial):
                digest, stat = _fingerprint(path, _DASHBOARD_BYTES)
                if _signature(stat) != _signature(initial):
                    raise StorageContractError("legacy source path no longer names the acquired snapshot")
                yield con, None, digest, stat
        else:
            digest, stat = _fingerprint(path, _PROFILE_BYTES)
            document = _profiles(path)
            if _signature(path.stat()) != _signature(stat):
                raise StorageContractError("legacy source changed while being parsed")
            yield None, document, digest, stat

    with opened_source() as (con, document, digest, stat):
        import_id = "jri1:" + hashlib.sha256(_json(["jayrun.legacy-import/1", format, digest])).hexdigest()
        database.open(read_only=False)
        with database:
            prior = database.get_legacy_import(import_id)
            encoding_key = hashlib.sha256(_json(["jayrun.legacy-encoding/1", asdict(database.value_limits), database.redact])).hexdigest()
            if prior is not None and prior.encoding_key != encoding_key:
                raise StorageContractError("resuming a legacy import requires the original encoding limits and redaction policy")
            if prior is not None and prior.complete:
                return prior
            current = prior or LegacyImportRecord(import_id, digest, format, datetime.now(timezone.utc), encoding_key)
            if format == "profiles":
                assert document is not None
                end = min(len(document["graphs"]), current.processed + max_items)
                reservation = database._reserve_cache(database._manual, database.limits.batch_bytes)
                if reservation is None:
                    raise PersistenceBackpressure("legacy conversion capture capacity unavailable")
                try:
                    evidence = _snapshot({"schema_version": 1, "graphs": document["graphs"][:end]}, database)
                    result = replace(current, processed=end, unmatched_profiles=end,
                        complete=end == len(document["graphs"]), evidence=evidence,
                        issues=("Legacy/nonmatching: graph, resolved-config and ordered execution compatibility are unproven",))
                    if _signature(path.stat()) != _signature(stat):
                        raise StorageContractError("legacy source changed during conversion")
                    _commit(database, result, prior, reservation)
                    return result
                finally:
                    if reservation.active and not reservation.published:
                        database._discard(database._manual, reservation)
            assert con is not None
            for _ in range(max_items):
                reservation = database._reserve_cache(database._manual, database.limits.batch_bytes)
                if reservation is None:
                    raise PersistenceBackpressure("legacy conversion capture capacity unavailable")
                try:
                    if _signature(path.stat()) != _signature(stat):
                        raise StorageContractError("legacy source changed during conversion")
                    where, args = ("", ()) if current.cursor is None else (" WHERE (partition,context)>(?,?)", current.cursor)
                    row = con.execute("SELECT partition,context,captured,CASE WHEN length(CAST(body AS BLOB))<=? THEN body END FROM dashboard_history" + where + " ORDER BY partition,context LIMIT 1", (_ROW_BYTES, *args)).fetchone()
                    if row is None:
                        result = replace(current, complete=True)
                        _commit(database, result, prior, reservation)
                        return result
                    entry, session, issue = _converted(con, row, current, database)
                    cursor = row[0], row[1]
                    more = con.execute("SELECT 1 FROM dashboard_history WHERE (partition,context)>(?,?) ORDER BY partition,context LIMIT 1", cursor).fetchone() is not None
                    issues = current.issues if issue is None else (*current.issues, issue)[-32:]
                    result = replace(current, processed=current.processed+1,
                        imported_contexts=current.imported_contexts+int(entry is not None),
                        skipped=current.skipped+int(entry is None), cursor=cursor, complete=not more,
                        issues=issues, evidence=encode_value({"coverage": "Legacy display snapshots, not replay-complete runtime history"}))
                    if _signature(path.stat()) != _signature(stat):
                        raise StorageContractError("legacy source changed during conversion")
                    _commit(database, result, prior, reservation, entry=entry, session=session)
                    current = prior = result
                    if result.complete:
                        return result
                finally:
                    if reservation.active and not reservation.published:
                        database._discard(database._manual, reservation)
            return current
