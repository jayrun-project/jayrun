from dataclasses import dataclass

from ...core.context.runtime_data import Data
from ..resource.placement import PlacementLocation
from ..recorders.artifact.record import ArtifactRecord


@dataclass(frozen=True, slots=True)
class ArtifactResult:
    """Finalized artifact data and its lifecycle report.

    Attributes:
        data: Final value and placement. Its payload is ``None`` when cleared or
            not retained.
        report: Ordered artifact lifecycle records.
    """

    data: Data
    report: tuple[ArtifactRecord, ...]

    @property
    def value(self) -> object:
        """Final artifact value, or ``None`` when its payload was released."""
        return self.data.value

    @property
    def placement(self) -> PlacementLocation:
        """Placement associated with the final data container."""
        return self.data.placement
