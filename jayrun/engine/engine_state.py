from enum import Enum


class EngineState(Enum):
    """Lifecycle state of an engine instance."""

    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"

    # Compatibility aliases. Idle/active status now belongs to
    # RuntimeActivity and no longer changes the lifecycle state.
    STARTED = "running"
    IDLE = "running"


class RuntimeActivity(Enum):
    """Current workload activity of a running engine."""

    IDLE = "idle"
    ACTIVE = "active"
