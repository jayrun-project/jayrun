from dataclasses import dataclass

from .execution_proxy import ExecutionProxy


@dataclass(frozen=True, slots=True)
class ExecutionStep:
    index: int
    proxy: ExecutionProxy
    context_id: int


class ExecutionOperator(ExecutionStep):
    pass


class ExecutionResource(ExecutionStep):
    pass
