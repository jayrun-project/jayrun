from dataclasses import dataclass
from enum import Enum

from .data import DataDefinition


class ArtifactRole(Enum):
    """Structural role assigned to an artifact by graph construction."""

    ENTRY = "entry"
    INTERMEDIATE = "intermediate"
    UNUSED = "unused"


@dataclass(slots=True, frozen=True, kw_only=True)
class ArtifactDefinition(DataDefinition):
    """Graph-local inspected artifact metadata."""

    artifact_id: int
    role: ArtifactRole
    is_exit: bool
