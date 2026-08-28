from ...artifact.base import Artifact
from ..definition.artifact import ArtifactDefinition
from .data import DataRegistry


class ArtifactRegistry(DataRegistry[Artifact, ArtifactDefinition]):
    pass
