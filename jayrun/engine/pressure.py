from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PressureSnapshot:
    """Immutable sampled runtime pressure visible to one caller.

    Attributes:
        sampled_at: UTC time at which the runtime was inspected.
        memory_pressured: Whether scheduler memory pressure is active.
        routing_contexts: Visible locally owned contexts waiting for a engine_id
            assignment.
        queued_contexts: Visible locally owned contexts assigned here and waiting
            for scheduler admission.
        running_contexts: Visible locally owned contexts currently running.
        paused_contexts: Visible locally owned paused contexts.
        placement_waiting_contexts: Visible locally owned contexts waiting for
            placement.
        pending_placements: Number of unresolved placement requests.
        task_capacity: Ordinary executor capacity across execution modes.
        occupied_tasks: Ordinary and supervising executor tasks in use.
        supervision_capacity: Executor capacity reserved for supervising contexts.
    """

    sampled_at: datetime
    memory_pressured: bool
    routing_contexts: int
    queued_contexts: int
    running_contexts: int
    paused_contexts: int
    placement_waiting_contexts: int
    pending_placements: int
    task_capacity: int
    occupied_tasks: int
    supervision_capacity: int
    engine_id: str
