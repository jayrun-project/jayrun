"""Small synchronous extension contract. The Database owns each acquired handle.

Factories create an inert handle on its lane. open/use/close are serial on that
same thread. A factory that fails before returning must release its own partial
acquisition. Database closes every returned handle even when open fails.
Native loop-bound clients need their own correctly owned adapter, not a nested
loop or an attempt to block the caller's event loop.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
import hashlib
import json
import math
from typing import Protocol, runtime_checkable

from .errors import StorageContractError
from .policy import DatabaseLimits, RetentionPolicy
from .values import ValueLimits
from .records import (ContextHistoryEntry, ContextHistoryHeader, EngineSessionHeader,
                      EngineSessionRecord, HistoryPage, HistoryQuery, SessionQuery,
                      _context_body, _graph_id, _json, _session_body, _text,
                      LegacyImportRecord, _legacy_import_body, _sequence)


@dataclass(frozen=True, slots=True)
class BackendOptions:
    read_only: bool
    retention: RetentionPolicy
    limits: DatabaseLimits
    value_limits: ValueLimits = ValueLimits()
    upgrade: bool = False

    def __post_init__(self) -> None:
        if (type(self.read_only) is not bool or type(self.retention) is not RetentionPolicy
                or type(self.limits) is not DatabaseLimits or type(self.value_limits) is not ValueLimits
                or type(self.upgrade) is not bool or (self.read_only and self.upgrade)):
            raise StorageContractError("invalid typed backend options")


@dataclass(frozen=True, slots=True)
class StoreStatistics:
    contexts: int = 0
    context_bytes: int = 0
    layouts: int = 0
    layout_bytes: int = 0
    sessions: int = 0
    session_bytes: int = 0
    profiles: int = 0
    profile_bytes: int = 0
    profile_steps: int = 0
    producers: int = 0
    publication: int = 0
    file_bytes: int = 0
    free_bytes: int = 0
    legacy_imports: int = 0
    legacy_bytes: int = 0


    def __post_init__(self) -> None:
        if any(type(getattr(self, field.name)) is not int or not 0 <= getattr(self, field.name) < 2**63 for field in fields(self)):
            raise StorageContractError("storage counters must be nonnegative signed-64 integers")
        if self.free_bytes > self.file_bytes:
            raise StorageContractError("free pages cannot exceed physical main-file allocation")


@dataclass(frozen=True, slots=True)
class TimingStatistics:
    """Same count/mean/squared-deviation meaning as existing engine step profiles.

    This is the backend's numeric transfer shape, not a new estimator or owner.
    A whole-graph statistic may be carried separately from ordered step work.
    """

    observation_count: int = 0
    completion_count: int = 0
    skipped_count: int = 0
    failure_count: int = 0
    mean_seconds: float = 0.0
    squared_deviation: float = 0.0

    def __post_init__(self) -> None:
        counts = (self.observation_count, self.completion_count, self.skipped_count, self.failure_count)
        if any(type(n) is not int or not 0 <= n < 2**63 for n in counts):
            raise StorageContractError("timing counts must be nonnegative signed-64 integers")
        if sum(counts[1:]) > self.observation_count:
            raise StorageContractError("timing support exceeds observations")
        for value in (self.mean_seconds, self.squared_deviation):
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise StorageContractError("timing values must be finite and nonnegative")
        if self.completion_count == 0 and (self.mean_seconds != 0 or self.squared_deviation != 0):
            raise StorageContractError("empty timing aggregate has nonzero moments")

    def _merge(self, other: TimingStatistics) -> TimingStatistics:
        count = self.completion_count + other.completion_count
        difference = other.mean_seconds - self.mean_seconds
        mean = (self.mean_seconds + difference * other.completion_count / count) if count else 0.0
        m2 = self.squared_deviation + other.squared_deviation
        if count:
            m2 += difference * difference * self.completion_count * other.completion_count / count
        return TimingStatistics(self.observation_count + other.observation_count, count,
            self.skipped_count + other.skipped_count, self.failure_count + other.failure_count, mean, m2)


@dataclass(frozen=True, slots=True)
class ProfileAggregate:
    """Typed stored aggregate/delta, keyed by explicit graph/config/compatibility."""

    graph_id: str
    graph_version: str
    configuration_key: str
    compatibility_key: str
    steps: tuple[TimingStatistics, ...]
    run_count: int = 0
    graph: TimingStatistics = TimingStatistics()
    schema_version: str = "jayrun.timing/1"

    def __post_init__(self) -> None:
        _graph_id(self.graph_id)
        if self.graph_id is None or not self.graph_id.startswith("jrg1:"):
            raise StorageContractError("profiles require the supported P1 intrinsic identity")
        for name in ("graph_version", "configuration_key", "compatibility_key", "schema_version"):
            _text(getattr(self, name), name, 256, empty=name == "graph_version")
        if self.schema_version != "jayrun.timing/1":
            raise StorageContractError("unsupported timing schema")
        if type(self.steps) is not tuple or len(self.steps) > 65_536 or any(type(s) is not TimingStatistics for s in self.steps):
            raise StorageContractError("steps must be a bounded ordered tuple of TimingStatistics")
        if type(self.graph) is not TimingStatistics or type(self.run_count) is not int or not 0 <= self.run_count < 2**63:
            raise StorageContractError("invalid graph aggregate/run count")

    @property
    def _key(self) -> str:
        return hashlib.sha256(_json([self.graph_id, self.graph_version, self.configuration_key,
                                    self.compatibility_key, self.schema_version])).hexdigest()

    def _merge(self, other: ProfileAggregate) -> ProfileAggregate:
        if self._key != other._key or len(self.steps) != len(other.steps):
            raise StorageContractError("profile compatibility/ordered step count mismatch")
        return ProfileAggregate(self.graph_id, self.graph_version, self.configuration_key,
            self.compatibility_key, tuple(a._merge(b) for a, b in zip(self.steps, other.steps, strict=True)),
            self.run_count + other.run_count, self.graph._merge(other.graph), self.schema_version)


def _profile_body(profile: ProfileAggregate) -> bytes:
    def stats(s: TimingStatistics) -> list[int | float]:
        return [s.observation_count, s.completion_count, s.skipped_count, s.failure_count, s.mean_seconds, s.squared_deviation]
    return _json([profile.schema_version, profile.graph_id, profile.graph_version, profile.configuration_key,
                  profile.compatibility_key, profile.run_count, stats(profile.graph), [stats(s) for s in profile.steps]])


def _profile_read(body: bytes) -> ProfileAggregate:
    try:
        r = json.loads(body)
        if type(r) is not list or len(r) != 8:
            raise ValueError("invalid profile")
        return ProfileAggregate(r[1], r[2], r[3], r[4], tuple(TimingStatistics(*s) for s in r[7]), r[5], TimingStatistics(*r[6]), r[0])
    except (TypeError, ValueError, RecursionError, IndexError) as error:
        raise StorageContractError("invalid profile body") from error


@dataclass(frozen=True, slots=True)
class ProfileQuery:
    graph_id: str | None = None
    compatibility_key: str | None = None
    limit: int = 1024
    max_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        _graph_id(self.graph_id)
        _text(self.compatibility_key, "compatibility_key", optional=True)
        if type(self.limit) is not int or not 1 <= self.limit <= 4096:
            raise StorageContractError("profile load limit must be 1..4096")
        if type(self.max_bytes) is not int or not 1 <= self.max_bytes <= 32 * 1024 * 1024:
            raise StorageContractError("profile load byte limit must be 1..32 MiB")


@dataclass(frozen=True, slots=True)
class WriteBatch:
    """An ordered retryable producer batch; only the owner invokes Backend.write.

    producer is '<issued-UTC-microseconds-in-hex>-<32-lowercase-UUID-hex>'. Its
    absolute retry horizon is part of store policy. Sequence begins at one and
    is contiguous. Retrying a covered older sequence never reapplies its data.
    """

    producer: str
    sequence: int
    contexts: tuple[ContextHistoryEntry, ...] = ()
    sessions: tuple[EngineSessionRecord, ...] = ()
    profiles: tuple[ProfileAggregate, ...] = ()
    legacy_import: LegacyImportRecord | None = None
    legacy_expected: int | None = None

    def __post_init__(self) -> None:
        import re
        if type(self.producer) is not str or re.fullmatch(r"[0-9a-f]{1,16}-[0-9a-f]{32}", self.producer) is None:
            raise StorageContractError("invalid ordered producer identity")
        if type(self.sequence) is not int or not 1 <= self.sequence < 2**63:
            raise StorageContractError("producer sequence must be positive signed-64")
        for name, cls in (("contexts", ContextHistoryEntry), ("sessions", EngineSessionRecord), ("profiles", ProfileAggregate)):
            value = getattr(self, name)
            if type(value) is not tuple or len(value) > 1024 or any(type(v) is not cls for v in value):
                raise StorageContractError(f"invalid detached {name} batch")
        if self.legacy_import is not None:
            if type(self.legacy_import) is not LegacyImportRecord:
                raise StorageContractError("invalid legacy import checkpoint")
            if self.legacy_expected is not None:
                _sequence(self.legacy_expected)
                if self.legacy_import.processed < self.legacy_expected:
                    raise StorageContractError("legacy import progress cannot move backwards")
            if self.profiles:
                raise StorageContractError("legacy diagnostics cannot become active timing samples")
        elif self.legacy_expected is not None:
            raise StorageContractError("legacy expectation without a checkpoint")
        if not self.items:
            raise StorageContractError("empty publication batch")

    @property
    def items(self) -> int:
        return len(self.contexts) + len(self.sessions) + len(self.profiles) + int(self.legacy_import is not None)

    @property
    def byte_size(self) -> int:
        return self._byte_size()

    def _byte_size(self, context_bodies: tuple[bytes, ...] | None = None) -> int:
        return sum(len(_context_body(c) if context_bodies is None else context_bodies[i])
                   + (len(c.layout.body) if c.layout else 0) + 1024 for i, c in enumerate(self.contexts)) + sum(
            len(_session_body(s)) + 1024 for s in self.sessions) + sum(len(_profile_body(p)) + 1024 for p in self.profiles) + (len(_legacy_import_body(self.legacy_import)) + 1024 if self.legacy_import else 0)

    @property
    def digest(self) -> str:
        return self._digest()

    def _digest(self, context_bodies: tuple[bytes, ...] | None = None) -> str:
        h = hashlib.sha256()
        def part(data: bytes) -> None:
            h.update(len(data).to_bytes(8, "big")); h.update(data)
        for s in self.sessions:
            part(_json([s.header.session_id, s.header.started_at.isoformat() if s.header.started_at is not None else None, s.header.engine_name,
                        s.header.engine_id, s.header.shutdown_at.isoformat() if s.header.shutdown_at else None]))
            part(_session_body(s))
        for i, c in enumerate(self.contexts):
            part(_json([c.header.session_id, c.header.context_id, c.header.graph_id, c.header.graph_version,
                        c.header.outcome, c.header.finalized_at.isoformat() if c.header.finalized_at is not None else None, c.layout._key if c.layout else None]))
            if c.header.captured_at is not None:
                part(_json(["captured_at", c.header.captured_at.isoformat()]))
            part(_context_body(c) if context_bodies is None else context_bodies[i])
        for p in self.profiles: part(_profile_body(p))
        if self.legacy_import is not None:
            part(_json(["legacy", self.legacy_expected]))
            part(_legacy_import_body(self.legacy_import))
        return h.hexdigest()


@dataclass(frozen=True, slots=True)
class WriteReceipt:
    sequence: int
    duplicate: bool
    statistics: StoreStatistics


@runtime_checkable
class Backend(Protocol):
    """Backend implementations must meet the P2 domain conformance contract.

    No engine/live objects, SQL handles or application capabilities cross this
    boundary. Headers/pages exclude bodies/layouts. get_context is an atomic
    bounded detail+exact-layout read. write atomically merges all its domains and
    advances its durable watermark, including on an uncertain-commit retry.
    """

    def open(self, options: BackendOptions) -> StoreStatistics: ...
    def write(self, batch: WriteBatch) -> WriteReceipt: ...
    def query_contexts(self, query: HistoryQuery, sessions: tuple[str, ...] | None = None) -> HistoryPage[ContextHistoryHeader]: ...
    def get_context(self, session_id: str, context_id: str) -> ContextHistoryEntry | None: ...
    def query_sessions(self, query: SessionQuery, sessions: tuple[str, ...] | None = None) -> HistoryPage[EngineSessionHeader]: ...
    def get_session(self, session_id: str) -> EngineSessionRecord | None: ...
    def get_legacy_import(self, import_id: str) -> LegacyImportRecord | None: ...
    def load_profiles(self, query: ProfileQuery) -> tuple[ProfileAggregate, ...]: ...
    def maintain(self, now: datetime) -> StoreStatistics: ...
    def close(self) -> None: ...
