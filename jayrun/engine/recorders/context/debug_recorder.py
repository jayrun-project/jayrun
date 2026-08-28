from ..artifact.debug_recorder import DebugArtifactRecorder
from ..execution.debug_recorder import DebugExecutionRecorder
from .recorder import ContextRecorder


class DebugContextRecorder(ContextRecorder):
    def __init__(self) -> None:
        super().__init__(
            execution_recorder_type=DebugExecutionRecorder,
            artifact_recorder_type=DebugArtifactRecorder,
        )
