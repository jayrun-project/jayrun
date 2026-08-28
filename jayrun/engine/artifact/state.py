from enum import Enum


class ArtifactStoreState(Enum):
    RUNNING = "running"
    FINALIZED = "finalized"
    PENDING = "pending"
