"""Explicit execution/ownership admission failures, independent of instrumentation."""


class OwnershipCapacityError(RuntimeError):
    """New distributed ownership would exceed the engine-incarnation budget.

    Existing identities keep their reserved protection through finalization.
    This error grants no remote ownership and is not a transport acknowledgement.
    """


class ContextHistoryLimitError(RuntimeError):
    """Further history-producing work exceeds an explicit context safety budget.

    Full accepted evidence and mandatory drainage are preserved, not truncated.
    """
