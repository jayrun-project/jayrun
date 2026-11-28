from ...artifact.base import Artifact
from ..definition.artifact import ArtifactDefinition
from .data import DataRegistry


class ArtifactRegistry(DataRegistry[Artifact, ArtifactDefinition]):
    def resolve(self, reference: int | Artifact | ArtifactDefinition) -> Artifact:
        if isinstance(reference, Artifact):
            if self._contains_source(reference):
                return reference
            raise KeyError("The Artifact does not belong to this graph.")
        if isinstance(reference, ArtifactDefinition):
            return self.source_for(reference)
        if type(reference) is int:
            if 0 <= reference < len(self.definitions):
                definition = self.definitions[reference]
                if definition.artifact_id == reference:
                    return self.source_for(definition)
            raise KeyError(f"Unknown artifact ID: {reference!r}.")
        raise TypeError("Artifact references must be int, Artifact, or ArtifactDefinition.")
