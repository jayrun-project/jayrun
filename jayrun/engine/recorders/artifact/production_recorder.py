from .recorder import ArtifactRecorder


class ProductionArtifactRecorder(ArtifactRecorder):
    def __init__(self) -> None:
        super().__init__(keep_history=False)
