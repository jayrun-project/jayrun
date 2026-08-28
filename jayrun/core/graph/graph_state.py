from enum import Enum


class GraphState(Enum):
    CREATED = "created"
    CONFIRMED = "confirmed"
    RESOURCES_BOUND = "resource-bound"
