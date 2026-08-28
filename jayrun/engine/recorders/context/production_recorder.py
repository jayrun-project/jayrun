from ..artifact.production_recorder import ProductionArtifactRecorder
from ..execution.production_recorder import ProductionExecutionRecorder
from .recorder import ContextRecorder


class ProductionContextRecorder(ContextRecorder):
    def __init__(self) -> None:
        super().__init__(
            execution_recorder_type=ProductionExecutionRecorder,
            artifact_recorder_type=ProductionArtifactRecorder,
        )
