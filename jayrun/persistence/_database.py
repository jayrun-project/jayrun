"""One bounded component lifecycle, one synchronous backend execution lane."""
from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import threading
import time
from typing import TypeVar
from uuid import uuid4
import warnings

from .backend import (Backend, BackendOptions, ProfileAggregate, ProfileQuery, StoreStatistics,
                      WriteBatch, WriteReceipt)
from .errors import (PersistenceBackpressure, PersistenceError, PersistenceFlushError,
                     PersistenceTimeout, StorageContractError, StorageUnavailable)
from .policy import DatabaseLimits, RetentionPolicy, _positive_seconds
from .values import (DiagnosticCodec, ValueLimits, ValuePath, ValueSnapshot, encode_value,
                     _codecs, _redactions)
from .records import (ContextHistoryEntry, ContextHistoryHeader, EngineSessionHeader,
                      EngineSessionRecord, HistoryPage, HistoryQuery, SessionQuery, _text, _header_size,
                      _context_body, _session_body, _check_values, _sequence,
                      LegacyImportRecord, _legacy_import_body)

Result = TypeVar("Result")


def _default_path() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        return root / "Jayrun" / "history.sqlite3"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Jayrun" / "history.sqlite3"
    state = os.environ.get("XDG_STATE_HOME")
    root = Path(state) if state and Path(state).is_absolute() else Path.home() / ".local" / "state"
    return root / "jayrun" / "history.sqlite3"


def _sync_caller() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise RuntimeError("blocking Database operation on a running event loop; use its async counterpart")


def _timeout(value: float | None, default: float) -> float:
    import math
    result = default if value is None else value
    if type(result) not in (int, float) or not math.isfinite(result) or result < 0:
        raise ValueError("timeout must be nonnegative finite seconds or None")
    return result


def _wait(future: Future[Result], timeout: float) -> Result:
    try:
        return future.result(timeout=timeout)
    except FutureTimeout as error:
        if future.done():
            raise
        raise PersistenceTimeout("wait expired; admitted work retains its lane/handle ownership") from error


async def _await(future: Future[Result], timeout: float) -> Result:
    wrapped = asyncio.wrap_future(future)
    # A canceled/timed-out caller does not cancel an admitted operation. Consume
    # late errors as well, so abandoned requests cannot emit unobserved warnings.
    wrapped.add_done_callback(lambda f: None if f.cancelled() else f.exception())
    try:
        return await asyncio.wait_for(asyncio.shield(wrapped), timeout)
    except asyncio.TimeoutError as error:
        if wrapped.done() and not wrapped.cancelled():
            raise
        raise PersistenceTimeout("wait expired; admitted work retains its lane/handle ownership") from error


@dataclass(frozen=True, slots=True)
class DatabaseStatus:
    state: str
    read_only: bool
    admitted: int
    settled: int
    failed: int
    capture_gaps: int
    first_failed: int | None
    pending_items: int
    pending_bytes: int
    detail_bytes: int
    reader_requests: int
    oldest_pending_seconds: float
    recent_errors: tuple[str, ...]
    statistics: StoreStatistics

    @property
    def healthy(self) -> bool:
        return self.state == "open" and self.first_failed is None


@dataclass(slots=True, eq=False)
class _Reservation:
    database: Database
    generation: int
    size: int
    detail: int
    created: float
    active: bool = True
    published: bool = False
    publication_number: int = 0


@dataclass(slots=True)
class _Publication:
    reservation: _Reservation
    number: int
    contexts: tuple[ContextHistoryEntry, ...]
    sessions: tuple[EngineSessionRecord, ...]
    profiles: tuple[ProfileAggregate, ...]
    byte_size: int
    items: int
    prepare_context: Callable[[], tuple[ContextHistoryEntry, bool]] | None = None
    prepare_profiles: Callable[[], tuple[ProfileAggregate, ...]] | None = None
    acknowledge: Callable[[bool], None] | None = None
    legacy_import: LegacyImportRecord | None = None
    legacy_expected: int | None = None


@dataclass(slots=True)
class _Read:
    operation: str
    arguments: tuple[object, ...]
    future: Future


class Database:
    """Explicit, inert configuration for standalone or engine-owned persistence.

    ``open()`` and ``with Database(path)`` are read-only inspection. A writable
    manual open is possible with ``open(read_only=False)``; publication remains a
    private framework operation. An engine owner uses the same lane without
    giving callers a public completion/mutation API.

    Configuration is read-only for this instance. Separate instances may share a
    qualified store under the same RetentionPolicy. No Engine integration is
    performed by constructing, importing or opening this component.
    """

    def __init__(self, path: str | os.PathLike[str] | None = None, *,
                 backend_factory: Callable[[], Backend] | None = None,
                 retention: RetentionPolicy = RetentionPolicy(),
                 limits: DatabaseLimits = DatabaseLimits(), value_limits: ValueLimits = ValueLimits(),
                 redact: tuple[ValuePath, ...] = (), codecs: tuple[DiagnosticCodec, ...] = (),
                 profile_checkpoint_interval_seconds: float | None = None) -> None:
        if path is not None and backend_factory is not None:
            raise ValueError("path and backend_factory are mutually exclusive")
        if backend_factory is not None and not callable(backend_factory):
            raise ValueError("backend_factory must be callable")
        if type(retention) is not RetentionPolicy or type(limits) is not DatabaseLimits:
            raise ValueError("retention/limits must be immutable policy objects")
        if type(value_limits) is not ValueLimits:
            raise ValueError("value_limits must be immutable ValueLimits")
        _codecs(codecs); _redactions(redact, value_limits)
        _positive_seconds("profile_checkpoint_interval_seconds", profile_checkpoint_interval_seconds, optional=True)
        self._profile_checkpoint_interval = (None if profile_checkpoint_interval_seconds is None
                                             else float(profile_checkpoint_interval_seconds))
        if path is not None:
            if not isinstance(path, (str, os.PathLike)) or not str(path).strip() or str(path) == ":memory:" or str(path).startswith("file:"):
                raise ValueError("path must identify a local file, not a connection/URI")
            configured_path = Path(path).expanduser().absolute()
        else:
            configured_path = None if backend_factory else _default_path().absolute()
        self._path = configured_path
        self._factory = backend_factory
        self._strict = True
        self._failure_callback: Callable[[BaseException], None] | None = None
        self._failure_notified = False
        self._retention = retention
        self._limits = limits
        self._value_limits = value_limits; self._redact = redact; self._codecs = codecs
        self._condition = threading.Condition()
        self._manual = object()
        self._owner: object | None = None
        self._generation = 0
        self._state = "closed"
        self._read_only = True
        self._upgrading = False
        self._thread: threading.Thread | None = None
        self._opened: Future[Database] | None = None
        self._closed: Future[None] | None = None
        self._queue: deque[_Publication | _Read] = deque()
        self._reservations: set[_Reservation] = set()
        self._pending_bytes = self._detail_bytes = self._readers = 0
        self._admitted = self._settled = self._failed = self._gaps = 0
        self._first_failed: int | None = None
        self._errors: deque[str] = deque(maxlen=8)
        self._statistics = StoreStatistics()
        self._barriers: list[tuple[int, Future[int], bool]] = []
        self._closing = False
        self._startup_unavailable = False
        self._profile_drain: Callable[[], None] | None = None
        self._profile_drain_requested = False

    @property
    def path(self) -> Path | None: return self._path
    @property
    def retention(self) -> RetentionPolicy: return self._retention
    @property
    def limits(self) -> DatabaseLimits: return self._limits

    @property
    def value_limits(self) -> ValueLimits: return self._value_limits
    @property
    def redact(self) -> tuple[ValuePath, ...]: return self._redact
    @property
    def codecs(self) -> tuple[DiagnosticCodec, ...]: return self._codecs

    @property
    def profile_checkpoint_interval_seconds(self) -> float | None:
        """Optional coarse timing-profile checkpoint seconds; None means off.

        Explicit flush, shutdown and bounded-buffer pressure still drain new
        contributions. This does not introduce a per-context profile transaction.
        """
        return self._profile_checkpoint_interval

    @property
    def status(self) -> DatabaseStatus:
        with self._condition:
            oldest = min((r.created for r in self._reservations), default=time.monotonic())
            return DatabaseStatus(self._state, self._read_only, self._admitted, self._settled,
                self._failed, self._gaps, self._first_failed, len(self._reservations),
                self._pending_bytes, self._detail_bytes, self._readers,
                max(0.0, time.monotonic() - oldest), tuple(self._errors), self._statistics)

    def _begin_open(self, owner: object, read_only: bool, *, upgrade: bool = False,
                    continue_on_failure: bool = False,
                    on_failure: Callable[[BaseException], None] | None = None) -> Future[Database]:
        if type(read_only) is not bool:
            raise ValueError("read_only must be bool")
        with self._condition:
            if self._owner is not None or self._state != "closed":
                raise StorageContractError("Database already has an active lifecycle owner")
            self._strict = not continue_on_failure
            self._failure_callback = on_failure
            self._failure_notified = False
            self._owner = owner; self._read_only = read_only; self._upgrading = upgrade; self._generation += 1
            self._state = "opening"; self._closing = False; self._startup_unavailable = False
            self._opened = Future(); self._closed = Future()
            self._queue.clear(); self._reservations.clear(); self._barriers.clear(); self._errors.clear()
            self._pending_bytes = self._detail_bytes = self._readers = 0
            self._admitted = self._settled = self._failed = self._gaps = 0
            self._first_failed = None; self._statistics = StoreStatistics()
            self._profile_drain = None; self._profile_drain_requested = False
            self._thread = threading.Thread(target=self._run, name=f"jayrun-database-{id(self):x}", daemon=True)
            self._thread.start()
            return self._opened

    def open(self, *, read_only: bool = True, timeout: float | None = None) -> Database:
        _sync_caller(); seconds = _timeout(timeout, self.limits.close_timeout)
        future = self._begin_open(self._manual, read_only)
        try:
            return _wait(future, seconds)
        except BaseException:
            self._begin_close(self._manual, allow_closed=True)
            raise

    async def open_async(self, *, read_only: bool = True, timeout: float | None = None) -> Database:
        seconds = _timeout(timeout, self.limits.close_timeout)
        future = self._begin_open(self._manual, read_only)
        try:
            return await _await(future, seconds)
        except BaseException:
            self._begin_close(self._manual, allow_closed=True)
            raise

    def upgrade(self, *, timeout: float | None = None) -> None:
        """Explicitly upgrade an existing store, then close its owned lane.

        Requires a closed component. Ordinary opens never upgrade an older
        schema; read-only inspection remains nonmutating. SQLite's transactional
        table rebuild may need temporary file space within the configured ceiling.
        Keep a backup before opting into a durable-format upgrade.
        """
        _sync_caller(); seconds = _timeout(timeout, self.limits.close_timeout)
        if self.path is not None and not self.path.is_file():
            raise StorageUnavailable("upgrade requires an existing database")
        future = self._begin_open(self._manual, False, upgrade=True)
        try:
            _wait(future, seconds)
        except BaseException:
            self._begin_close(self._manual, allow_closed=True)
            raise
        self.close(timeout=seconds)

    async def upgrade_async(self, *, timeout: float | None = None) -> None:
        """Nonblocking counterpart of upgrade; cancellation never closes an in-use handle."""
        seconds = _timeout(timeout, self.limits.close_timeout)
        if self.path is not None and not self.path.is_file():
            raise StorageUnavailable("upgrade requires an existing database")
        future = self._begin_open(self._manual, False, upgrade=True)
        try:
            await _await(future, seconds)
        except BaseException:
            self._begin_close(self._manual, allow_closed=True)
            raise
        await self.close_async(timeout=seconds)

    def _check_owner(self, owner: object, *, writable: bool = True) -> None:
        if owner is not self._owner or self._owner is None:
            raise StorageContractError("Database operation belongs to a different lifecycle owner")
        if writable and self._read_only:
            raise StorageContractError("read-only Database cannot publish or reserve capture")

    def _begin_close(self, owner: object, *, allow_closed: bool = False) -> Future[None]:
        with self._condition:
            if self._owner is None:
                if self._closed is not None and allow_closed:
                    return self._closed
                future: Future[None] = Future(); future.set_result(None); return future
            self._check_owner(owner, writable=False)
            self._closing = True
            if self._state != "opening": self._state = "closing"
            self._condition.notify_all()
            return self._closed

    def close(self, *, timeout: float | None = None) -> None:
        _sync_caller(); seconds = _timeout(timeout, self.limits.close_timeout)
        start = time.monotonic(); future = self._begin_close(self._manual, allow_closed=True)
        try:
            _wait(future, seconds)
        finally:
            thread = self._thread
            if future.done() and thread is not None:
                thread.join(max(0.0, seconds - (time.monotonic() - start)))

    async def close_async(self, *, timeout: float | None = None) -> None:
        seconds = _timeout(timeout, self.limits.close_timeout)
        await _await(self._begin_close(self._manual, allow_closed=True), seconds)

    def __enter__(self) -> Database:
        if self._owner is None: return self.open()
        with self._condition:
            self._check_owner(self._manual, writable=False)
            if self._state not in ("open", "degraded") or self._closing:
                raise StorageContractError("Database is not open")
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        try:
            self.close()
        except PersistenceError as error:
            if exc is None: raise
            exc.add_note(f"Database cleanup also failed: {type(error).__name__}; inspect database.status")
        return False

    async def __aenter__(self) -> Database:
        if self._owner is None: return await self.open_async()
        with self._condition:
            self._check_owner(self._manual, writable=False)
            if self._state not in ("open", "degraded") or self._closing:
                raise StorageContractError("Database is not open")
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        try:
            await self.close_async()
        except PersistenceError as error:
            if exc is None: raise
            exc.add_note(f"Database cleanup also failed: {type(error).__name__}; inspect database.status")
        return False

    def _failure(self, error: BaseException, number: int, *, gap: bool = False) -> None:
        # Caller holds condition. Retain bounded classification, never exception
        # tracebacks or custom backend error strings that might contain secrets.
        self._first_failed = number if self._first_failed is None else min(self._first_failed, number)
        self._failed += 1; self._gaps += int(gap)
        self._errors.append(type.__getattribute__(type(error), "__name__"))
        if not self._closing and self._state != "opening": self._state = "degraded"
        self._settle_barriers()

        if (self._strict or isinstance(error, StorageContractError)) and self._failure_callback is not None and not self._failure_notified:
            self._failure_notified = True
            classification = type.__getattribute__(type(error), "__name__")
            failure_type = StorageContractError if isinstance(error, StorageContractError) else StorageUnavailable
            self._failure_callback(failure_type(f"engine persistence failed: {classification}"))

    def _record_gap(self, owner: object, error: BaseException) -> None:
        """Record an owner-observed lost capture/drain without inventing a context."""
        with self._condition:
            self._check_owner(owner)
            self._admitted += 1
            self._failure(error, self._admitted, gap=True)

    def _reserve(self, owner: object) -> _Reservation | None:
        """Reserve essential capacity before capture/context ownership (P3 integration)."""
        with self._condition:
            self._check_owner(owner)
            if self._closing or self._state == "opening":
                raise StorageContractError("Database is not accepting capture reservations")
            unavailable = (self._startup_unavailable or len(self._reservations) >= self.limits.pending_items
                           or self._pending_bytes + self.limits.essential_bytes > self.limits.pending_bytes
                           or (self._strict and self._first_failed is not None))
            if unavailable:
                error = PersistenceBackpressure("essential persistence capacity unavailable before ownership")
                if self._strict:
                    if self._failure_callback is not None:
                        self._failure(error, 0)
                    raise error
                self._admitted += 1; self._failure(error, self._admitted, gap=True)
                return None
            reservation = _Reservation(self, self._generation, self.limits.essential_bytes, 0, time.monotonic())
            self._reservations.add(reservation); self._pending_bytes += reservation.size
            return reservation

    def _reserve_detail(self, owner: object, reservation: _Reservation, byte_size: int) -> None:
        """Reserve before detaching larger values/layouts; never retain an uncharged job."""
        if type(byte_size) is not int or byte_size < 0:
            raise ValueError("detail byte_size must be nonnegative")
        with self._condition:
            self._check_owner(owner); self._reservation(reservation)
            if reservation.published: raise StorageContractError("capture reservation already published")
            if (self._detail_bytes + byte_size > self.limits.pending_bytes - self.limits.protected_essential_bytes
                    or self._pending_bytes + byte_size > self.limits.pending_bytes):
                raise PersistenceBackpressure("detail capacity exhausted; essential reservation is retained")
            reservation.size += byte_size; reservation.detail += byte_size
            self._pending_bytes += byte_size; self._detail_bytes += byte_size

    def _capture_value(self, owner: object, reservation: _Reservation, value: object,
                       *, namespace: str | None = None,
                       encoder: Callable[..., ValueSnapshot] | None = None) -> ValueSnapshot:
        """Reserve bounded detached work before invoking any explicit codec.

        Codecs run on the producer's capture boundary, never on the storage lane
        or under this component's lock. Applications own their codec's temporary
        allocations/time. The full envelope reservation remains charged on error
        until its owner explicitly discards the capture or publishes a labeled gap.
        """
        self._reserve_detail(owner, reservation, self.value_limits.max_bytes)
        redact = self.redact if namespace is None else tuple(
            path[1:] if path else () for path in self.redact if not path or path[0] == namespace
        )
        # Private producer encoders share the same reserve-before-capture and
        # settle-after-capture boundary. They never run under this lock.
        snapshot = (encode_value if encoder is None else encoder)(
            value, limits=self.value_limits, redact=redact, codecs=self.codecs)
        with self._condition:
            self._check_owner(owner); self._reservation(reservation)
            excess = self.value_limits.max_bytes - len(snapshot.data)
            reservation.size -= excess; reservation.detail -= excess
            self._pending_bytes -= excess; self._detail_bytes -= excess
        return snapshot

    def _release_detail(self, owner: object, reservation: _Reservation, byte_size: int) -> None:
        """Release unused pre-capture allowance; never resize an admitted handoff."""
        if type(byte_size) is not int or byte_size < 0:
            raise ValueError("released detail bytes must be nonnegative")
        with self._condition:
            self._check_owner(owner); self._reservation(reservation)
            if reservation.published or byte_size > reservation.detail:
                raise StorageContractError("invalid detail allowance release")
            reservation.size -= byte_size; reservation.detail -= byte_size
            self._pending_bytes -= byte_size; self._detail_bytes -= byte_size

    def _reserve_cache(self, owner: object, byte_size: int) -> _Reservation | None:
        """Nonessential detached storage; the producer decides whether a miss is a gap."""
        if type(byte_size) is not int or byte_size < 0:
            raise ValueError("cache bytes must be nonnegative")
        with self._condition:
            self._check_owner(owner)
            if (self._closing or self._state != "open"
                    or len(self._reservations) >= self.limits.pending_items
                    or self._pending_bytes + byte_size > self.limits.pending_bytes
                    or self._detail_bytes + byte_size > self.limits.pending_bytes - self.limits.protected_essential_bytes):
                return None
            reservation = _Reservation(self, self._generation, byte_size, byte_size, time.monotonic())
            self._reservations.add(reservation)
            self._pending_bytes += byte_size; self._detail_bytes += byte_size
            return reservation

    def _defer_context(self, owner: object, reservation: _Reservation,
                       prepare: Callable[[], tuple[ContextHistoryEntry, bool]]) -> int:
        """Register one final context before readiness, without encoding under owner locks.

        The private runtime producer supplies only charged, detached facts. Its
        builder must not retain a live graph, context, exception, artifact value or
        application callback. It runs once on the existing lane, before immutable
        batch creation; uncertain-commit retries reuse the resulting exact entry.
        The bool reports required capture gaps, not a changed execution outcome.
        """
        with self._condition:
            self._check_owner(owner); self._reservation(reservation)
            if reservation.published:
                raise StorageContractError("reservation already published")
            if self._startup_unavailable:
                raise StorageUnavailable("Database startup was unavailable")
            if reservation.size > self.limits.batch_bytes:
                raise PersistenceBackpressure("deferred context exceeds batch capacity")
            self._admitted += 1; number = self._admitted
            reservation.published = True
            reservation.publication_number = number
            self._queue.append(_Publication(reservation, number, (), (), (), reservation.size, 1, prepare))
            self._condition.notify_all()
            return number

    def _bind_profile_drain(self, owner: object, drain: Callable[[], None]) -> None:
        """Install the sole engine-owned timing drain; not a public producer registry."""
        with self._condition:
            self._check_owner(owner)
            if self._profile_drain is not None:
                raise StorageContractError("a timing-profile drain is already attached")
            self._profile_drain = drain
            self._condition.notify_all()

    def _request_profile_drain(self, owner: object) -> None:
        with self._condition:
            self._check_owner(owner)
            if not self._closing:
                self._profile_drain_requested = True
                self._condition.notify_all()

    def _drain_profiles(self) -> None:
        # Never hold the Database condition while entering the timing owner.
        with self._condition:
            drain = self._profile_drain
        if drain is not None:
            drain()

    def _defer_profile(self, owner: object, reservation: _Reservation,
                       prepare: Callable[[], tuple[ProfileAggregate, ...]],
                       acknowledge: Callable[[bool], None]) -> int:
        """Transfer one charged numeric delta; encode once on the existing lane.

        Acknowledgement runs outside the Database lock after confirmed commit or
        explicit failed settlement. Retry attempts reuse the same immutable batch.
        No loaded baseline, executable graph or application callback is retained.
        """
        with self._condition:
            self._check_owner(owner); self._reservation(reservation)
            if reservation.published:
                raise StorageContractError("reservation already published")
            if self._startup_unavailable or self._closing:
                raise StorageUnavailable("Database is unavailable for a timing handoff")
            if reservation.size > self.limits.batch_bytes:
                raise PersistenceBackpressure("timing profile exceeds batch capacity")
            self._admitted += 1
            number = self._admitted
            reservation.published = True
            reservation.publication_number = number
            self._queue.append(_Publication(reservation, number, (), (), (), reservation.size, 1,
                                           prepare_profiles=prepare, acknowledge=acknowledge))
            self._condition.notify_all()
            return number

    def _reservation(self, reservation: _Reservation) -> None:
        if (type(reservation) is not _Reservation or reservation.database is not self
                or reservation.generation != self._generation or not reservation.active
                or reservation not in self._reservations):
            raise StorageContractError("inactive/foreign capture reservation")

    def _release(self, reservation: _Reservation) -> None:
        # Caller holds condition; published work owns this until settlement.
        if reservation.active:
            self._reservations.remove(reservation); reservation.active = False
            self._pending_bytes -= reservation.size; self._detail_bytes -= reservation.detail
            self._condition.notify_all()

    def _discard(self, owner: object, reservation: _Reservation, *, gap: bool = False) -> None:
        with self._condition:
            self._check_owner(owner)
            if not reservation.active: return
            self._reservation(reservation)
            if reservation.published: raise StorageContractError("cannot discard an admitted publication")
            if gap:
                self._admitted += 1
                self._failure(PersistenceBackpressure("capture omitted"), self._admitted, gap=True)
            self._release(reservation)

    def _publish(self, owner: object, reservation: _Reservation, *,
                 contexts: tuple[ContextHistoryEntry, ...] = (), sessions: tuple[EngineSessionRecord, ...] = (),
                 profiles: tuple[ProfileAggregate, ...] = (),
                 legacy_import: LegacyImportRecord | None = None,
                 legacy_expected: int | None = None) -> int:
        """Register a handoff before finalization waiters can be notified; no I/O here.

        Inputs must already be detached and their capture covered by reservation.
        Serialization used for validation/accounting executes outside the service
        lock; P3 must likewise call this outside authoritative runtime locks.
        """
        probe = WriteBatch("0-" + "0" * 32, 1, contexts, sessions, profiles, legacy_import, legacy_expected)
        size = probe.byte_size
        if probe.items > self.limits.batch_items or size > self.limits.batch_bytes:
            raise PersistenceBackpressure("publication exceeds batch capacity")
        with self._condition:
            self._check_owner(owner); self._reservation(reservation)
            if reservation.published: raise StorageContractError("reservation already published")
            if self._startup_unavailable: raise StorageUnavailable("Database startup was unavailable")
            if size > reservation.size:
                raise PersistenceBackpressure("publication exceeds reserved capture bytes; reserve detail first")
            self._admitted += 1; number = self._admitted
            reservation.published = True
            reservation.publication_number = number
            self._queue.append(_Publication(reservation, number, contexts, sessions, profiles, size, probe.items,
                                            legacy_import=legacy_import, legacy_expected=legacy_expected))
            self._condition.notify_all()
            return number

    def _request(self, operation: str, arguments: tuple[object, ...], *, generation: int | None = None) -> Future:
        if operation in ("query_contexts", "query_sessions"):
            expected = HistoryQuery if operation == "query_contexts" else SessionQuery
            if type(arguments[0]) is not expected or arguments[0].limit > self.limits.page_items:
                raise StorageContractError("query must be a bounded typed page request")
        with self._condition:
            if self._owner is None or self._state == "opening" or self._closing:
                raise StorageContractError("Database is not open for reads")
            if generation is not None and generation != self._generation:
                raise StorageContractError("borrowed reader belongs to an ended lifecycle")
            if self._startup_unavailable:
                raise StorageUnavailable("Database startup was unavailable")
            if self._readers >= self.limits.reader_requests:
                raise PersistenceBackpressure("bounded reader request capacity exhausted")
            future = Future(); self._readers += 1
            self._queue.append(_Read(operation, arguments, future)); self._condition.notify_all()
            return future

    def _barrier(self, *, report_failure: bool = True) -> Future[int]:
        with self._condition:
            if self._owner is None or self._state == "opening":
                raise StorageContractError("Database is not open")
            if self._readers >= self.limits.reader_requests:
                raise PersistenceBackpressure("bounded barrier request capacity exhausted")
            future: Future[int] = Future(); self._readers += 1
            self._barriers.append((self._admitted, future, report_failure)); self._settle_barriers()
            return future

    def _settle_barriers(self) -> None:
        pending = []
        for target, future, report_failure in self._barriers:
            if report_failure and self._first_failed is not None and self._first_failed <= target:
                future.set_exception(PersistenceFlushError(target, self._first_failed)); self._readers -= 1
            elif (self._settled >= target or (not report_failure and all(
                    not reservation.published or reservation.publication_number > target
                    for reservation in self._reservations))):
                future.set_result(target); self._readers -= 1
            else:
                pending.append((target, future, report_failure))
        self._barriers = pending

    def flush(self, *, timeout: float | None = None) -> int:
        """Cover already registered handoffs, not unfinished/future contexts."""
        _sync_caller(); seconds = _timeout(timeout, self.limits.close_timeout)
        self._drain_profiles()
        return _wait(self._barrier(), seconds)

    async def flush_async(self, *, timeout: float | None = None) -> int:
        seconds = _timeout(timeout, self.limits.close_timeout)
        # The hook only transfers bounded already-charged numeric deltas. Encoding
        # and backend work stay on the lane; no application codec runs here.
        self._drain_profiles()
        return await _await(self._barrier(), seconds)

    def reader(self, *, session_ids: tuple[str, ...] | None = None) -> DatabaseReader:
        """Borrow a read-only scope. IDs filter visibility; they are not credentials."""
        if session_ids is not None:
            if type(session_ids) is not tuple or len(session_ids) > 256:
                raise ValueError("session_ids must be a bounded tuple or None")
            for session in session_ids: _text(session, "session scope")
            session_ids = tuple(sorted(set(session_ids)))
        with self._condition:
            if self._owner is None or self._state == "opening" or self._closing:
                raise StorageContractError("Database is not open")
            return DatabaseReader(self, self._generation, session_ids)

    def query_contexts(self, query: HistoryQuery = HistoryQuery(), *, timeout: float | None = None) -> HistoryPage[ContextHistoryHeader]:
        return self.reader().query_contexts(query, timeout=timeout)

    async def query_contexts_async(self, query: HistoryQuery = HistoryQuery(), *, timeout: float | None = None) -> HistoryPage[ContextHistoryHeader]:
        return await self.reader().query_contexts_async(query, timeout=timeout)

    def get_context(self, session_id: str, context_id: str, *, timeout: float | None = None) -> ContextHistoryEntry | None:
        return self.reader().get_context(session_id, context_id, timeout=timeout)

    async def get_context_async(self, session_id: str, context_id: str, *, timeout: float | None = None) -> ContextHistoryEntry | None:
        return await self.reader().get_context_async(session_id, context_id, timeout=timeout)

    def query_sessions(self, query: SessionQuery = SessionQuery(), *, timeout: float | None = None) -> HistoryPage[EngineSessionHeader]:
        return self.reader().query_sessions(query, timeout=timeout)

    async def query_sessions_async(self, query: SessionQuery = SessionQuery(), *, timeout: float | None = None) -> HistoryPage[EngineSessionHeader]:
        return await self.reader().query_sessions_async(query, timeout=timeout)

    def get_session(self, session_id: str, *, timeout: float | None = None) -> EngineSessionRecord | None:
        return self.reader().get_session(session_id, timeout=timeout)

    async def get_session_async(self, session_id: str, *, timeout: float | None = None) -> EngineSessionRecord | None:
        return await self.reader().get_session_async(session_id, timeout=timeout)

    def get_legacy_import(self, import_id: str, *, timeout: float | None = None) -> LegacyImportRecord | None:
        return self.reader().get_legacy_import(import_id, timeout=timeout)

    async def get_legacy_import_async(self, import_id: str, *, timeout: float | None = None) -> LegacyImportRecord | None:
        return await self.reader().get_legacy_import_async(import_id, timeout=timeout)

    def _acquire(self) -> Backend:
        if self._factory is not None:
            backend = self._factory()
        else:
            from ._sqlite import SQLiteBackend
            backend = SQLiteBackend(self.path)
        # Capability/shape validation only; no connection/codec auto-adaptation.
        if not isinstance(backend, Backend):
            close = getattr(backend, "close", None)
            if callable(close): close()
            raise StorageContractError("factory did not return a conforming Backend handle")
        return backend

    def _validate_result(self, job: _Read, result: object) -> None:
        """A custom handle cannot leak a live object or silently widen a reader scope."""
        if job.operation in ("query_contexts", "query_sessions"):
            query, scope = job.arguments
            header_type = ContextHistoryHeader if job.operation == "query_contexts" else EngineSessionHeader
            if (type(result) is not HistoryPage or type(result.items) is not tuple
                    or len(result.items) > query.limit or any(type(h) is not header_type for h in result.items)):
                raise StorageContractError("backend returned an invalid historical page")
            _sequence(result.boundary); _text(result.next_cursor, "page cursor", 4096, optional=True)
            if sum(_header_size(h) for h in result.items) > self.limits.page_bytes:
                raise StorageContractError("backend page exceeds its byte limit")
            previous = result.boundary + 1 if query.descending else -1
            for header in result.items:
                ordered = header.publication < previous if query.descending else previous < header.publication
                if not ordered or not 0 <= header.publication <= result.boundary:
                    raise StorageContractError("backend page is not in requested committed publication order")
                previous = header.publication
                if scope is not None and header.session_id not in scope:
                    raise StorageContractError("backend page widened the borrowed session scope")
                names = ("graph_id", "graph_version", "session_id", "outcome") if header_type is ContextHistoryHeader else ("engine_name",)
                if any(getattr(query, name) is not None and getattr(header, name) != getattr(query, name) for name in names):
                    raise StorageContractError("backend page violates its requested filters")
                if (header_type is ContextHistoryHeader and query.search is not None
                        and not any(query.search in (getattr(header, name) or "")
                                    for name in ("context_id", "session_id", "graph_id", "graph_version"))):
                    raise StorageContractError("backend page violates its requested header search")
                instant = header.finalized_at if header_type is ContextHistoryHeader else header.started_at
                if ((query.since is not None or query.until is not None) and instant is None
                        or query.since is not None and instant < query.since
                        or query.until is not None and instant > query.until):
                    raise StorageContractError("backend page violates its requested time interval")
            if result.next_cursor is not None and not result.items:
                raise StorageContractError("backend cannot advance an empty page")
        elif job.operation == "get_context" and result is not None:
            if type(result) is not ContextHistoryEntry or (result.header.session_id, result.header.context_id) != job.arguments:
                raise StorageContractError("backend returned a different/nonhistorical context")
            _check_values(result, self.value_limits)
            if len(_context_body(result)) > self.limits.max_context_bytes or (result.layout is not None and len(result.layout.body) > self.limits.layout_bytes):
                raise StorageContractError("backend context exceeds its detail limits")
        elif job.operation == "get_session" and result is not None:
            if type(result) is not EngineSessionRecord or (result.header.session_id,) != job.arguments:
                raise StorageContractError("backend returned a different/nonhistorical session")
            _check_values(result, self.value_limits)
            if len(_session_body(result)) > self.limits.max_context_bytes:
                raise StorageContractError("backend session exceeds its detail limit")
        elif job.operation == "get_legacy_import" and result is not None:
            if type(result) is not LegacyImportRecord or (result.import_id,) != job.arguments:
                raise StorageContractError("backend returned a different/nonhistorical import")
            ValueSnapshot(result.evidence.data, self.value_limits)
            if len(_legacy_import_body(result)) > self.limits.max_context_bytes:
                raise StorageContractError("backend import exceeds its evidence limit")
        elif job.operation == "load_profiles":
            from .backend import _profile_body
            query = job.arguments[0]
            if type(result) is not tuple or len(result) > query.limit or any(type(p) is not ProfileAggregate for p in result):
                raise StorageContractError("backend returned an invalid bounded profile working set")
            if sum(len(_profile_body(p)) + 64 for p in result) > query.max_bytes:
                raise StorageContractError("backend profile working set exceeds its byte limit")
            if any((query.graph_id is not None and p.graph_id != query.graph_id) or (query.compatibility_key is not None and p.compatibility_key != query.compatibility_key) for p in result):
                raise StorageContractError("backend profile working set violates its filters")

    def _run(self) -> None:
        backend: Backend | None = None
        startup_failed = False
        try:
            for attempt in range(self.limits.max_attempts):
                try:
                    backend = self._acquire()
                    statistics = backend.open(BackendOptions(self._read_only, self.retention, self.limits, self.value_limits, self._upgrading))
                    if type(statistics) is not StoreStatistics:
                        raise StorageContractError("backend open did not return StoreStatistics")
                    break
                except BaseException as error:
                    if backend is not None:
                        try: backend.close()
                        finally: backend = None
                    if not isinstance(error, (StorageUnavailable, OSError, PersistenceBackpressure)) or attempt + 1 == self.limits.max_attempts:
                        raise
            with self._condition:
                self._statistics = statistics; self._state = "closing" if self._closing else "open"
            self._opened.set_result(self)
        except BaseException as error:
            startup_failed = True
            with self._condition:
                self._failure(error, 0)
                self._startup_unavailable = True
            if not self._strict and isinstance(error, (StorageUnavailable, OSError, PersistenceBackpressure)):
                with self._condition: self._state = "closing" if self._closing else "degraded"
                self._opened.set_result(self)
            else:
                self._opened.set_exception(error)
                with self._condition: self._closing = True
        producer, producer_sequence = self._producer(), 0
        next_maintenance = time.monotonic() + self.limits.maintenance_interval_seconds
        next_profile = (None if self.profile_checkpoint_interval_seconds is None else
                        time.monotonic() + self.profile_checkpoint_interval_seconds)
        try:
            while True:
                with self._condition:
                    checkpoint = (self._profile_drain is not None and not self._closing
                                  and (self._profile_drain_requested or
                                       (next_profile is not None and time.monotonic() >= next_profile)))
                    if checkpoint:
                        self._profile_drain_requested = False
                        next_profile = (None if self.profile_checkpoint_interval_seconds is None else
                                        time.monotonic() + self.profile_checkpoint_interval_seconds)
                if checkpoint:
                    try:
                        self._drain_profiles()
                    except BaseException as error:
                        with self._condition:
                            self._admitted += 1
                            self._failure(error, self._admitted, gap=True)
                with self._condition:
                    if self._queue:
                        job = self._queue.popleft()
                    elif self._closing and not self._reservations:
                        break
                    else:
                        wait = max(0.0, next_maintenance - time.monotonic()) if backend is not None and not self._read_only and not self._closing else None
                        if self._profile_drain is not None and not self._closing:
                            if self._profile_drain_requested:
                                wait = 0.0
                            elif next_profile is not None:
                                profile_wait = max(0.0, next_profile - time.monotonic())
                                wait = profile_wait if wait is None else min(wait, profile_wait)
                        self._condition.wait(wait)
                        job = None
                if isinstance(job, _Read):
                    try:
                        if backend is None: raise StorageUnavailable("storage handle unavailable")
                        operation = getattr(backend, job.operation)
                        result = operation(*job.arguments)
                        self._validate_result(job, result)
                        job.future.set_result(result)
                    except BaseException as error:
                        job.future.set_exception(error)
                    finally:
                        with self._condition: self._readers -= 1
                        result = None
                elif isinstance(job, _Publication):
                    jobs = [job]; size = job.byte_size; count = job.items
                    with self._condition:
                        # Batch only ready adjacent publications. Never wait to
                        # fill a batch or reorder a read past an earlier handoff.
                        while job.legacy_import is None and self._queue and isinstance(self._queue[0], _Publication):
                            candidate = self._queue[0]
                            if candidate.legacy_import is not None: break
                            if size + candidate.byte_size > self.limits.batch_bytes or count + candidate.items > self.limits.batch_items: break
                            jobs.append(self._queue.popleft()); size += candidate.byte_size; count += candidate.items
                    # Preparation is bounded and outside both Database and runtime
                    # locks. Failed detail cannot silently discard unrelated jobs.
                    ready: list[_Publication] = []
                    for pending in jobs:
                        try:
                            if pending.prepare_context is not None:
                                entry, gap = pending.prepare_context()
                                if type(entry) is not ContextHistoryEntry or type(gap) is not bool:
                                    raise StorageContractError("invalid deferred context result")
                                probe = WriteBatch("0-" + "0" * 32, 1, contexts=(entry,))
                                body = _context_body(entry)
                                if (probe._byte_size((body,)) > pending.reservation.size
                                        or len(body) > self.limits.max_context_bytes
                                        or (entry.layout is not None and len(entry.layout.body) > self.limits.layout_bytes)):
                                    raise PersistenceBackpressure("deferred context exceeded its reserved bounds")
                                pending.contexts = (entry,)
                                if gap:
                                    with self._condition:
                                        self._failure(PersistenceBackpressure("required context detail unavailable"), pending.number, gap=True)
                            if pending.prepare_profiles is not None:
                                profiles = pending.prepare_profiles()
                                if type(profiles) is not tuple or len(profiles) != 1 or type(profiles[0]) is not ProfileAggregate:
                                    raise StorageContractError("invalid deferred timing profile result")
                                probe = WriteBatch("0-" + "0" * 32, 1, profiles=profiles)
                                if probe.byte_size > pending.reservation.size:
                                    raise PersistenceBackpressure("timing profile exceeded its charged bounds")
                                pending.profiles = profiles
                            ready.append(pending)
                        except BaseException as failure:
                            with self._condition:
                                self._failure(failure, pending.number, gap=True)
                        finally:
                            body = None  # Do not retain serialized detail in an idle writer frame.
                            pending.prepare_context = None
                            pending.prepare_profiles = None
                    error: BaseException | None = None
                    batch = None
                    try:
                        if ready:
                            issued = int(producer.split("-", 1)[0], 16)
                            if time.time_ns() // 1000 - issued > self.retention.retry_horizon_seconds * 500_000:
                                producer, producer_sequence = self._producer(), 0
                            producer_sequence += 1
                            batch = WriteBatch(producer, producer_sequence,
                                tuple(c for j in ready for c in j.contexts), tuple(s for j in ready for s in j.sessions),
                                tuple(p for j in ready for p in j.profiles),
                                ready[0].legacy_import if len(ready) == 1 else None,
                                ready[0].legacy_expected if len(ready) == 1 else None)
                            if backend is None: raise StorageUnavailable("storage handle unavailable")
                            for attempt in range(self.limits.max_attempts):
                                try:
                                    receipt = backend.write(batch)
                                    if type(receipt) is not WriteReceipt or receipt.sequence != batch.sequence or type(receipt.statistics) is not StoreStatistics:
                                        raise StorageContractError("backend returned an invalid publication acknowledgement")
                                    with self._condition: self._statistics = receipt.statistics
                                    break
                                except (StorageUnavailable, OSError, PersistenceBackpressure):
                                    if attempt + 1 == self.limits.max_attempts: raise
                                    try: backend.maintain(datetime.now(timezone.utc))
                                    except (StorageUnavailable, OSError, PersistenceBackpressure): pass
                    except BaseException as failure:
                        error = failure
                        producer, producer_sequence = self._producer(), 0
                    with self._condition:
                        if error is not None: self._failure(error, ready[0].number)
                        for completed in jobs: self._release(completed.reservation)
                    # Owner callbacks cannot run under the condition: learning
                    # acquires its own lock before reserving Database capacity.
                    for completed in jobs:
                        if completed.acknowledge is not None:
                            try:
                                completed.acknowledge(error is None and any(completed is item for item in ready))
                            except BaseException as failure:
                                with self._condition:
                                    self._failure(failure, completed.number, gap=True)
                            finally:
                                completed.acknowledge = None
                    with self._condition:
                        self._settled = jobs[-1].number
                        self._settle_barriers(); self._condition.notify_all()
                    # No live or detached payload is retained by idle frame locals.
                    batch = jobs = ready = pending = probe = entry = candidate = completed = receipt = error = profiles = None
                job = None
                if (backend is not None and not self._read_only and not self._closing
                        and time.monotonic() >= next_maintenance):
                    try:
                        stats = backend.maintain(datetime.now(timezone.utc))
                        if type(stats) is not StoreStatistics: raise StorageContractError("invalid maintenance result")
                        with self._condition: self._statistics = stats
                    except BaseException as error:
                        with self._condition:
                            self._admitted += 1; self._failure(error, self._admitted)
                    next_maintenance = time.monotonic() + self.limits.maintenance_interval_seconds
        finally:
            if backend is not None:
                try:
                    backend.close()
                except BaseException as error:
                    with self._condition:
                        self._admitted += 1; self._failure(error, self._admitted)
            with self._condition:
                self._profile_drain = None; self._profile_drain_requested = False
                self._owner = None; self._state = "closed"; self._settle_barriers()
                if self._first_failed is not None and self._strict and not startup_failed:
                    self._closed.set_exception(PersistenceFlushError(self._admitted, self._first_failed, "automatic persistence drain failed"))
                else:
                    self._closed.set_result(None)
                    if self._first_failed is not None and not self._strict:
                        warnings.warn("Database closed with persistence gaps; inspect database.status", RuntimeWarning, stacklevel=1)
                self._condition.notify_all()

    @staticmethod
    def _producer() -> str:
        return f"{time.time_ns() // 1000:x}-{uuid4().hex}"


@dataclass(frozen=True, slots=True)
class DatabaseReader:
    """Borrowed historical-only scope, invalid after its open interval ends.

    There are deliberately no close, flush, publish, Stop, Abort, Resume or
    transfer methods. Python private-attribute introspection is not a sandbox.
    """

    _database: Database
    _generation: int
    _sessions: tuple[str, ...] | None
    _guard: Callable[[], None] | None = field(default=None, repr=False, compare=False)

    def __reduce__(self):
        raise TypeError("borrowed database readers cannot be serialized")

    def _check_access(self) -> None:
        if self._guard is not None:
            self._guard()
        with self._database._condition:
            if (self._generation != self._database._generation or self._database._owner is None
                    or self._database._closing):
                raise StorageContractError("borrowed reader belongs to an ended lifecycle")

    @property
    def max_page_size(self) -> int:
        """Maximum admitted header-page size for this borrowed lifecycle."""
        self._check_access()
        return self._database.limits.page_items

    def _with_guard(self, guard: Callable[[], None]) -> DatabaseReader:
        self._check_access()
        def check() -> None:
            self._check_access()
            guard()
        return DatabaseReader(self._database, self._generation, self._sessions, check)

    def _request(self, operation: str, *arguments: object) -> Future:
        self._check_access()
        return self._database._request(operation, arguments, generation=self._generation)

    def _allowed(self, session_id: str) -> bool:
        _text(session_id, "session_id")
        self._check_access()
        return self._sessions is None or session_id in self._sessions

    def query_contexts(self, query: HistoryQuery = HistoryQuery(), *, timeout: float | None = None) -> HistoryPage[ContextHistoryHeader]:
        _sync_caller()
        seconds = _timeout(timeout, self._database.limits.operation_timeout)
        result = _wait(self._request("query_contexts", query, self._sessions), seconds)
        self._check_access()
        return result

    async def query_contexts_async(self, query: HistoryQuery = HistoryQuery(), *, timeout: float | None = None) -> HistoryPage[ContextHistoryHeader]:
        seconds = _timeout(timeout, self._database.limits.operation_timeout)
        result = await _await(self._request("query_contexts", query, self._sessions), seconds)
        self._check_access()
        return result

    def get_context(self, session_id: str, context_id: str, *, timeout: float | None = None) -> ContextHistoryEntry | None:
        _sync_caller(); _text(context_id, "context_id", 128)
        seconds = _timeout(timeout, self._database.limits.operation_timeout)
        if not self._allowed(session_id): return None
        result = _wait(self._request("get_context", session_id, context_id), seconds)
        self._check_access()
        return result

    async def get_context_async(self, session_id: str, context_id: str, *, timeout: float | None = None) -> ContextHistoryEntry | None:
        _text(context_id, "context_id", 128)
        seconds = _timeout(timeout, self._database.limits.operation_timeout)
        if not self._allowed(session_id): return None
        result = await _await(self._request("get_context", session_id, context_id), seconds)
        self._check_access()
        return result

    def query_sessions(self, query: SessionQuery = SessionQuery(), *, timeout: float | None = None) -> HistoryPage[EngineSessionHeader]:
        _sync_caller()
        seconds = _timeout(timeout, self._database.limits.operation_timeout)
        result = _wait(self._request("query_sessions", query, self._sessions), seconds)
        self._check_access()
        return result

    async def query_sessions_async(self, query: SessionQuery = SessionQuery(), *, timeout: float | None = None) -> HistoryPage[EngineSessionHeader]:
        seconds = _timeout(timeout, self._database.limits.operation_timeout)
        result = await _await(self._request("query_sessions", query, self._sessions), seconds)
        self._check_access()
        return result

    def get_session(self, session_id: str, *, timeout: float | None = None) -> EngineSessionRecord | None:
        _sync_caller()
        seconds = _timeout(timeout, self._database.limits.operation_timeout)
        if not self._allowed(session_id): return None
        result = _wait(self._request("get_session", session_id), seconds)
        self._check_access()
        return result

    async def get_session_async(self, session_id: str, *, timeout: float | None = None) -> EngineSessionRecord | None:
        seconds = _timeout(timeout, self._database.limits.operation_timeout)
        if not self._allowed(session_id): return None
        result = await _await(self._request("get_session", session_id), seconds)
        self._check_access()
        return result


    def get_legacy_import(self, import_id: str, *, timeout: float | None = None) -> LegacyImportRecord | None:
        """Inspect import diagnostics only with an explicitly unrestricted reader.

        An import can span legacy partitions, so an engine-session grant cannot
        read its ledger or old unmatched profiles. IDs never enlarge that scope.
        """
        _sync_caller(); _text(import_id, "legacy import ID", 69)
        seconds = _timeout(timeout, self._database.limits.operation_timeout)
        self._check_access()
        if self._sessions is not None:
            return None
        result = _wait(self._request("get_legacy_import", import_id), seconds)
        self._check_access()
        return result

    async def get_legacy_import_async(self, import_id: str, *, timeout: float | None = None) -> LegacyImportRecord | None:
        _text(import_id, "legacy import ID", 69)
        seconds = _timeout(timeout, self._database.limits.operation_timeout)
        self._check_access()
        if self._sessions is not None:
            return None
        result = await _await(self._request("get_legacy_import", import_id), seconds)
        self._check_access()
        return result
