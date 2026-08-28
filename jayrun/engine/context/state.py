from enum import Enum


class State(Enum):
    RUNNING = "running"
    TERMINATED = "terminated"
    FAILED = "failed"
    FINISHED = "finished"
    PENDING = "pending"
    ABORTED = "aborted"
    PAUSED = "paused"
