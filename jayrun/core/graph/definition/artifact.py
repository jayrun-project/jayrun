from dataclasses import dataclass
from enum import Enum

from .data import DataDefinition


class ArtifactRole(Enum):
    """Origin role assigned by graph construction, independent of exit status.

    UNUSED is the historical name for produced artifacts without a consuming
    flow. These are terminal outputs with ``is_exit=True`` and can be retained.
    """

    ENTRY = "entry"
    INTERMEDIATE = "intermediate"
    UNUSED = "unused"


@dataclass(slots=True, frozen=True, kw_only=True)
class ArtifactDefinition(DataDefinition):
    """Graph-local inspected artifact metadata."""

    artifact_id: int
    role: ArtifactRole
    is_exit: bool
