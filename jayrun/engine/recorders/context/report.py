from dataclasses import dataclass

from ..execution.records import ExecutionReport


@dataclass(frozen=True, slots=True)
class ContextReport:
    """Immutable execution reports collected for one context.

    Attributes:
        executions: Step reports in runtime recording order.
    """

    executions: tuple[ExecutionReport, ...]
