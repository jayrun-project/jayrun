from .recorder import ExecutionRecorder


class ProductionExecutionRecorder(ExecutionRecorder):
    def __init__(self) -> None:
        super().__init__(
            record_logs=True,
            record_metrics=True,
            record_timers=False,
            record_failures=False,
        )
