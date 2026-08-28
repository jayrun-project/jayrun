from .recorder import ArtifactRecorder


class DebugArtifactRecorder(ArtifactRecorder):
    def __init__(self) -> None:
        super().__init__(keep_history=True)
