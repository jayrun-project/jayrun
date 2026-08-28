from .recorder import ExecutionRecorder


class DebugExecutionRecorder(ExecutionRecorder):
    def __init__(self) -> None:
        super().__init__(
            record_logs=True,
            record_metrics=True,
            record_timers=True,
            record_failures=True,
        )
