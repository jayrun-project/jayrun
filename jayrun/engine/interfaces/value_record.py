from collections.abc import Hashable
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ValueRecord:
    """Immutable value stored through a context interface.

    Attributes:
        step_name: Operator or resource step that created the record.
        execution: Execution number within the step session.
        iteration: Context iteration number.
        context_id: ID of the context that created the record.
        key: User-provided record key.
        value: User-provided value.
        recorded_at: UTC recording timestamp.
    """

    step_name: str
    execution: int
    iteration: int
    context_id: int
    key: Hashable
    value: object
    recorded_at: datetime
