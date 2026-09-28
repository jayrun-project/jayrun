"""Owned SQLite backend: rollback journal, atomic publication and indexed retention.

Only local files with correctly functioning SQLite locks/fsync are supported.
DELETE/EXTRA avoids the WAL-reset bug on the qualified Python-linked library.
No journal-policy changes, initialization or maintenance occur on read-only opens.
"""
from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
import sqlite3
import threading
import time
from uuid import uuid4

from .backend import (BackendOptions, ProfileAggregate, ProfileQuery, StoreStatistics,
                      WriteBatch, WriteReceipt, _profile_body, _profile_read)
from .errors import PersistenceBackpressure, StorageContractError, StorageUnavailable
from .policy import RetentionPolicy
from .values import ValueSnapshot
from .records import (ContextHistoryEntry, ContextHistoryHeader, EngineSessionHeader,
                      EngineSessionRecord, HistoryPage, HistoryQuery, SerializedLayout,
                      SessionQuery, _context_body, _context_read, _datetime, _json,
                      _micros, _session_body, _session_read, _text, _layout_size,
                      _context_identity, _session_identity, _check_values, LegacyImportRecord,
                      _legacy_import_body, _legacy_import_read)

_APPLICATION_ID = 0x4A525031
_SCHEMA_VERSION = 2
_SCHEMA = (
    """CREATE TABLE metadata (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), store_id TEXT NOT NULL,
        policy TEXT NOT NULL, clock_us INTEGER NOT NULL DEFAULT 0,
        publication INTEGER NOT NULL DEFAULT 0,
        contexts INTEGER NOT NULL DEFAULT 0, context_bytes INTEGER NOT NULL DEFAULT 0,
        layouts INTEGER NOT NULL DEFAULT 0, layout_bytes INTEGER NOT NULL DEFAULT 0,
        sessions INTEGER NOT NULL DEFAULT 0, session_bytes INTEGER NOT NULL DEFAULT 0,
        profiles INTEGER NOT NULL DEFAULT 0, profile_bytes INTEGER NOT NULL DEFAULT 0,
        profile_steps INTEGER NOT NULL DEFAULT 0, producers INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE sessions (
        session_id TEXT PRIMARY KEY, started_us INTEGER NOT NULL, shutdown_us INTEGER,
        engine_name TEXT, machine_name TEXT, publication INTEGER NOT NULL UNIQUE,
        refs INTEGER NOT NULL DEFAULT 0 CHECK(refs>=0), nbytes INTEGER NOT NULL,
        startup_digest TEXT NOT NULL, digest TEXT NOT NULL, body BLOB NOT NULL)""",
    """CREATE TABLE layouts (
        layout_key TEXT PRIMARY KEY, graph_id TEXT, graph_version TEXT,
        schema_version TEXT NOT NULL, refs INTEGER NOT NULL CHECK(refs>=0),
        nbytes INTEGER NOT NULL, body BLOB NOT NULL)""",
    """CREATE TABLE contexts (
        session_id TEXT NOT NULL REFERENCES sessions(session_id), context_id TEXT NOT NULL,
        graph_id TEXT, graph_version TEXT, outcome TEXT NOT NULL, finalized_us INTEGER NOT NULL,
        publication INTEGER NOT NULL UNIQUE, layout_key TEXT REFERENCES layouts(layout_key),
        layout_schema TEXT, nbytes INTEGER NOT NULL, digest TEXT NOT NULL, body BLOB NOT NULL,
        PRIMARY KEY(session_id,context_id))""",
    """CREATE TABLE profiles (
        profile_key TEXT PRIMARY KEY, graph_id TEXT NOT NULL, graph_version TEXT NOT NULL,
        configuration_key TEXT NOT NULL, compatibility_key TEXT NOT NULL, schema_version TEXT NOT NULL,
        updated_us INTEGER NOT NULL, publication INTEGER NOT NULL UNIQUE,
        steps INTEGER NOT NULL, nbytes INTEGER NOT NULL, body BLOB NOT NULL)""",
    """CREATE TABLE producers (
        producer TEXT PRIMARY KEY, expires_us INTEGER NOT NULL, sequence INTEGER NOT NULL,
        digest TEXT NOT NULL)""",
    "CREATE INDEX contexts_graph ON contexts(graph_id,graph_version,publication)",
    "CREATE INDEX contexts_graph_page ON contexts(graph_id,publication)",
    "CREATE INDEX contexts_session ON contexts(session_id,publication)",
    "CREATE INDEX contexts_outcome ON contexts(outcome,publication)",
    "CREATE INDEX contexts_retention ON contexts(finalized_us,publication)",
    "CREATE INDEX contexts_version ON contexts(graph_version,publication)",
    "CREATE INDEX layouts_graph ON layouts(graph_id,graph_version)",
    "CREATE INDEX sessions_engine ON sessions(engine_name,publication)",
    "CREATE INDEX sessions_retention ON sessions(shutdown_us,started_us,publication)",
    "CREATE INDEX sessions_time ON sessions(started_us,publication)",
    "CREATE INDEX profiles_graph ON profiles(graph_id,publication)",
    "CREATE INDEX profiles_compatibility ON profiles(compatibility_key,publication)",
    "CREATE INDEX profiles_retention ON profiles(updated_us,publication)",
    "CREATE INDEX producers_expiry ON producers(expires_us)",
)
# Version 1 remains a read-only input. Upgrade is an explicit owner operation,
# never a side effect of ordinary inspection or engine startup.
_SCHEMA_V1 = _SCHEMA
_SCHEMA = tuple(statement.replace(
    "producers INTEGER NOT NULL DEFAULT 0)",
    "producers INTEGER NOT NULL DEFAULT 0, legacy_imports INTEGER NOT NULL DEFAULT 0, legacy_bytes INTEGER NOT NULL DEFAULT 0)")
    .replace("started_us INTEGER NOT NULL", "started_us INTEGER")
    .replace("finalized_us INTEGER NOT NULL", "finalized_us INTEGER")
    .replace("body BLOB NOT NULL,\n        PRIMARY KEY(session_id,context_id)",
             "body BLOB NOT NULL, captured_us INTEGER,\n        PRIMARY KEY(session_id,context_id)")
    .replace("contexts(finalized_us,publication)", "contexts(COALESCE(finalized_us,captured_us),publication)")
    for statement in _SCHEMA_V1) + (
    "CREATE TABLE legacy_imports (import_id TEXT PRIMARY KEY, processed INTEGER NOT NULL, nbytes INTEGER NOT NULL, body BLOB NOT NULL)",
)


def _schema_sql(statement: str) -> str:
    # SQLite quotes a table name after RENAME. Normalize only our known names
    # and insignificant whitespace, not arbitrary SQL syntax or expressions.
    statement = re.sub(r'"(metadata|sessions|contexts)"', r'\1', statement)
    statement = " ".join(statement.split())
    return re.sub(r"\s*([(),=])\s*", r"\1", statement)


_MAINTENANCE_ITEMS = 128
_RECLAIM_PAGES = 64

_COUNTERS = frozenset({"contexts", "context_bytes", "layouts", "layout_bytes", "sessions",
    "session_bytes", "profiles", "profile_bytes", "profile_steps", "producers", "legacy_imports", "legacy_bytes"})


def _policy_json(policy: RetentionPolicy) -> str:
    raw = asdict(policy)
    raw["context_bytes"] = raw.pop("total_context_bytes")
    return _json(["jayrun.retention/2", raw]).decode("ascii")


def _sql_error(error: sqlite3.Error) -> Exception:
    code = getattr(error, "sqlite_errorcode", 0) & 255
    if code in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_SCHEMA,
                sqlite3.SQLITE_CONSTRAINT, sqlite3.SQLITE_MISMATCH, sqlite3.SQLITE_TOOBIG}:
        return StorageContractError(f"SQLite rejected data/schema (code {code})")
    if code == sqlite3.SQLITE_FULL:
        return PersistenceBackpressure("SQLite main-file/disk capacity unavailable")
    return StorageUnavailable(f"SQLite operation unavailable (code {code})")


class SQLiteBackend:
    """Private built-in handle; use Database, not a raw connection, in applications."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._db: sqlite3.Connection | None = None
        self._thread: int | None = None
        self._options: BackendOptions | None = None
        self._retention = RetentionPolicy()
        self._store_id = ""
        self._schema_version = 0

    def _connection(self, *, write: bool = False) -> sqlite3.Connection:
        if self._db is None or self._options is None:
            raise StorageContractError("backend is not open")
        if threading.get_ident() != self._thread:
            raise StorageContractError("backend handle used off its owned lane")
        if write and self._options.read_only:
            raise StorageContractError("backend is read-only")
        return self._db

    def open(self, options: BackendOptions) -> StoreStatistics:
        if self._db is not None:
            raise StorageContractError("backend already open")
        if type(options) is not BackendOptions or type(options.read_only) is not bool:
            raise StorageContractError("invalid backend options")
        if not options.read_only:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._options = options
        self._thread = threading.get_ident()
        try:
            # A read-only WAL connection can otherwise create a shared-memory
            # sidecar. Reject this unqualified journal format before sqlite opens it.
            if self.path.exists():
                with self.path.open("rb") as stream:
                    header = stream.read(100)
                if header.startswith(b"SQLite format 3\0") and len(header) >= 20 and 2 in header[18:20]:
                    raise StorageContractError("WAL-format stores require explicit conversion to the qualified rollback-journal format")
            # Explicit SQL transactions retain Python 3.11 compatibility and do
            # not depend on a future change to sqlite3's autocommit default.
            self._db = sqlite3.connect(self.path.absolute().as_uri() + ("?mode=ro" if options.read_only else "?mode=rwc"),
                uri=True, isolation_level=None, check_same_thread=True, timeout=options.limits.busy_timeout)
            con = self._db
            # Bound SQLite's own scalar/statement allocation before schema reads.
            con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, min(2**31 - 1, max(options.limits.max_context_bytes, options.limits.layout_bytes) + 1024 * 1024))
            con.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 65536)
            con.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 128)
            con.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 1024)
            con.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA trusted_schema=OFF")
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("PRAGMA cache_size=-2048")
            con.execute("PRAGMA temp_store=MEMORY")
            if options.read_only:
                con.execute("PRAGMA query_only=ON")
                with self._transaction():
                    self._validate()
            else:
                # Check before any format/journal changes, then recheck while
                # holding the serialized initialization/migration boundary.
                with self._transaction():
                    initially_empty = self._preflight()
                if initially_empty:
                    # SQLite requires this empty-file format flag before BEGIN.
                    # Competing schema creation is still serialized/rechecked below.
                    con.execute("PRAGMA auto_vacuum=INCREMENTAL")
                if con.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                    raise StorageContractError("store journal mode is not the supported DELETE policy")
                con.execute("PRAGMA synchronous=EXTRA")
                con.execute("PRAGMA journal_size_limit=0")
                if options.upgrade:
                    # SQLite's documented table-rebuild procedure requires FK
                    # checking off before BEGIN, and an explicit check before commit.
                    con.execute("PRAGMA foreign_keys=OFF")
                page_size = con.execute("PRAGMA page_size").fetchone()[0]
                if con.execute(f"PRAGMA max_page_count={options.retention.file_bytes // page_size}").fetchone()[0] * page_size > options.retention.file_bytes:
                    raise PersistenceBackpressure("existing main file exceeds the configured physical ceiling")
                with self._transaction(write=True):
                    empty = self._preflight()
                    if empty:
                        self._initialize()
                    elif self._schema_version == 1:
                        self._validate()
                        if not options.upgrade:
                            raise StorageContractError("schema 1 is read-only; call Database.upgrade() explicitly before writing")
                        self._upgrade_v1()
                    self._validate()
                    if _policy_json(options.retention) != self._metadata()["policy"]:
                        raise StorageContractError("retention policy conflicts with the shared store")
                con.execute("PRAGMA foreign_keys=ON")
                page_size = con.execute("PRAGMA page_size").fetchone()[0]
                requested = self._retention.file_bytes // page_size
                actual = con.execute(f"PRAGMA max_page_count={requested}").fetchone()[0]
                if actual > requested:
                    raise PersistenceBackpressure("existing main file exceeds the configured physical ceiling")
            with self._transaction():
                if con.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                    raise StorageContractError("SQLite integrity check failed")
            return self._statistics()
        except sqlite3.Error as error:
            self.close()
            raise _sql_error(error) from error
        except OSError as error:
            self.close()
            raise StorageUnavailable("local store path unavailable") from error
        except BaseException:
            self.close()
            raise

    def _preflight(self) -> bool:
        con = self._connection()
        app = con.execute("PRAGMA application_id").fetchone()[0]
        version = con.execute("PRAGMA user_version").fetchone()[0]
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1")]
        if app == 0 and version == 0 and not tables:
            return True
        if app != _APPLICATION_ID:
            raise StorageContractError("foreign database; no implicit conversion is performed")
        if version not in (1, _SCHEMA_VERSION):
            raise StorageContractError("unsupported database schema; explicit migration is required")
        self._schema_version = version
        return False

    def _initialize(self) -> None:
        con = self._connection(write=True)
        for statement in _SCHEMA:
            con.execute(statement)
        con.execute("INSERT INTO metadata(singleton,store_id,policy) VALUES(1,?,?)",
                    (uuid4().hex, _policy_json(self._options.retention)))
        con.execute(f"PRAGMA application_id={_APPLICATION_ID}")
        con.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
        self._schema_version = _SCHEMA_VERSION

    def _validate(self) -> None:
        con = self._connection()
        if self._preflight():
            raise StorageContractError("uninitialized store; read-only opening never creates a schema")
        actual = {r["name"]: _schema_sql(r["sql"]) for r in con.execute(
            "SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' LIMIT 64")}
        expected = {s.split()[2]: _schema_sql(s) for s in (_SCHEMA_V1 if self._schema_version == 1 else _SCHEMA)}
        if actual != expected:
            raise StorageContractError("foreign or altered database schema/index contract")
        if con.execute("PRAGMA auto_vacuum").fetchone()[0] != 2:
            raise StorageContractError("store does not have the qualified incremental-reclamation format")
        meta = self._metadata()
        try:
            document = json.loads(meta["policy"])
            if document[0] != ("jayrun.retention/1" if self._schema_version == 1 else "jayrun.retention/2"):
                raise ValueError("unknown policy")
            policy = dict(document[1])
            policy["total_context_bytes"] = policy.pop("context_bytes")
            self._retention = RetentionPolicy(**policy)
            self._store_id = meta["store_id"]
            if len(self._store_id) != 32 or any(meta[k] < 0 for k in _COUNTERS if k in meta.keys()):
                raise ValueError("invalid accounting")
        except (TypeError, ValueError, KeyError, IndexError, RecursionError, OverflowError) as error:
            raise StorageContractError("invalid retention/accounting metadata") from error
        # Counts are transactionally maintained; no table SUM/COUNT is performed
        # per publication. Exact table/accounting comparison is a qualification probe.
        if not self._within_bounds(meta):
            raise StorageContractError("stored accounting exceeds the retained policy")

    def _upgrade_v1(self) -> None:
        """Rebuild only affected tables in the caller's single write transaction."""
        con = self._connection(write=True)
        old_policy = asdict(self._retention)
        requested = asdict(self._options.retention)
        for name in ("legacy_imports", "legacy_bytes"):
            old_policy.pop(name); requested.pop(name)
        if old_policy != requested:
            raise StorageContractError("upgrade cannot silently change the existing retention policy")
        tables = {statement.split()[2]: statement for statement in _SCHEMA if statement.startswith("CREATE TABLE")}
        for name in ("metadata", "sessions", "contexts"):
            con.execute(tables[name].replace("CREATE TABLE " + name, "CREATE TABLE p5b_new_" + name, 1))
        con.execute("INSERT INTO p5b_new_metadata SELECT *,0,0 FROM metadata")
        con.execute("INSERT INTO p5b_new_sessions SELECT * FROM sessions")
        con.execute("INSERT INTO p5b_new_contexts SELECT *,NULL FROM contexts")
        for name in ("contexts", "sessions", "metadata"):
            con.execute("DROP TABLE " + name)
        for name in ("metadata", "sessions", "contexts"):
            con.execute("ALTER TABLE p5b_new_" + name + " RENAME TO " + name)
        for statement in _SCHEMA:
            if statement.startswith("CREATE INDEX") and (" ON contexts(" in statement or " ON sessions(" in statement):
                con.execute(statement)
        con.execute(tables["legacy_imports"])
        con.execute("UPDATE metadata SET policy=? WHERE singleton=1", (_policy_json(self._options.retention),))
        con.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
        self._schema_version = _SCHEMA_VERSION
        if con.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise StorageContractError("schema upgrade broke retained references")

    @contextmanager
    def _transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        con = self._connection(write=write)
        deadline = time.monotonic() + self._options.limits.operation_timeout
        con.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        try:
            con.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield con
            self._commit()
        except BaseException as error:
            if con.in_transaction:
                try:
                    con.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            if isinstance(error, sqlite3.Error):
                raise _sql_error(error) from error
            raise
        finally:
            con.set_progress_handler(None, 0)

    def _commit(self) -> None:
        self._connection().execute("COMMIT")

    def _metadata(self) -> sqlite3.Row:
        row = self._connection().execute("SELECT * FROM metadata WHERE singleton=1").fetchone()
        if row is None:
            raise StorageContractError("store metadata is missing")
        return row

    def _change(self, **deltas: int) -> None:
        if not deltas or not deltas.keys() <= _COUNTERS:
            raise AssertionError("internal accounting column")
        self._connection(write=True).execute("UPDATE metadata SET " + ",".join(f"{k}={k}+?" for k in deltas) + " WHERE singleton=1", tuple(deltas.values()))

    def _next_publication(self) -> int:
        con = self._connection(write=True)
        con.execute("UPDATE metadata SET publication=publication+1 WHERE singleton=1")
        return con.execute("SELECT publication FROM metadata WHERE singleton=1").fetchone()[0]

    def _clock(self, now: datetime) -> int:
        value = max(_micros(now), self._metadata()["clock_us"])
        self._connection(write=True).execute("UPDATE metadata SET clock_us=? WHERE singleton=1", (value,))
        return value

    def _statistics(self, meta: sqlite3.Row | None = None) -> StoreStatistics:
        if meta is None:
            meta = self._metadata()
        con = self._connection()
        page = con.execute("PRAGMA page_size").fetchone()[0]
        return StoreStatistics(**{k: meta[k] if k in meta.keys() else 0 for k in _COUNTERS}, publication=meta["publication"],
            file_bytes=page * con.execute("PRAGMA page_count").fetchone()[0],
            free_bytes=page * con.execute("PRAGMA freelist_count").fetchone()[0])

    def _within_bounds(self, m: sqlite3.Row) -> bool:
        p = self._retention
        return (m["contexts"] <= p.contexts and m["context_bytes"] + m["layout_bytes"] <= p.total_context_bytes
            and m["sessions"] <= p.sessions and m["session_bytes"] <= p.session_bytes
            and m["profiles"] <= p.profiles and m["profile_bytes"] <= p.profile_bytes
            and m["profile_steps"] <= p.profile_steps and m["producers"] <= p.producers
            and (self._schema_version == 1 or (m["legacy_imports"] <= p.legacy_imports and m["legacy_bytes"] <= p.legacy_bytes)))

    def write(self, batch: WriteBatch) -> WriteReceipt:
        con = self._connection(write=True); limits = self._options.limits
        if type(batch) is not WriteBatch or batch.items > limits.batch_items:
            raise PersistenceBackpressure("publication batch exceeds item/byte limits")
        # Bodies live only for this write attempt. Bound the retained bytes while
        # constructing them, before validating or entering the transaction. Reuse
        # them for accounting, retry digest and INSERT without caching on records
        # or across calls. Validation still runs on every attempt, including retries.
        bodies = []
        context_bytes = 0
        for entry in batch.contexts:
            body = _context_body(entry)
            context_bytes += len(body) + (len(entry.layout.body) if entry.layout else 0) + 1024
            if context_bytes > limits.batch_bytes:
                raise PersistenceBackpressure("publication batch exceeds item/byte limits")
            bodies.append(body)
        context_bodies = tuple(bodies)
        if batch._byte_size(context_bodies) > limits.batch_bytes:
            raise PersistenceBackpressure("publication batch exceeds item/byte limits")
        for entry, body in zip(batch.contexts, context_bodies, strict=True):
            _check_values(entry, self._options.value_limits)
            if len(_context_identity(entry)) + len(body) + (_layout_size(entry.layout) if entry.layout else 0) > self._retention.total_context_bytes:
                raise PersistenceBackpressure("one context and its layout exceed the store context budget")
            if len(body) > limits.max_context_bytes:
                raise StorageContractError("context body exceeds its declared byte limit")
            if entry.layout is not None and len(entry.layout.body) > limits.layout_bytes:
                raise StorageContractError("layout exceeds its declared byte limit")
        for entry in batch.sessions:
            _check_values(entry, self._options.value_limits)
            if len(_session_identity(entry)) + len(_session_body(entry)) > self._retention.session_bytes:
                raise PersistenceBackpressure("one session exceeds the store session budget")
            if len(_session_body(entry)) > limits.max_context_bytes:
                raise StorageContractError("session body exceeds its declared byte limit")
        for profile in batch.profiles:
            if len(_profile_body(profile)) + 64 > self._retention.profile_bytes or len(profile.steps) > self._retention.profile_steps:
                raise PersistenceBackpressure("one aggregate exceeds the store profile budget")
            if len(_profile_body(profile)) > limits.max_context_bytes:
                raise StorageContractError("profile aggregate exceeds its declared byte limit")
        if batch.legacy_import is not None:
            ValueSnapshot(batch.legacy_import.evidence.data, self._options.value_limits)
            if len(_legacy_import_body(batch.legacy_import)) > limits.max_context_bytes:
                raise StorageContractError("legacy import evidence exceeds its item bound")
        digest = batch._digest(context_bodies)
        with self._transaction(write=True):
            now = self._clock(datetime.now(timezone.utc))
            issued = int(batch.producer.split("-", 1)[0], 16)
            expires = issued + int(self._retention.retry_horizon_seconds * 1_000_000)
            if issued > now or expires <= now:
                raise StorageContractError("producer is future-dated or outside its absolute retry horizon")
            previous = con.execute("SELECT sequence,digest FROM producers WHERE producer=?", (batch.producer,)).fetchone()
            if previous is not None and batch.sequence <= previous["sequence"]:
                if batch.sequence == previous["sequence"] and digest != previous["digest"]:
                    raise StorageContractError("same producer sequence carries conflicting data")
                return WriteReceipt(batch.sequence, True, self._statistics())
            expected = 1 if previous is None else previous["sequence"] + 1
            if batch.sequence != expected:
                raise StorageContractError("producer batches must be contiguous and ordered")
            # Check conversion CAS before applying any accompanying diagnostic rows.
            if batch.legacy_import is not None:
                old = con.execute("SELECT processed,body FROM legacy_imports WHERE import_id=?", (batch.legacy_import.import_id,)).fetchone()
                expected = None if old is None else old["processed"]
                if expected != batch.legacy_expected:
                    raise StorageContractError("legacy import advanced concurrently; reload its checkpoint")
                if old is not None:
                    prior = _legacy_import_read(old["body"], self._options.value_limits)
                    if (prior.complete or prior.created_at != batch.legacy_import.created_at
                            or prior.encoding_key != batch.legacy_import.encoding_key
                            or prior.imported_contexts > batch.legacy_import.imported_contexts
                            or prior.unmatched_profiles > batch.legacy_import.unmatched_profiles
                            or prior.skipped > batch.legacy_import.skipped):
                        raise StorageContractError("legacy import cannot rewrite completed or earlier evidence")
            self._prune(now)
            if previous is None:
                if self._metadata()["producers"] >= self._retention.producers:
                    raise PersistenceBackpressure("unexpired producer watermark capacity exhausted")
                con.execute("INSERT INTO producers VALUES(?,?,?,?)", (batch.producer, expires, 0, ""))
                self._change(producers=1)
            for session in batch.sessions: self._put_session(session)
            # Validated immutable layout content is reusable only in this batch,
            # between retention passes while the write transaction excludes peers.
            layouts: dict[str, tuple[str | None, str | None, str, bytes]] = {}
            context_count = context_bytes = 0
            for context, body in zip(batch.contexts, context_bodies, strict=True):
                size = self._put_context(context, layouts, body)
                if size is None: continue
                context_count += 1
                context_bytes += size
            # No retention/accounting reader intervenes in the context loop.
            # Apply totals before other mutations and the second prune. Keep
            # ref updates in place: moving a body-bearing row update can change
            # overflow-page allocation and physical capacity/receipt statistics.
            if context_count:
                self._change(contexts=context_count, context_bytes=context_bytes)
            for profile in batch.profiles: self._put_profile(profile, now)
            if batch.legacy_import is not None: self._put_legacy_import(batch.legacy_import)
            self._prune(now)
            metadata = self._metadata()
            if not self._within_bounds(metadata):
                raise PersistenceBackpressure("bounded maintenance cannot satisfy retention capacity; no partial publication")
            con.execute("UPDATE producers SET sequence=?,digest=? WHERE producer=?", (batch.sequence, digest, batch.producer))
            statistics = self._statistics(metadata)
        return WriteReceipt(batch.sequence, False, statistics)

    def _put_session(self, entry: EngineSessionRecord) -> None:
        con = self._connection(write=True); h = entry.header
        body = _session_body(entry)
        identity = _session_identity(entry)
        size = len(body) + len(identity)
        start_digest = hashlib.sha256(_session_identity(entry, startup=True) + entry.settings.data + b"\0" + entry.environment.data).hexdigest()
        digest = hashlib.sha256(identity + body).hexdigest()
        previous = con.execute("SELECT startup_digest,digest,nbytes,shutdown_us FROM sessions WHERE session_id=?", (h.session_id,)).fetchone()
        if previous is not None:
            if previous["digest"] == digest: return
            if previous["startup_digest"] != start_digest or previous["shutdown_us"] is not None or h.shutdown_at is None:
                raise StorageContractError("engine session startup/finalized evidence is immutable")
            con.execute("UPDATE sessions SET shutdown_us=?,publication=?,nbytes=?,digest=?,body=? WHERE session_id=?",
                (_micros(h.shutdown_at), self._next_publication(), size, digest, body, h.session_id))
            self._change(session_bytes=size - previous["nbytes"])
        else:
            con.execute("INSERT INTO sessions(session_id,started_us,shutdown_us,engine_name,machine_name,publication,nbytes,startup_digest,digest,body) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (h.session_id, _micros(h.started_at) if h.started_at is not None else None, _micros(h.shutdown_at) if h.shutdown_at else None,
                 h.engine_name, h.engine_id, self._next_publication(), size, start_digest, digest, body))
            self._change(sessions=1, session_bytes=size)

    def _put_context(self, entry: ContextHistoryEntry,
                     layouts: dict[str, tuple[str | None, str | None, str, bytes]], body: bytes) -> int | None:
        con = self._connection(write=True); h = entry.header
        identity = _context_identity(entry)
        size = len(body) + len(identity)
        digest = hashlib.sha256(identity + body).hexdigest()
        previous = con.execute("SELECT digest FROM contexts WHERE session_id=? AND context_id=?", (h.session_id, h.context_id)).fetchone()
        if previous is not None:
            if previous[0] != digest:
                raise StorageContractError("finalized context identity already has different evidence")
            return
        layout_key = None
        if entry.layout is not None:
            layout = entry.layout; layout_key = layout._key
            content = (layout.graph_id, layout.graph_version, layout.schema_version, layout.body)
            existing = layouts.get(layout_key)
            if existing is None:
                row = con.execute("SELECT graph_id,graph_version,schema_version,body FROM layouts WHERE layout_key=?", (layout_key,)).fetchone()
                if row is not None:
                    existing = (row["graph_id"], row["graph_version"], row["schema_version"], row["body"])
            if existing is None:
                nbytes = _layout_size(layout)
                con.execute("INSERT INTO layouts VALUES(?,?,?,?,?,?,?)", (layout_key, layout.graph_id, layout.graph_version,
                    layout.schema_version, 0, nbytes, layout.body))
                self._change(layouts=1, layout_bytes=nbytes)
            elif existing != content:
                raise StorageContractError("layout digest conflict/corruption")
            layouts[layout_key] = content
            con.execute("UPDATE layouts SET refs=refs+1 WHERE layout_key=?", (layout_key,))
        con.execute("INSERT INTO contexts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (h.session_id, h.context_id,
            h.graph_id, h.graph_version, h.outcome, _micros(h.finalized_at) if h.finalized_at is not None else None, self._next_publication(),
            layout_key, entry.layout.schema_version if entry.layout else h.layout_schema, size, digest, body,
            _micros(h.captured_at) if h.captured_at is not None else None))
        con.execute("UPDATE sessions SET refs=refs+1 WHERE session_id=?", (h.session_id,))
        return size

    def _put_legacy_import(self, record: LegacyImportRecord) -> None:
        con = self._connection(write=True)
        body = _legacy_import_body(record); size = len(body) + len(record.import_id)
        old = con.execute("SELECT nbytes FROM legacy_imports WHERE import_id=?", (record.import_id,)).fetchone()
        meta = self._metadata()
        if (meta["legacy_imports"] + int(old is None) > self._retention.legacy_imports
                or meta["legacy_bytes"] + size - (old[0] if old else 0) > self._retention.legacy_bytes):
            raise PersistenceBackpressure("legacy import ledger capacity exhausted; no unsafe automatic expiry")
        con.execute("INSERT INTO legacy_imports VALUES(?,?,?,?) ON CONFLICT(import_id) DO UPDATE SET processed=excluded.processed,nbytes=excluded.nbytes,body=excluded.body",
                    (record.import_id, record.processed, size, body))
        self._change(legacy_imports=int(old is None), legacy_bytes=size - (old[0] if old else 0))

    def get_legacy_import(self, import_id: str) -> LegacyImportRecord | None:
        _text(import_id, "legacy import ID", 69)
        if self._schema_version == 1:
            return None
        with self._transaction() as con:
            row = con.execute("SELECT CASE WHEN length(body)<=? THEN body END FROM legacy_imports WHERE import_id=?",
                              (self._options.limits.max_context_bytes, import_id)).fetchone()
            if row is None:
                return None
            if row[0] is None:
                raise StorageContractError("legacy import exceeds the reader's evidence limit")
            record = _legacy_import_read(row[0], self._options.value_limits)
            if record.import_id != import_id:
                raise StorageContractError("legacy import key/body mismatch")
            return record

    def _put_profile(self, delta: ProfileAggregate, now: int) -> None:
        con = self._connection(write=True); key = delta._key
        previous = con.execute("SELECT body,nbytes,steps FROM profiles WHERE profile_key=?", (key,)).fetchone()
        merged = delta if previous is None else _profile_read(previous["body"])._merge(delta)
        body = _profile_body(merged); size = len(body) + len(key)
        if len(body) > self._options.limits.max_context_bytes:
            raise StorageContractError("merged profile exceeds the declared byte limit")
        if size > self._retention.profile_bytes:
            raise PersistenceBackpressure("merged aggregate exceeds the indivisible profile budget")
        con.execute("INSERT INTO profiles VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(profile_key) DO UPDATE SET updated_us=excluded.updated_us,publication=excluded.publication,nbytes=excluded.nbytes,body=excluded.body",
            (key, merged.graph_id, merged.graph_version, merged.configuration_key, merged.compatibility_key,
             merged.schema_version, now, self._next_publication(), len(merged.steps), size, body))
        self._change(profiles=int(previous is None), profile_bytes=size - (previous["nbytes"] if previous else 0),
                     profile_steps=len(merged.steps) if previous is None else 0)

    def _remove_context(self, row: sqlite3.Row) -> None:
        con = self._connection(write=True)
        con.execute("DELETE FROM contexts WHERE publication=?", (row["publication"],))
        con.execute("UPDATE sessions SET refs=refs-1 WHERE session_id=?", (row["session_id"],))
        self._change(contexts=-1, context_bytes=-row["nbytes"])
        if row["layout_key"] is not None:
            con.execute("UPDATE layouts SET refs=refs-1 WHERE layout_key=?", (row["layout_key"],))
            layout = con.execute("SELECT refs,nbytes FROM layouts WHERE layout_key=?", (row["layout_key"],)).fetchone()
            if layout["refs"] == 0:
                con.execute("DELETE FROM layouts WHERE layout_key=?", (row["layout_key"],))
                self._change(layouts=-1, layout_bytes=-layout["nbytes"])

    def _prune(self, now: int) -> None:
        con = self._connection(write=True); p = self._retention
        budget = _MAINTENANCE_ITEMS
        # Expired tokens are rejected from their embedded issue time even after
        # this bounded ledger deletion, and clock_us never moves backwards.
        expired = con.execute("SELECT producer FROM producers WHERE expires_us<=? ORDER BY expires_us LIMIT ?", (now, budget)).fetchall()
        for row in expired:
            con.execute("DELETE FROM producers WHERE producer=?", (row[0],)); self._change(producers=-1)
        budget -= len(expired)
        # Reuse only until a deletion changes accounting. Each retention pass
        # starts fresh, including when publication changed rows between passes.
        m = None
        cutoff = None if p.context_age_seconds is None else now - int(p.context_age_seconds * 1_000_000)
        for _ in range(budget):
            if m is None: m = self._metadata()
            pressure = m["contexts"] > p.contexts or m["context_bytes"] + m["layout_bytes"] > p.total_context_bytes
            clause, parameters = ("", ()) if pressure else (" WHERE COALESCE(finalized_us,captured_us)<?", (cutoff,))
            if not pressure and cutoff is None: break
            row = con.execute("SELECT publication,session_id,layout_key,nbytes FROM contexts" + clause + " ORDER BY COALESCE(finalized_us,captured_us),publication LIMIT 1", parameters).fetchone()
            if row is None: break
            self._remove_context(row); budget -= 1
            m = None
        cutoff = None if p.profile_age_seconds is None else now - int(p.profile_age_seconds * 1_000_000)
        for _ in range(budget):
            if m is None: m = self._metadata()
            pressure = m["profiles"] > p.profiles or m["profile_bytes"] > p.profile_bytes or m["profile_steps"] > p.profile_steps
            clause, parameters = ("", ()) if pressure else (" WHERE updated_us<?", (cutoff,))
            if not pressure and cutoff is None: break
            row = con.execute("SELECT profile_key,nbytes,steps FROM profiles" + clause + " ORDER BY updated_us,publication LIMIT 1", parameters).fetchone()
            if row is None: break
            con.execute("DELETE FROM profiles WHERE profile_key=?", (row["profile_key"],))
            self._change(profiles=-1, profile_bytes=-row["nbytes"], profile_steps=-row["steps"]); budget -= 1
            m = None
        cutoff = None if p.session_age_seconds is None else now - int(p.session_age_seconds * 1_000_000)
        for _ in range(budget):
            if m is None: m = self._metadata()
            pressure = m["sessions"] > p.sessions or m["session_bytes"] > p.session_bytes
            clause, parameters = ("", ()) if pressure else (" AND (started_us IS NULL OR shutdown_us<?)", (cutoff,))
            if not pressure and cutoff is None:
                clause, parameters = " AND started_us IS NULL", ()
            row = con.execute("SELECT session_id,nbytes FROM sessions WHERE refs=0 AND (shutdown_us IS NOT NULL OR started_us IS NULL)" + clause + " ORDER BY shutdown_us,started_us,publication LIMIT 1", parameters).fetchone()
            if row is None: break
            con.execute("DELETE FROM sessions WHERE session_id=?", (row["session_id"],))
            self._change(sessions=-1, session_bytes=-row["nbytes"]); budget -= 1
            m = None

    def maintain(self, now: datetime) -> StoreStatistics:
        con = self._connection(write=True)
        with self._transaction(write=True):
            self._prune(self._clock(now))
            if not self._within_bounds(self._metadata()):
                raise PersistenceBackpressure("retention capacity unavailable")
        # Incremental page reclamation, not a full VACUUM or a journal-policy change.
        try:
            with self._transaction(write=True):
                con.execute(f"PRAGMA incremental_vacuum({_RECLAIM_PAGES})").fetchall()
        except sqlite3.Error as error:
            raise _sql_error(error) from error
        return self._statistics()

    @staticmethod
    def _context_header(row: sqlite3.Row) -> ContextHistoryHeader:
        return ContextHistoryHeader(row["session_id"], row["context_id"], row["graph_id"], row["graph_version"],
            row["outcome"], _datetime(row["finalized_us"]) if row["finalized_us"] is not None else None,
            row["publication"], row["layout_schema"], _datetime(row["captured_us"]) if row["captured_us"] is not None else None)

    @staticmethod
    def _session_header(row: sqlite3.Row) -> EngineSessionHeader:
        return EngineSessionHeader(row["session_id"], _datetime(row["started_us"]) if row["started_us"] is not None else None, row["engine_name"], row["machine_name"],
            _datetime(row["shutdown_us"]) if row["shutdown_us"] is not None else None, row["publication"])

    def _page_cursor(self, query: HistoryQuery | SessionQuery, sessions: tuple[str, ...] | None) -> tuple[int, int, str]:
        if sessions is not None:
            if type(sessions) is not tuple or len(sessions) > 256:
                raise StorageContractError("session scope must be a tuple of at most 256 IDs")
            for s in sessions: _text(s, "session scope")
        document = asdict(query); document.pop("limit"); document.pop("cursor")
        # Preserve the P2/P4 default-query cursor fingerprint. New filters bind
        # only non-default fields; cursors cannot widen a reader's session scope.
        if not document.get("descending"):
            document.pop("descending", None)
        if document.get("search") is None:
            document.pop("search", None)
        for key in ("since", "until"):
            if document[key] is not None: document[key] = _micros(document[key])
        fingerprint = hashlib.sha256(_json([type(query).__name__, document, sorted(set(sessions)) if sessions is not None else None])).hexdigest()
        current = self._metadata()["publication"]
        if query.cursor is None:
            return current, 0, fingerprint
        try:
            raw = json.loads(urlsafe_b64decode(query.cursor.encode("ascii")))
            if type(raw) is not list or len(raw) != 5 or raw[:3] != ["jayrun.page/1", self._store_id, fingerprint]:
                raise ValueError("foreign cursor")
            boundary, last = raw[3:]
            if type(boundary) is not int or type(last) is not int or not 0 <= last <= boundary <= current:
                raise ValueError("invalid cursor position")
            return boundary, last, fingerprint
        except (TypeError, ValueError, UnicodeError, RecursionError) as error:
            raise StorageContractError("invalid/foreign page cursor or changed filters/scope") from error

    def _cursor(self, boundary: int, last: int, fingerprint: str) -> str:
        return urlsafe_b64encode(_json(["jayrun.page/1", self._store_id, fingerprint, boundary, last])).decode("ascii")

    def query_contexts(self, query: HistoryQuery, sessions: tuple[str, ...] | None = None) -> HistoryPage[ContextHistoryHeader]:
        if type(query) is not HistoryQuery or query.limit > self._options.limits.page_items:
            raise StorageContractError("context page exceeds configured item limit")
        with self._transaction() as con:
            boundary, last, fingerprint = self._page_cursor(query, sessions)
            clauses = ["publication<=?"]; args: list[object] = [boundary]
            if query.cursor is not None or not query.descending:
                clauses.append("publication<?" if query.descending else "publication>?")
                args.append(last)
            for name in ("graph_id", "graph_version", "session_id", "outcome"):
                value = getattr(query, name)
                if value is not None: clauses.append(name + "=?"); args.append(value)
            self._filter_time_scope(clauses, args, query, sessions, "finalized_us")
            if query.search is not None:
                clauses.append("(" + " OR ".join("instr(COALESCE(" + field + ",''),?)>0"
                    for field in ("context_id", "session_id", "graph_id", "graph_version")) + ")")
                args.extend([query.search] * 4)
            order = "DESC" if query.descending else "ASC"
            capture = "captured_us" if self._schema_version == 2 else "NULL AS captured_us"
            rows = con.execute("SELECT session_id,context_id,graph_id,graph_version,outcome,finalized_us,publication,layout_schema," + capture + " FROM contexts WHERE "
                + " AND ".join(clauses) + " ORDER BY publication " + order + " LIMIT ?", (*args, query.limit + 1)).fetchall()
            items: list[ContextHistoryHeader] = []; size = 0
            for row in rows[:query.limit]:
                cost = len(_json(tuple(row)))
                if size + cost > self._options.limits.page_bytes: break
                items.append(self._context_header(row)); size += cost
            if rows and not items:
                raise PersistenceBackpressure("one context header exceeds page byte budget")
            more = len(rows) > len(items)
            cursor = self._cursor(boundary, items[-1].publication, fingerprint) if more else None
            return HistoryPage(tuple(items), cursor, boundary)

    @staticmethod
    def _filter_time_scope(clauses: list[str], args: list[object], query: HistoryQuery | SessionQuery,
                           sessions: tuple[str, ...] | None, column: str) -> None:
        if query.since is not None: clauses.append(column + ">=?"); args.append(_micros(query.since))
        if query.until is not None: clauses.append(column + "<=?"); args.append(_micros(query.until))
        if sessions is not None:
            clauses.append("session_id IN (" + ",".join("?" for _ in sessions) + ")")
            args.extend(sessions)

    def get_context(self, session_id: str, context_id: str) -> ContextHistoryEntry | None:
        _text(session_id, "session_id"); _text(context_id, "context_id", 128)
        limits = self._options.limits
        with self._transaction() as con:
            capture = "c.captured_us" if self._schema_version == 2 else "NULL AS captured_us"
            row = con.execute("SELECT " + capture + """, c.session_id,c.context_id,c.graph_id,c.graph_version,c.outcome,
                c.finalized_us,c.publication,c.layout_schema,c.layout_key,
                CASE WHEN length(c.body)<=? THEN c.body END AS body,
                l.graph_id AS lgid,l.graph_version AS lversion,l.schema_version AS lschema,
                CASE WHEN length(l.body)<=? THEN l.body END AS lbody
                FROM contexts c LEFT JOIN layouts l ON c.layout_key=l.layout_key
                WHERE c.session_id=? AND c.context_id=?""", (limits.max_context_bytes, limits.layout_bytes, session_id, context_id)).fetchone()
            if row is None: return None
            if row["body"] is None: raise StorageContractError("context body exceeds the reader's limit")
            layout = None; error = None
            if row["layout_key"] is not None:
                try:
                    layout = SerializedLayout(row["lgid"], row["lversion"], row["lschema"], row["lbody"])
                    if layout._key != row["layout_key"] or (layout.graph_id, layout.graph_version) != (row["graph_id"], row["graph_version"]):
                        raise StorageContractError("layout reference identity mismatch")
                    if not layout.available: error = "layout: unsupported schema; outcome remains readable"
                except (StorageContractError, TypeError, ValueError):
                    error = "layout: invalid/missing/oversized stored description; outcome remains readable"; layout = None
            else:
                error = "layout: not captured"
            return _context_read(self._context_header(row), row["body"], layout, error, value_limits=self._options.value_limits)

    def query_sessions(self, query: SessionQuery, sessions: tuple[str, ...] | None = None) -> HistoryPage[EngineSessionHeader]:
        if type(query) is not SessionQuery or query.limit > self._options.limits.page_items:
            raise StorageContractError("session page exceeds configured item limit")
        with self._transaction() as con:
            boundary, last, fingerprint = self._page_cursor(query, sessions)
            clauses = ["publication<=?"]; args: list[object] = [boundary]
            if query.cursor is not None or not query.descending:
                clauses.append("publication<?" if query.descending else "publication>?")
                args.append(last)
            if query.engine_name is not None: clauses.append("engine_name=?"); args.append(query.engine_name)
            self._filter_time_scope(clauses, args, query, sessions, "started_us")
            order = "DESC" if query.descending else "ASC"
            rows = con.execute("SELECT session_id,started_us,shutdown_us,engine_name,machine_name,publication FROM sessions WHERE "
                + " AND ".join(clauses) + " ORDER BY publication " + order + " LIMIT ?", (*args, query.limit + 1)).fetchall()
            items: list[EngineSessionHeader] = []; size = 0
            for row in rows[:query.limit]:
                cost = len(_json(tuple(row)))
                if size + cost > self._options.limits.page_bytes: break
                items.append(self._session_header(row)); size += cost
            if rows and not items: raise PersistenceBackpressure("one session header exceeds page byte budget")
            cursor = self._cursor(boundary, items[-1].publication, fingerprint) if len(rows) > len(items) else None
            return HistoryPage(tuple(items), cursor, boundary)

    def get_session(self, session_id: str) -> EngineSessionRecord | None:
        _text(session_id, "session_id")
        with self._transaction() as con:
            row = con.execute("SELECT session_id,started_us,shutdown_us,engine_name,machine_name,publication,CASE WHEN length(body)<=? THEN body END AS body FROM sessions WHERE session_id=?",
                (self._options.limits.max_context_bytes, session_id)).fetchone()
            if row is None: return None
            if row["body"] is None: raise StorageContractError("session body exceeds the reader's limit")
            return _session_read(self._session_header(row), row["body"], value_limits=self._options.value_limits)

    def load_profiles(self, query: ProfileQuery) -> tuple[ProfileAggregate, ...]:
        if type(query) is not ProfileQuery:
            raise StorageContractError("invalid profile query")
        with self._transaction() as con:
            clauses = ["schema_version='jayrun.timing/1'"]; args: list[object] = []
            for name in ("graph_id", "compatibility_key"):
                value = getattr(query, name)
                if value is not None: clauses.append(name + "=?"); args.append(value)
            cursor = con.execute("SELECT profile_key,nbytes,CASE WHEN length(body)<=? THEN body END AS body FROM profiles WHERE "
                + " AND ".join(clauses) + " ORDER BY publication DESC LIMIT ?",
                (self._options.limits.max_context_bytes, *args, query.limit))
            results = []; size = 0
            for row in cursor:
                if size + row["nbytes"] > query.max_bytes: break
                if row["body"] is None: raise StorageContractError("profile exceeds the reader's aggregate limit")
                profile = _profile_read(row["body"])
                if profile._key != row["profile_key"]: raise StorageContractError("profile key/body mismatch")
                results.append(profile); size += row["nbytes"]
            return tuple(results)

    def close(self) -> None:
        if self._db is None:
            return
        con = self._connection()
        try:
            con.close()
        finally:
            self._db = None
            self._thread = None
