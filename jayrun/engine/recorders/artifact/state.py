from enum import Enum


class RecorderState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    STOPPED = "stopped"
