from dataclasses import dataclass
from datetime import datetime

from ...context.step_reference import StepReference
from ...registry.context_state import ContextState
from ...registry.context_status import ContextHistoryEntry
from ..execution.records import ExecutionReport


@dataclass(frozen=True, slots=True)
class ContextReport:
    """Immutable terminal report for one submitted context.

    Attributes:
        context_id: Engine-local context identifier.
        state: Terminal context state.
        revision: Final monotonic context revision.
        iteration_count: Number of graph iterations that started.
        stop_requested: Whether graceful iteration stopping was requested.
        created_at: Submission timestamp.
        updated_at: Timestamp of the final context update.
        validated_at: Validation-completion timestamp, if reached.
        started_at: Execution-start timestamp, if reached.
        finished_at: Terminal-state timestamp.
        history: Ordered lifecycle and iteration history.
        executions: Step reports in runtime recording order.
        failure: Context failure, if any.
        failed_step: Graph step associated with the failure, if any.
    """

    context_id: int
    state: ContextState
    revision: int
    iteration_count: int
    stop_requested: bool
    created_at: datetime
    updated_at: datetime
    validated_at: datetime | None
    started_at: datetime | None
    finished_at: datetime
    history: tuple[ContextHistoryEntry, ...]
    executions: tuple[ExecutionReport, ...]
    failure: Exception | None
    failed_step: StepReference | None
