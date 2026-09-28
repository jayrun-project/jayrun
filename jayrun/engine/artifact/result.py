from dataclasses import dataclass

from ...core.context.runtime_data import Data
from ..resource.placement import PlacementLocation
from ..recorders.artifact.record import ArtifactRecord


@dataclass(frozen=True, slots=True)
class ArtifactResult:
    """Finalized artifact data and its retained lifecycle history.

    Attributes:
        data: Final value and placement. Its payload is ``None`` when cleared or
            not retained.
        history: Ordered retained artifact lifecycle records; not a global timeline.
    """

    data: Data
    history: tuple[ArtifactRecord, ...]

    @property
    def value(self) -> object:
        """Final artifact value, or ``None`` when its payload was released."""
        return self.data.value

    @property
    def placement(self) -> PlacementLocation:
        """Placement associated with the final data container."""
        return self.data.placement
