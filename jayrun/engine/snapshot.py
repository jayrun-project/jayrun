from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from ..core.context.runtime_data import Data
from .artifact.result import ArtifactResult
from .interfaces.context_record import ContextRecord
from .progress import ProgressSnapshot
from .recorders.context.report import ContextReport
from .recorders.execution.records import ExecutionReport
from .registry.context_state import ContextRequest, ContextState
from .registry.context_status import ContextHistoryEntry
from .settings.context import ContextSettings


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    """Immutable, transport-neutral state of one logical context.

    Snapshots contain no runtime capability, executor, queue, or transport. A
    controller may serialize one with its chosen codec, transport it by any
    mechanism, and pass the reconstructed value to ``Engine.apply`` or
    ``self.runtime.apply``. Generation rejects an obsolete owner; revision makes
    duplicate and out-of-order application idempotent.

    Configs and ContextRecords have codecs in ``jayrun.serialization``. These
    codecs do not cover the complete snapshot: settings may contain exception
    classes, and reports may contain exceptions. Applications must define their
    full snapshot representation; picklability is not a value admission check.

    Every run can be inspected as a snapshot. Applying it on another engine
    additionally requires a registered graph whose complete entry and exit
    boundary has serializers; snapshots from local-only graphs remain useful for
    atomic observation but are not remotely executable.

    ``request`` is optional intent and never pretends that its requested state is
    already committed. Progress is sampled into a snapshot only when requested or
    when another narrow context event is emitted.

    Attributes:
        context_id: Probabilistically unique 62-bit integer identity of the
            logical context, compatible with signed 64-bit systems.
        graph_key: Registered graph key, or ``None`` for a process-local graph.
        graph_version: Version of the context graph.
        engine_id: Unique name and UUID of the assigned engine incarnation.
        generation: Ownership generation used to fence obsolete engine incarnations.
        revision: Monotonic synchronization revision for all portable changes.
        state: Last committed lifecycle state.
        request: Optional lifecycle change awaiting the owning runtime.
        request_duration: Pause duration beginning when the owner applies it.
        iteration_count: Number of iterations that have started.
        completed_iterations: Number of atomically completed iterations.
        stop_requested: Whether the execution owner accepted Stop. This sticky
            fact prevents another iteration independently of ``state``; it does
            not mean the current iteration has finished. ``request=STOP`` alone
            is only intent. Normal Stop completion is FINISHED; legacy STOPPED
            remains readable as a terminal outcome.
        finalized: Whether terminal reports and artifacts are complete.
        progress: Latest immutable progress estimate.
        records: Retained context records in committed sequence order.
        record_sequence: Highest committed record sequence, preserved by transfer.
            Gaps in retained sequences indicate unavailable history.
        reports: Completed execution reports available so far.
        report: Terminal context report, when finalized.
        artifacts: Final artifact results keyed by graph artifact ID.
        artifact_context: Safe entry or feedback checkpoint keyed by artifact ID.
        config_context: Submitted configuration keyed by config ID.
        context_settings: Effective portable context settings.
        artifacts_serialized: Whether artifact payloads contain serializer bytes.
        history: Ordered lifecycle, request, and ownership history. Ownership
            changes record the completed-iteration checkpoint used by the next
            generation.
    """

    context_id: int
    graph_key: str | None
    graph_version: str
    engine_id: str
    generation: int
    revision: int
    state: ContextState
    request: ContextRequest | None
    request_duration: float | None
    iteration_count: int
    completed_iterations: int
    stop_requested: bool
    finalized: bool
    progress: ProgressSnapshot
    records: tuple[ContextRecord, ...]
    record_sequence: int
    reports: tuple[ExecutionReport, ...]
    report: ContextReport | None
    artifacts: tuple[tuple[int, ArtifactResult], ...]
    artifact_context: tuple[tuple[int, Data[object]], ...]
    config_context: tuple[tuple[int, Data[object]], ...]
    context_settings: ContextSettings
    artifacts_serialized: bool
    history: tuple[ContextHistoryEntry, ...]
    created_at: datetime
    updated_at: datetime
    validated_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None

    def __post_init__(self) -> None:
        if type(self.context_id) is not int or self.context_id < 0:
            raise ValueError("context_id must be a non-negative int")
        if self.graph_key is not None and not isinstance(self.graph_key, str):
            raise TypeError("graph_key must be a string or None")
        if not isinstance(self.graph_version, str) or not self.graph_version:
            raise ValueError("graph_version must be a non-empty string")
        if not isinstance(self.engine_id, str):
            raise TypeError("engine_id must be a string")
        if not self.engine_id.strip():
            raise ValueError("engine_id must not be empty")
        if self.engine_id.strip() == "self":
            raise ValueError("engine_id must identify an engine incarnation")
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("generation must be a non-negative int")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("revision must be a non-negative int")
        if not isinstance(self.state, ContextState):
            raise TypeError("state must be a ContextState instance")
        if self.request is not None and not isinstance(
            self.request,
            ContextRequest,
        ):
            raise TypeError("request must be a ContextRequest or None")
        if self.request is not None and self.finalized:
            raise ValueError("a finalized snapshot cannot carry a request")
        if self.request_duration is not None:
            if isinstance(self.request_duration, bool) or not isinstance(
                self.request_duration,
                (int, float),
            ):
                raise TypeError("request_duration must be numeric or None")
            if self.request_duration < 0 or not math.isfinite(
                self.request_duration
            ):
                raise ValueError(
                    "request_duration must be finite and non-negative"
                )
            if self.request is not ContextRequest.PAUSE:
                raise ValueError("only a pause request can have a duration")
        if self.completed_iterations > self.iteration_count:
            raise ValueError(
                "completed_iterations cannot exceed iteration_count"
            )
        if self.finalized and not self.state.is_terminal:
            raise ValueError("only a terminal context can be finalized")
        if self.finalized != (self.report is not None):
            raise ValueError("a finalized snapshot must contain a report")
        if not isinstance(self.context_settings, ContextSettings):
            raise TypeError("context_settings must be a ContextSettings instance")
        if not isinstance(self.artifacts_serialized, bool):
            raise TypeError("artifacts_serialized must be a bool")

    @property
    def records_complete(self) -> bool:
        """Whether all committed context records are still retained."""
        return len(self.records) == self.record_sequence

    @property
    def failure(self) -> Exception | None:
        """Terminal failure, or ``None`` when no failure is available."""
        return None if self.report is None else self.report.failure
