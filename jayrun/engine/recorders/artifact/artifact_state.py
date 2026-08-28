from enum import Enum


class ArtifactState(Enum):
    UNREGISTERED = "unregistered"
    REGISTERED = "registered"
    CLEARED = "cleared"
    UPDATED = "updated"
