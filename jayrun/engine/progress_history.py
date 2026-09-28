from __future__ import annotations

from collections import OrderedDict
import math
import threading
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, TypeAlias
from weakref import WeakKeyDictionary, ref, ReferenceType

from ..core.graph.graph_definition import GraphDefinition

from .progress import (
    StepProgressState,
    _ProgressProfile,
    _StepProfile,
)
from .recorders.execution.records import ExecutionOutcome, ExecutionReport
from .submission import _GraphScope
from ._timing import (_TimingKey, _Unmatchable, _environment, _ordered_plan, _key,
                      _CONFIG_PREFIX, _COMPATIBILITY_PREFIX)

if TYPE_CHECKING:
    from ..persistence import Database
    from ..persistence._database import _Reservation
    from ..persistence.backend import ProfileAggregate, TimingStatistics
    from .submission import _NormalizedSubmission
    from .settings.combined_context import CombinedContextSettings
    from .settings.engine import EngineSettings

_TimingScope: TypeAlias = _GraphScope | _TimingKey | None


@dataclass(slots=True)
class _MutableStepProfile:
    observation_count: int = 0
    completion_count: int = 0
    skipped_count: int = 0
    failure_count: int = 0
    mean_seconds: float = 0.0
    squared_deviation: float = 0.0

    def observe(self, state: StepProgressState, duration: float) -> None:
        self.observation_count += 1
        if state is StepProgressState.SKIPPED:
            self.skipped_count += 1
            return
        if state in {StepProgressState.FAILED, StepProgressState.CANCELLED}:
            self.failure_count += 1
            return
        if state is not StepProgressState.COMPLETED:
            return
        self.completion_count += 1
        difference = duration - self.mean_seconds
        self.mean_seconds += difference / self.completion_count
        self.squared_deviation += difference * (duration - self.mean_seconds)


@dataclass(slots=True)
class _MutableProgressProfile:
    run_count: int
    steps: list[_MutableStepProfile]
    graph: _MutableStepProfile = field(default_factory=_MutableStepProfile)


@dataclass(slots=True)
class _PendingProfile:
    profile: _MutableProgressProfile
    reservation: _Reservation


@dataclass(frozen=True, slots=True)
class _ProgressObservation:
    step_index: int
    state: StepProgressState
    duration: float


class ProgressHistory:
    """Thread-safe timing profiles keyed by stable graph identity.

    Report batches are validated completely and applied copy-on-write, so readers
    observe either the profile before a lifecycle boundary or the profile after
    it. Optional persistence contains numeric aggregates only.
    """

    def __init__(self, *, enabled: bool = True,
                 max_profiles: int = 1024, max_step_profiles: int = 65536,
                 max_profile_bytes: int = 16 * 1024 * 1024,
                 max_pending_profiles: int = 128, max_pending_bytes: int = 8 * 1024 * 1024,
                 engine_settings: EngineSettings | None = None) -> None:
        if type(enabled) is not bool:
            raise TypeError("enabled must be a bool")
        for name, value in (("max_profiles", max_profiles), ("max_step_profiles", max_step_profiles),
                            ("max_profile_bytes", max_profile_bytes), ("max_pending_profiles", max_pending_profiles),
                            ("max_pending_bytes", max_pending_bytes)):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self._max_profiles = max_profiles
        self._max_step_profiles = max_step_profiles
        self._max_profile_bytes = max_profile_bytes
        self._max_pending_profiles = max_pending_profiles
        self._max_pending_bytes = max_pending_bytes
        self._retained_steps = self._retained_bytes = 0
        self._recency: OrderedDict[tuple[str, str] | _TimingKey | ReferenceType[GraphDefinition], int] = OrderedDict()
        self._enabled = enabled
        self._lock = threading.RLock()
        # Timing keys own bounded numeric profiles. Private declaration-scoped
        # probes remain weakly owned; estimates must not keep graphs alive.
        self._profiles: dict[tuple[str, str] | _TimingKey, _MutableProgressProfile] = {}
        self._local_profiles: WeakKeyDictionary[GraphDefinition, _MutableProgressProfile] = WeakKeyDictionary()
        self._database: Database | None = None
        self._database_owner: object | None = None
        self._pending: dict[_TimingKey, _PendingProfile] = {}
        self._pending_bytes = self._inflight_profiles = 0
        self._acknowledged_contributions = self._lost_contributions = 0
        self._unmatchable = self._remote_excluded = self._loaded_profiles = 0
        self._plan_cache: WeakKeyDictionary[GraphDefinition, tuple[bool, tuple[str, tuple[int, ...]]]] = WeakKeyDictionary()
        if engine_settings is None:
            from .settings.engine import EngineSettings
            engine_settings = EngineSettings()
        self._environment = _environment(engine_settings) if enabled else ()

    def profile_for(
        self,
        graph_scope: _TimingScope,
        step_count: int,
    ) -> _ProgressProfile:
        with self._lock:
            profile = self._profile_store(graph_scope).get(graph_scope) if self._enabled and graph_scope is not None else None
            if profile is None:
                return _ProgressProfile(
                    steps=tuple(
                        _StepProfile(step_index=index)
                        for index in range(step_count)
                    )
                )
            if len(profile.steps) != step_count:
                raise ValueError(
                    "progress history does not match the registered graph structure"
                )
            self._touch(graph_scope)
            return self._snapshot(profile)

    def commit_context(
        self,
        graph_scope: _TimingScope,
        executions: tuple[ExecutionReport, ...],
        step_count: int,
        *, graph_seconds: float | None = None,
    ) -> _ProgressProfile:
        """Atomically learn from one finalized finite context.

        graph_seconds is supplied only for a fully completed eligible local run;
        its wall elapsed remains separate from the existing per-step work.
        """
        if graph_seconds is not None and (type(graph_seconds) not in (int, float)
                or not math.isfinite(graph_seconds) or graph_seconds < 0):
            raise ValueError("graph_seconds must be finite nonnegative seconds or None")
        observations = self._observations(
            executions=executions,
            step_count=step_count,
        )
        return self._commit(graph_scope, step_count, observations, graph_seconds)

    def commit_iteration(
        self,
        graph_scope: _TimingScope,
        executions: tuple[ExecutionReport, ...],
        step_count: int,
        iteration: int,
    ) -> _ProgressProfile:
        """Atomically learn from one complete unbounded-context iteration."""
        if type(iteration) is not int or iteration < 1:
            raise ValueError("iteration must be a positive int")
        observations = self._observations(
            executions=executions,
            step_count=step_count,
            iteration=iteration,
        )
        if {observation.step_index for observation in observations} != set(
            range(step_count)
        ):
            raise ValueError(
                "completed iteration reports must cover every compiled step"
            )
        return self._commit(graph_scope, step_count, observations)

    def _commit(
        self,
        graph_scope: _TimingScope,
        step_count: int,
        observations: tuple[_ProgressObservation, ...],
        graph_seconds: float | None = None,
    ) -> _ProgressProfile:
        with self._lock:
            # Validation in _observations above is unconditional: suppressing
            # estimates must never accept invalid report identities or outcomes.
            if not self._enabled or graph_scope is None:
                return self.profile_for(graph_scope, step_count)
            store = self._profile_store(graph_scope)
            current = store.get(graph_scope)
            if current is None:
                profile = _MutableProgressProfile(
                    run_count=0,
                    steps=[_MutableStepProfile() for _ in range(step_count)],
                )
            else:
                if len(current.steps) != step_count:
                    raise ValueError(
                        "progress history does not match the registered graph structure"
                    )
                profile = self._copy_profile(current)

            for observation in observations:
                profile.steps[observation.step_index].observe(
                    observation.state,
                    observation.duration,
                )
            profile.run_count += 1
            if graph_seconds is not None:
                profile.graph.observe(StepProgressState.COMPLETED, float(graph_seconds))
            if isinstance(graph_scope, _TimingKey):
                self._contribute(graph_scope, observations, graph_seconds)
            # An indivisible oversized graph receives cold estimates next time;
            # retain neither a partial vector nor a graph-owned diagnostic cache.
            if (step_count > self._max_step_profiles
                    or self._charge(graph_scope, step_count) > self._max_profile_bytes):
                return self._snapshot(profile)
            store[graph_scope] = profile
            self._remember(graph_scope, step_count)
            self._trim()
            return self._snapshot(profile)

    def _touch(self, scope: _TimingScope) -> None:
        key = ref(scope) if isinstance(scope, GraphDefinition) else scope
        if key in self._recency:
            self._recency.move_to_end(key)

    @staticmethod
    def _charge(scope: object, steps: int) -> int:
        return scope.charge if isinstance(scope, _TimingKey) else 1024 + 256 * steps

    def _remember(self, scope: _TimingScope, steps: int) -> None:
        # The recency index must be just as weak as the local profile table.
        if isinstance(scope, GraphDefinition):
            owner = ref(self)
            def expired(key: ReferenceType[GraphDefinition]) -> None:
                history = owner()
                if history is not None:
                    with history._lock:
                        if key in history._recency:
                            steps = history._recency.pop(key)
                            history._retained_steps -= steps
                            history._retained_bytes -= history._charge(key, steps)
            key = ref(scope, expired)
        else:
            key = scope
        previous = self._recency.pop(key, None)
        if previous is not None:
            self._retained_steps -= previous
            self._retained_bytes -= self._charge(key, previous)
        self._recency[key] = steps
        self._retained_steps += steps
        self._retained_bytes += self._charge(key, steps)

    def _trim(self) -> None:
        while (len(self._recency) > self._max_profiles
               or self._retained_steps > self._max_step_profiles
               or self._retained_bytes > self._max_profile_bytes):
            scope, steps = self._recency.popitem(last=False)
            self._retained_steps -= steps
            self._retained_bytes -= self._charge(scope, steps)
            if isinstance(scope, (tuple, _TimingKey)):
                self._profiles.pop(scope, None)
            else:
                graph = scope()
                if graph is not None:
                    self._local_profiles.pop(graph, None)

    def _profile_store(
        self, graph_scope: _TimingScope,
    ) -> dict[tuple[str, str] | _TimingKey, _MutableProgressProfile] | WeakKeyDictionary[GraphDefinition, _MutableProgressProfile]:
        return self._local_profiles if isinstance(graph_scope, GraphDefinition) else self._profiles

    def flush(self) -> None:
        # Runtime shutdown invokes this on its loop after producers/resources
        # settle. Database draining here only registers numeric handoffs; it never
        # waits for a driver. The subsequent engine-owned Database barrier waits.
        if self._database is not None:
            self._drain_profiles()
            return

    @staticmethod
    def _observations(
        executions: tuple[ExecutionReport, ...],
        step_count: int,
        iteration: int | None = None,
    ) -> tuple[_ProgressObservation, ...]:
        if not isinstance(executions, tuple):
            raise TypeError("executions must be a tuple of ExecutionReport instances")
        if any(not isinstance(report, ExecutionReport) for report in executions):
            raise TypeError("executions must contain only ExecutionReport instances")
        if type(step_count) is not int or step_count < 0:
            raise ValueError("step_count must be a non-negative int")

        states = {
            ExecutionOutcome.FINISHED: StepProgressState.COMPLETED,
            ExecutionOutcome.SKIPPED: StepProgressState.SKIPPED,
            ExecutionOutcome.FAILED: StepProgressState.FAILED,
            ExecutionOutcome.CANCELLED: StepProgressState.CANCELLED,
        }
        observations: list[_ProgressObservation] = []
        identities: set[tuple[int, int]] = set()
        context_id: int | None = None
        for report in executions:
            if type(report.context_id) is not int or report.context_id < 0:
                raise ValueError("execution report has an invalid context ID")
            if context_id is None:
                context_id = report.context_id
            elif report.context_id != context_id:
                raise ValueError("execution reports belong to different contexts")
            if (
                type(report.step_index) is not int
                or report.step_index < 0
                or report.step_index >= step_count
            ):
                raise ValueError("execution report has an unknown step index")
            if type(report.iteration) is not int or report.iteration < 1:
                raise ValueError("execution report has an invalid iteration")
            if iteration is not None and report.iteration != iteration:
                raise ValueError("execution report belongs to another iteration")
            identity = (report.iteration, report.step_index)
            if identity in identities:
                raise ValueError("execution reports contain a duplicate step")
            identities.add(identity)
            if not isinstance(report.outcome, ExecutionOutcome):
                raise ValueError("execution report has an unknown outcome")
            state = states[report.outcome]
            duration = report.duration_seconds
            if isinstance(duration, bool) or not isinstance(duration, (int, float)):
                raise TypeError("execution report duration must be numeric")
            if duration < 0 or not math.isfinite(duration):
                raise ValueError(
                    "execution report duration must be finite and non-negative"
                )
            observations.append(
                _ProgressObservation(
                    step_index=report.step_index,
                    state=state,
                    duration=float(duration),
                )
            )
        return tuple(observations)

    @staticmethod
    def _copy_profile(
        profile: _MutableProgressProfile,
    ) -> _MutableProgressProfile:
        return _MutableProgressProfile(
            run_count=profile.run_count,
            graph=replace(profile.graph),
            steps=[
                _MutableStepProfile(
                    observation_count=step.observation_count,
                    completion_count=step.completion_count,
                    skipped_count=step.skipped_count,
                    failure_count=step.failure_count,
                    mean_seconds=step.mean_seconds,
                    squared_deviation=step.squared_deviation,
                )
                for step in profile.steps
            ],
        )

    @staticmethod
    def _snapshot(profile: _MutableProgressProfile) -> _ProgressProfile:
        return _ProgressProfile(
            run_count=profile.run_count,
            graph_completion_count=profile.graph.completion_count,
            graph_mean_seconds=(profile.graph.mean_seconds if profile.graph.completion_count else None),
            graph_squared_deviation=profile.graph.squared_deviation,
            steps=tuple(
                _StepProfile(
                    step_index=index,
                    observation_count=step.observation_count,
                    completion_count=step.completion_count,
                    skipped_count=step.skipped_count,
                    failure_count=step.failure_count,
                    mean_seconds=step.mean_seconds,
                    squared_deviation=step.squared_deviation,
                )
                for index, step in enumerate(profile.steps)
            ),
        )

    def timing_key(self, submission: _NormalizedSubmission,
                   settings: CombinedContextSettings) -> _TimingScope:
        """Prepare bounded metadata matching without codecs, SQL or storage waits."""
        if not self._enabled:
            return None
        graph = submission.graph
        try:
            if type(graph.version) is not str or len(graph.version.encode("utf-8")) > 256:
                raise _Unmatchable("graph version exceeds timing key bounds")
            with self._lock:
                cached = self._plan_cache.get(graph)
            if cached is None or cached[0] != graph._serializers_bound:
                bound = graph._serializers_bound
                plan = _ordered_plan(graph)
                if bound != graph._serializers_bound:
                    raise _Unmatchable("bindings changed during timing preparation")
                with self._lock:
                    if len(self._plan_cache) >= min(64, self._max_profiles):
                        self._plan_cache.pop(next(iter(self._plan_cache)), None)
                    self._plan_cache[graph] = (bound, plan)
            else:
                plan = cached[1]
            redactions = () if self._database is None else self._database.redact
            return _key(submission, settings, self._environment, plan, redactions)
        except (_Unmatchable, UnicodeError):
            with self._lock:
                self._unmatchable += 1
            return None

    def _open_database(self, database: Database, owner: object) -> None:
        """One bounded startup read; imported baselines never become new deltas."""
        self._database, self._database_owner = database, owner
        if not self._enabled:
            return
        from ..persistence.backend import ProfileQuery
        from ..persistence._database import _wait
        from ..persistence.errors import PersistenceBackpressure, StorageUnavailable
        database._bind_profile_drain(owner, self._drain_profiles)
        try:
            profiles = _wait(database._request("load_profiles", (ProfileQuery(
                limit=min(self._max_profiles, 4096), max_bytes=min(self._max_profile_bytes, 8 * 1024 * 1024)),)),
                database.limits.close_timeout)
        except (PersistenceBackpressure, StorageUnavailable, OSError) as error:
            database._record_gap(owner, error)
            if database._strict:
                raise
            return
        with self._lock:
            for stored in profiles:
                if not (stored.configuration_key.startswith(_CONFIG_PREFIX)
                        and stored.compatibility_key.startswith(_COMPATIBILITY_PREFIX)):
                    continue
                key = _TimingKey(stored.graph_id, stored.graph_version, stored.configuration_key,
                                 stored.compatibility_key, len(stored.steps))
                if key.charge > self._max_profile_bytes or len(stored.steps) > self._max_step_profiles:
                    continue
                def mutable(value: TimingStatistics) -> _MutableStepProfile:
                    return _MutableStepProfile(value.observation_count, value.completion_count,
                        value.skipped_count, value.failure_count, value.mean_seconds, value.squared_deviation)
                self._profiles[key] = _MutableProgressProfile(stored.run_count,
                    [mutable(step) for step in stored.steps], mutable(stored.graph))
                self._remember(key, key.step_count)
                self._trim()
                self._loaded_profiles += 1

    def _contribute(self, key: _TimingKey, observations: tuple[_ProgressObservation, ...],
                    graph_seconds: float | None) -> None:
        """Called under the learning lock; numeric work/reservation only, no I/O."""
        database, owner = self._database, self._database_owner
        if database is None or owner is None:
            return
        pending = self._pending.get(key)
        if pending is None:
            reservation = None
            if (len(self._pending) + self._inflight_profiles < self._max_pending_profiles
                    and self._pending_bytes + key.charge <= self._max_pending_bytes
                    and key.charge <= database.limits.batch_bytes):
                reservation = database._reserve_cache(owner, key.charge)
            if reservation is None:
                from ..persistence.errors import PersistenceBackpressure
                self._lost_contributions += 1
                database._request_profile_drain(owner)
                database._record_gap(owner, PersistenceBackpressure("timing contribution capacity exhausted"))
                return
            pending = _PendingProfile(_MutableProgressProfile(0,
                [_MutableStepProfile() for _ in range(key.step_count)]), reservation)
            self._pending[key] = pending
            self._pending_bytes += key.charge
        # Detached handoffs own earlier profile objects. Only this current pending
        # accumulator is mutated, while the lock excludes a concurrent drain.
        for observation in observations:
            pending.profile.steps[observation.step_index].observe(observation.state, observation.duration)
        pending.profile.run_count += 1
        if graph_seconds is not None:
            pending.profile.graph.observe(StepProgressState.COMPLETED, float(graph_seconds))
        if (len(self._pending) >= max(1, min(self._max_pending_profiles * 3 // 4,
                                           database.limits.pending_items // 4))
                or self._pending_bytes >= self._max_pending_bytes * 3 // 4):
            database._request_profile_drain(owner)

    @staticmethod
    def _stored(key: _TimingKey, profile: _MutableProgressProfile) -> tuple[ProfileAggregate, ...]:
        # Only invoked on the database lane, after mutable accumulator ownership
        # has been transferred. No live configuration, graph or context is closed over.
        from ..persistence.backend import ProfileAggregate, TimingStatistics
        def numeric(step: _MutableStepProfile) -> TimingStatistics:
            return TimingStatistics(step.observation_count, step.completion_count, step.skipped_count,
                step.failure_count, step.mean_seconds, step.squared_deviation)
        return (ProfileAggregate(key.graph_id, key.graph_version, key.configuration_key,
            key.compatibility_key, tuple(numeric(step) for step in profile.steps),
            profile.run_count, numeric(profile.graph)),)

    def _drain_profiles(self) -> None:
        database, owner = self._database, self._database_owner
        if database is None or owner is None:
            return
        with self._lock:
            # All deltas accepted before this lock boundary are registered before
            # it is released. Later completions build distinct pending accumulators.
            pending, self._pending = self._pending, {}
            for key, delta in pending.items():
                self._inflight_profiles += 1
                history_ref = ref(self)
                def acknowledged(committed: bool, *, charge=key.charge,
                                 count=delta.profile.run_count, history_ref=history_ref) -> None:
                    history = history_ref()
                    if history is not None:
                        with history._lock:
                            history._inflight_profiles -= 1
                            history._pending_bytes -= charge
                            if committed:
                                history._acknowledged_contributions += count
                            else:
                                history._lost_contributions += count
                try:
                    database._defer_profile(owner, delta.reservation,
                        lambda key=key, profile=delta.profile: ProgressHistory._stored(key, profile), acknowledged)
                except Exception as error:
                    acknowledged(False)
                    if delta.reservation.active and not delta.reservation.published:
                        database._discard(owner, delta.reservation)
                    database._record_gap(owner, error)

    def _timing_diagnostics(self) -> dict[str, int]:
        with self._lock:
            return {"retained_profiles": len(self._recency), "retained_steps": self._retained_steps,
                "retained_bytes": self._retained_bytes, "pending_profiles": len(self._pending),
                "inflight_profiles": self._inflight_profiles, "pending_bytes": self._pending_bytes,
                "acknowledged_contributions": self._acknowledged_contributions,
                "lost_contributions": self._lost_contributions, "unmatchable": self._unmatchable,
                "remote_excluded": self._remote_excluded, "loaded_profiles": self._loaded_profiles}
