from dataclasses import dataclass
from typing import Generic, TypeVar

from ...engine.resource.placement import CPU_PLACEMENT, PlacementLocation

T = TypeVar("T")


@dataclass(frozen=True, slots=True, eq=False)
class Data(Generic[T]):
    """Pair a runtime value with its placement.

    Args:
        value: Arbitrary artifact or resource value.
        placement: CPU or reserved accelerator placement containing the value.
    """

    value: T
    placement: PlacementLocation = CPU_PLACEMENT

    def __post_init__(self) -> None:
        from ...engine.resource.placement import Placement, PlacementGroup

        if not isinstance(self.placement, (Placement, PlacementGroup)):
            raise TypeError(
                "placement must be a Placement or PlacementGroup instance"
            )
