from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from time import perf_counter

from ..core.graph.compiled_graph import (
    CompiledOperatorStep,
    CompiledResourceStep,
    CompiledStep,
)
from .registry.context_state import ContextState
from .submission import _GraphScope


class StepProgressState(Enum):
    """Current execution state of one compiled graph step."""

    PENDING = "pending"
    RUNNING = "running"
    PLACEMENT_WAITING = "placement_waiting"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """Whether this step has finished for the current graph iteration."""
        return self in {
            StepProgressState.COMPLETED,
            StepProgressState.SKIPPED,
            StepProgressState.FAILED,
            StepProgressState.CANCELLED,
        }


@dataclass(frozen=True, slots=True)
class StepProgress:
    """Immutable progress for one compiled graph step.

    Attributes:
        step_index: Stable step index within the compiled graph version.
        step_kind: ``"operator"`` or ``"resource"``.
        step_name: Display name of the operator or resource.
        layout_position: Graph-layout position used by visualization adapters.
        state: Current state for this iteration.
        iteration: Context iteration represented by this value.
        execution_count: Executions attempted within the current step session.
        elapsed_seconds: Monotonic active execution time accumulated by the step.
        estimated_seconds: Learned duration estimate, when one is available.
    """

    step_index: int
    step_kind: str
    step_name: str
    layout_position: tuple[int, int]
    state: StepProgressState
    iteration: int
    execution_count: int
    elapsed_seconds: float
    estimated_seconds: float | None


@dataclass(frozen=True, slots=True)
class ProgressSnapshot:
    """Immutable current and estimated progress for one context.

    The snapshot separates observed execution facts from estimates learned from
    compatible completed steps of the same ordered graph declaration. Completed live steps
    refine only this context's estimate; durable history is updated from execution
    reports once at finite-context finalization or at each completed unbounded
    iteration. Estimates can move backward when routing or runtime behavior
    changes. ``estimated_fraction`` and
    ``estimated_remaining_seconds`` are ``None`` when the context has no finite
    completion boundary or insufficient timing information.

    Terminal fractions are 1.0 for every outcome: execution has ended, not
    necessarily succeeded. Cold finite estimates use equal step weights.
    Timing profiles match selected resolved configurations and supported ordered
    execution descriptors. Artifact contents, transient contention and physical
    hardware equivalence are not inferred. They are estimates, not guarantees or
    execution history; the deprecated history-file route keeps its legacy matching.

    Attributes:
        context_id: Probabilistically unique 62-bit logical context identifier.
        graph_key: Registered graph key, or ``None`` for a local graph.
        graph_version: Version of the submitted graph.
        revision: Monotonic progress revision owned by the context instance.
        observed_at: UTC time at which this snapshot was materialized.
        context_state: Current context lifecycle state.
        iteration: Number of the current iteration, or zero before execution.
        max_iterations: Configured iteration limit, or ``None`` when unbounded.
        steps: Step-level progress for the current iteration.
        elapsed_seconds: Measured time since execution started, including local
            pauses and waits. Preserved across ownership changes; unobserved
            transport/downtime is not reconstructed from wall clocks.
        estimated_fraction: Estimated completion in the inclusive range 0 to 1.
        estimated_remaining_seconds: Sum of estimated remaining step work in
            seconds, not a wall-clock ETA for concurrent execution.
        confidence: Sample support in the inclusive range 0 to 1, saturating at
            five completed samples per step; not a probability of accuracy.
        sample_count: Completed-step timing samples used by the estimate.
    """

    context_id: int
    graph_key: str | None
    graph_version: str
    revision: int
    observed_at: datetime
    context_state: ContextState
    iteration: int
    max_iterations: int | None
    steps: tuple[StepProgress, ...]
    elapsed_seconds: float
    estimated_fraction: float | None
    estimated_remaining_seconds: float | None
    confidence: float
    sample_count: int

    @property
    def completed_steps(self) -> int:
        """Number of completed or skipped steps in the current iteration."""
        return sum(
            step.state
            in {StepProgressState.COMPLETED, StepProgressState.SKIPPED}
            for step in self.steps
        )

    @property
    def active_steps(self) -> int:
        """Number of running or placement-waiting steps."""
        return sum(
            step.state
            in {
                StepProgressState.RUNNING,
                StepProgressState.PLACEMENT_WAITING,
            }
            for step in self.steps
        )


@dataclass(frozen=True, slots=True)
class _StepProfile:
    step_index: int
    observation_count: int = 0
    completion_count: int = 0
    skipped_count: int = 0
    failure_count: int = 0
    mean_seconds: float = 0.0
    squared_deviation: float = 0.0


@dataclass(frozen=True, slots=True)
class _ProgressProfile:
    run_count: int = 0
    steps: tuple[_StepProfile, ...] = ()
    graph_completion_count: int = 0
    graph_mean_seconds: float | None = None
    graph_squared_deviation: float = 0.0

    def step(self, step_index: int) -> _StepProfile:
        if 0 <= step_index < len(self.steps):
            profile = self.steps[step_index]
            if profile.step_index == step_index:
                return profile
        return _StepProfile(step_index=step_index)


@dataclass(frozen=True, slots=True)
class _ProgressUpdate:
    context_id: int
    revision: int
    step_index: int
    state: StepProgressState
    iteration: int
    execution_count: int
    elapsed_seconds: float

    def __post_init__(self) -> None:
        if type(self.context_id) is not int or self.context_id < 0:
            raise ValueError("context_id must be a non-negative int")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive int")
        if type(self.step_index) is not int or self.step_index < 0:
            raise ValueError("step_index must be a non-negative int")
        if not isinstance(self.state, StepProgressState):
            raise TypeError("state must be a StepProgressState instance")
        if type(self.iteration) is not int or self.iteration < 0:
            raise ValueError("iteration must be a non-negative int")
        if type(self.execution_count) is not int or self.execution_count < 0:
            raise ValueError("execution_count must be a non-negative int")
        if not isinstance(self.elapsed_seconds, (int, float)) or isinstance(
            self.elapsed_seconds,
            bool,
        ):
            raise TypeError("elapsed_seconds must be numeric")
        if self.elapsed_seconds < 0 or not math.isfinite(self.elapsed_seconds):
            raise ValueError("elapsed_seconds must be finite and non-negative")


@dataclass(slots=True)
class _MutableStepProgress:
    step_index: int
    step_kind: str
    step_name: str
    layout_position: tuple[int, int]
    state: StepProgressState = StepProgressState.PENDING
    iteration: int = 0
    execution_count: int = 0
    elapsed_seconds: float = 0.0
    active_started_at: float | None = None


@dataclass(slots=True)
class _LocalStepProfile:
    completion_count: int = 0
    mean_seconds: float = 0.0

    def observe(self, duration: float) -> None:
        self.completion_count += 1
        self.mean_seconds += (
            duration - self.mean_seconds
        ) / self.completion_count


class _ProgressTracker:
    def __init__(
        self,
        *,
        context_id: int,
        graph_scope: _GraphScope,
        graph_version: str,
        compiled_steps: tuple[CompiledStep, ...],
        max_iterations: int | None,
        profile: _ProgressProfile,
        learn_progress: bool = True,
    ) -> None:
        self._context_id = context_id
        self._graph_key = graph_scope[0] if isinstance(graph_scope, tuple) else None
        self._graph_version = graph_version
        self._max_iterations = max_iterations
        self._profile = profile
        self._learn_progress = learn_progress
        self._revision = 0
        self._source_revision = 0
        self._context_state = ContextState.SUBMITTED
        self._iteration = 0
        self._started_at: datetime | None = None
        self._finished_at: datetime | None = None
        self._started_counter: float | None = None
        self._finished_counter: float | None = None
        self._elapsed_offset = 0.0
        self._local_profiles: dict[int, _LocalStepProfile] = {}
        self._steps = tuple(
            self._step_progress(index, step)
            for index, step in enumerate(compiled_steps)
        )

    @property
    def snapshot(self) -> ProgressSnapshot:
        return self._materialize()

    def restore_timing(self, previous: ProgressSnapshot) -> None:
        """Carry detached measured time across a tracker/ownership boundary.

        Step states belong to the new execution attempt and are not restored.
        No wall-clock subtraction can establish elapsed time between machines.
        """
        if previous.context_id != self._context_id:
            raise ValueError("progress snapshot belongs to another context")
        self._elapsed_offset = previous.elapsed_seconds
        self._started_counter = perf_counter() if self._started_at is not None else None
        self._finished_counter = None
        self._revision = max(self._revision, previous.revision) + 1

    def replace_profile(self, profile: _ProgressProfile) -> None:
        if not isinstance(profile, _ProgressProfile):
            raise TypeError("profile must be a progress profile")
        if len(profile.steps) != len(self._steps):
            raise ValueError("progress profile does not match the compiled graph")
        if any(
            step.step_index != index
            for index, step in enumerate(profile.steps)
        ):
            raise ValueError("progress profile step indices are inconsistent")
        self._profile = profile
        self._local_profiles.clear()
        self._refresh()

    def change_context(
        self,
        *,
        state: ContextState,
        iteration: int,
        started_at: datetime | None,
        finished_at: datetime | None,
    ) -> None:
        if iteration != self._iteration:
            if self._iteration == 0 and iteration == 1:
                for step in self._steps:
                    step.iteration = 1
            else:
                for step in self._steps:
                    step.state = StepProgressState.PENDING
                    step.iteration = iteration
                    step.execution_count = 0
                    step.elapsed_seconds = 0.0
                    step.active_started_at = None
            self._iteration = iteration
        self._context_state = state
        if self._started_at is None and started_at is not None:
            self._started_counter = perf_counter()
        if self._finished_at is None and finished_at is not None:
            self._finished_counter = perf_counter()
        self._started_at = started_at
        self._finished_at = finished_at
        self._refresh()

    def apply(self, update: _ProgressUpdate) -> bool:
        if update.context_id != self._context_id:
            raise ValueError("progress update belongs to another context")
        if update.revision <= self._source_revision:
            return False
        if update.step_index >= len(self._steps):
            raise ValueError("progress update has an unknown step index")
        if update.iteration < self._iteration:
            return False
        if update.iteration > self._iteration:
            raise ValueError("progress update is ahead of the context iteration")

        step = self._steps[update.step_index]
        previous_state = step.state
        previous_elapsed = step.elapsed_seconds
        step.state = update.state
        step.iteration = update.iteration
        step.execution_count = update.execution_count
        step.elapsed_seconds = float(update.elapsed_seconds)
        step.active_started_at = (
            perf_counter()
            if update.state is StepProgressState.RUNNING
            else None
        )
        self._source_revision = update.revision

        if (
            self._learn_progress
            and update.state is StepProgressState.COMPLETED
            and previous_state is not StepProgressState.COMPLETED
            and step.elapsed_seconds >= previous_elapsed
        ):
            self._local_profiles.setdefault(
                update.step_index,
                _LocalStepProfile(),
            ).observe(step.elapsed_seconds)

        self._refresh()
        return True

    def _refresh(self) -> None:
        self._revision += 1

    def _materialize(self) -> ProgressSnapshot:
        observed_at = datetime.now(timezone.utc)
        sampled_counter = perf_counter()
        step_values = tuple(
            StepProgress(
                step_index=step.step_index,
                step_kind=step.step_kind,
                step_name=step.step_name,
                layout_position=step.layout_position,
                state=step.state,
                iteration=step.iteration,
                execution_count=step.execution_count,
                elapsed_seconds=self._step_elapsed(step, sampled_counter),
                estimated_seconds=self._estimated_seconds(step.step_index) if self._learn_progress else None,
            )
            for step in self._steps
        )
        return ProgressSnapshot(
            context_id=self._context_id,
            graph_key=self._graph_key,
            graph_version=self._graph_version,
            revision=self._revision,
            observed_at=observed_at,
            context_state=self._context_state,
            iteration=self._iteration,
            max_iterations=self._max_iterations,
            steps=step_values,
            elapsed_seconds=self._elapsed_seconds(sampled_counter),
            estimated_fraction=(self._estimated_fraction(step_values) if self._learn_progress
                                else 1.0 if self._context_state.is_terminal else None),
            estimated_remaining_seconds=(self._estimated_remaining(step_values) if self._learn_progress
                                         else 0.0 if self._context_state.is_terminal else None),
            confidence=self._confidence() if self._learn_progress else 0.0,
            sample_count=self._sample_count() if self._learn_progress else 0,
        )

    def _estimated_fraction(
        self,
        steps: tuple[StepProgress, ...],
    ) -> float | None:
        if self._context_state.is_terminal:
            return 1.0
        if self._max_iterations is None:
            return None
        if self._iteration == 0:
            return 0.0

        weights = tuple(self._weight(step.step_index) for step in steps)
        total = sum(weights)
        if total <= 0:
            iteration_fraction = 1.0
        else:
            completed = sum(
                self._completed_weight(step, weight)
                for step, weight in zip(steps, weights, strict=True)
            )
            iteration_fraction = min(max(completed / total, 0.0), 1.0)
        completed_iterations = max(self._iteration - 1, 0)
        return min(
            (completed_iterations + iteration_fraction) / self._max_iterations,
            1.0,
        )

    def _estimated_remaining(
        self,
        steps: tuple[StepProgress, ...],
    ) -> float | None:
        if self._context_state.is_terminal:
            return 0.0
        if self._max_iterations is None or self._iteration == 0:
            return None
        estimates = tuple(self._estimated_seconds(step.step_index) for step in steps)
        if any(value is None for value in estimates):
            return None

        remaining = 0.0
        for step, estimate in zip(steps, estimates, strict=True):
            if estimate is None or step.state in {
                StepProgressState.COMPLETED,
                StepProgressState.SKIPPED,
            }:
                continue
            if step.state in {
                StepProgressState.RUNNING,
                StepProgressState.PENDING,
                StepProgressState.PLACEMENT_WAITING,
            }:
                remaining += max(estimate - step.elapsed_seconds, 0.0)
            else:
                remaining += estimate
        future_iterations = max(self._max_iterations - self._iteration, 0)
        remaining += future_iterations * sum(value for value in estimates if value)
        return remaining

    def _confidence(self) -> float:
        if not self._steps:
            return 1.0
        counts = tuple(
            self._profile.step(step.step_index).completion_count
            + self._local_completion_count(step.step_index)
            for step in self._steps
        )
        return min(sum(min(count, 5) for count in counts) / (5 * len(counts)), 1.0)

    def _sample_count(self) -> int:
        return sum(
            self._profile.step(step.step_index).completion_count
            + self._local_completion_count(step.step_index)
            for step in self._steps
        )

    def _weight(self, step_index: int) -> float:
        profile = self._profile.step(step_index)
        estimated = self._estimated_seconds(step_index)
        base = 1.0 if estimated is None else max(estimated, 1e-9)
        if profile.observation_count == 0:
            return base
        completion_rate = (
            profile.completion_count + profile.skipped_count
        ) / profile.observation_count
        return max(base * completion_rate, 1e-9)

    def _estimated_seconds(self, step_index: int) -> float | None:
        profile = self._profile.step(step_index)
        local = self._local_profiles.get(step_index)
        if profile.completion_count and local is not None:
            return (
                profile.mean_seconds * profile.completion_count
                + local.mean_seconds * local.completion_count
            ) / (profile.completion_count + local.completion_count)
        if local is not None:
            return local.mean_seconds
        if profile.completion_count:
            return profile.mean_seconds
        if (
            profile.observation_count
            and profile.skipped_count == profile.observation_count
        ):
            return 0.0
        return None

    def _local_completion_count(self, step_index: int) -> int:
        local = self._local_profiles.get(step_index)
        return 0 if local is None else local.completion_count

    def _elapsed_seconds(self, sampled_counter: float) -> float:
        if self._started_counter is None:
            return 0.0
        end = sampled_counter if self._finished_counter is None else self._finished_counter
        return self._elapsed_offset + max(end - self._started_counter, 0.0)

    def _completed_weight(self, step: StepProgress, weight: float) -> float:
        if step.state in {StepProgressState.COMPLETED, StepProgressState.SKIPPED}:
            return weight
        if step.state not in {
            StepProgressState.RUNNING,
            StepProgressState.PENDING,
            StepProgressState.PLACEMENT_WAITING,
        }:
            return 0.0
        estimate = step.estimated_seconds
        if estimate is None or estimate <= 0:
            return 0.0
        # Retries/repeats and placement waits preserve this step session's
        # measured work. Only RUNNING extrapolates elapsed time; a wait freezes
        # the estimate instead of erasing already measured active seconds.
        return weight * min(step.elapsed_seconds / estimate, 0.95)

    @staticmethod
    def _step_elapsed(
        step: _MutableStepProgress,
        sampled_counter: float,
    ) -> float:
        if step.active_started_at is None:
            return step.elapsed_seconds
        return step.elapsed_seconds + max(sampled_counter - step.active_started_at, 0.0)

    @staticmethod
    def _step_progress(
        index: int,
        step: CompiledStep,
    ) -> _MutableStepProgress:
        if isinstance(step, CompiledOperatorStep):
            kind = "operator"
            name = step.operator_name
        elif isinstance(step, CompiledResourceStep):
            kind = "resource"
            name = step.resource_name
        else:
            raise TypeError("compiled graph contains an unsupported step")
        return _MutableStepProgress(
            step_index=index,
            step_kind=kind,
            step_name=name,
            layout_position=step.layout_position,
        )
