from enum import Enum


class EngineState(Enum):
    """Lifecycle state of an engine instance."""

    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"

class RuntimeActivity(Enum):
    """Current workload activity of a running engine."""

    IDLE = "idle"
    ACTIVE = "active"
