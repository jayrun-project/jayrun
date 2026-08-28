from enum import Enum


class ResourceState(Enum):
    LOADING = "loading"
    READY = "ready"
    IN_USE = "in_use"
    UNLOADING = "unloading"
