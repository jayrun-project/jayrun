from enum import Enum


class ExecutionState(Enum):
    IDLE = "idle"
    DISPATCHED = "dispatched"
    PLACEMENT_WAITING = "placement_waiting"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"
