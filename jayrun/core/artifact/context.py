from __future__ import annotations

from collections.abc import Mapping

from ..context.base import DataContext
from ..context.runtime_data import Data
from ..graph.definition.artifact import ArtifactDefinition, ArtifactRole
from ..graph.graph_definition import GraphDefinition
from .base import Artifact


class ArtifactContext(DataContext[Artifact, Data]):
    """Hold the entry-artifact values for one graph submission.

    The graph must be confirmed before the context is created. Values are wrapped in
    :class:`~jayrun.Data`; callers may address artifacts by object, inspected
    definition, or graph-local integer ID.

    Args:
        graph: Confirmed graph whose artifacts the context accepts.
        name: Optional name for diagnostics.
        description: Optional description for diagnostics.

    Raises:
        TypeError: If ``graph`` is not a :class:`~jayrun.GraphDefinition`.
        RuntimeError: If the graph has not been confirmed.
    """

    def __init__(
        self,
        *,
        graph: GraphDefinition,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)

        if not isinstance(graph, GraphDefinition):
            raise TypeError("graph must be a GraphDefinition instance")
        if not graph.confirmed:
            raise RuntimeError("The graph must be confirmed.")

        self._graph = graph
        self._registry = graph._specification.artifacts
        self._definitions_by_id = {
            definition.artifact_id: definition
            for definition in self._registry.definitions
        }
        self._release_target: ArtifactContext | None = None

    def set(
        self,
        artifacts: Mapping[int | Artifact | ArtifactDefinition, object],
    ) -> None:
        """Set or replace artifact values.

        Args:
            artifacts: Mapping from artifact IDs, artifacts, or inspected artifact
                definitions to raw values.

        Raises:
            KeyError: If a key does not belong to this graph.
            TypeError: If ``artifacts`` is not a mapping or a key is unsupported.
            ValueError: If multiple keys resolve to the same artifact.
        """
        if not isinstance(artifacts, Mapping):
            raise TypeError(
                "Expected a mapping of artifact IDs, Artifact, or "
                "ArtifactDefinition to values."
            )

        instances: dict[Artifact, Data] = {}

        for key, value in artifacts.items():
            artifact = self._resolve_artifact(key)

            if artifact in instances:
                raise ValueError("Multiple artifact keys resolve to the same Artifact.")

            instances[artifact] = Data(value=value)

        self._update_instances(instances)

    def get(
        self,
        artifact: int | Artifact | ArtifactDefinition,
    ) -> Data | None:
        """Return an artifact's wrapped value, or ``None`` if it is unset."""
        return self._instances.get(self._resolve_artifact(artifact))

    def clear(self) -> None:
        """Remove every value from this context."""
        self._instances.clear()

    def clear_entries(self) -> None:
        """Remove graph-entry values from this context and its release target."""
        self._clear_entries()
        if self._release_target is not None:
            self._release_target._clear_entries()

    def _clear_entries(self) -> None:
        for definition in self._registry.definitions:
            if definition.role is ArtifactRole.ENTRY:
                self._instances.pop(
                    self._registry.source_for(definition),
                    None,
                )

    def _fork(self) -> ArtifactContext:
        context = ArtifactContext(
            graph=self.graph,
            name=self.name,
            description=self.description,
        )
        context._instances = dict(self._instances)
        context._release_target = self
        return context

    def validate(self) -> bool:
        """Return whether every graph entry artifact has a value."""
        return all(
            self._registry.source_for(definition) in self._instances
            for definition in self._registry.definitions
            if definition.role is ArtifactRole.ENTRY
        )

    def _resolve_artifact(
        self,
        artifact: int | Artifact | ArtifactDefinition,
    ) -> Artifact:
        if type(artifact) is int:
            try:
                definition = self._definitions_by_id[artifact]
            except KeyError:
                raise KeyError(f"Unknown artifact ID: {artifact!r}.") from None

            return self._registry.source_for(definition)

        if isinstance(artifact, ArtifactDefinition):
            if artifact not in self._registry.definitions:
                raise KeyError("The ArtifactDefinition does not belong to this graph.")

            return self._registry.source_for(artifact)

        if isinstance(artifact, Artifact):
            if artifact not in self._registry.sources:
                raise KeyError("The Artifact does not belong to this graph.")

            return artifact

        raise TypeError(
            "Expected int, Artifact, or ArtifactDefinition, "
            f"got {type(artifact).__name__!r}."
        )

    @property
    def graph(self) -> GraphDefinition:
        """The confirmed graph associated with this context."""
        return self._graph
