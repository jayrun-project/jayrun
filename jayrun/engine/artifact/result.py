from dataclasses import dataclass

from ...core.context.runtime_data import Data
from ..resource.placement import PlacementLocation
from ..recorders.artifact.record import ArtifactRecord


@dataclass(frozen=True, slots=True)
class ArtifactResult:
    """A retained artifact value and its lifecycle report.

    Attributes:
        data: Retained value and placement.
        report: Ordered artifact lifecycle records.
    """

    data: Data
    report: tuple[ArtifactRecord, ...]

    @property
    def value(self) -> object:
        """Retained artifact value, or ``None`` when its payload was released."""
        return self.data.value

    @property
    def placement(self) -> PlacementLocation:
        """Placement on which the retained value resides."""
        return self.data.placement
