from dataclasses import dataclass

from ...artifact.actor import ArtifactActor
from .artifact_state import ArtifactState


@dataclass(slots=True, frozen=True)
class ArtifactRecord:
    """One artifact lifecycle transition recorded during a context iteration."""

    state: ArtifactState
    actor: ArtifactActor | None
    step_index: int | None
    iteration: int
