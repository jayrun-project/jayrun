from enum import Enum


class ExecutionMode(Enum):
    THREAD = "thread"
    EVENT_LOOP = "event-loop"
    PROCESS = "process"
    INTERPRETER = "interpreter"
