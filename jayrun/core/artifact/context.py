from __future__ import annotations

from collections.abc import Mapping

from ..context.base import DataContext
from ..context.runtime_data import Data
from ..graph.definition.artifact import ArtifactDefinition, ArtifactRole
from ..graph.registry.artifact import ArtifactRegistry
from .base import Artifact


_ArtifactReference = int | Artifact | ArtifactDefinition


class ArtifactContext(DataContext[_ArtifactReference, Data[object]]):
    """Build the artifact values for one graph submission.

    Builder contexts are graph-independent. References are resolved against the
    explicit graph during submission; before then, only exact artifact declarations
    support lookup. Submission creates a separate, sealed context that additionally
    supports graph-local definitions and integer IDs.

    Args:
        artifacts: Optional initial values, using the same rules as :meth:`set`.
        name: Optional name for diagnostics.
        description: Optional description for diagnostics.
    """

    def __init__(
        self,
        artifacts: Mapping[_ArtifactReference, object] | None = None,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self._registry: ArtifactRegistry | None = None
        if artifacts is not None:
            self.set(artifacts)

    def set(
        self,
        artifacts: Mapping[_ArtifactReference, object],
    ) -> None:
        """Set or replace artifact values.

        Builder keys may be exact declarations or graph-relative references. The
        latter are retained without interpretation until submission, when the
        explicit graph resolves them. Assignments retain call order, and the last
        reference resolving to an artifact supplies its submitted value. Sealed
        submission contexts cannot be mutated.

        Args:
            artifacts: Mapping from artifact references to raw values.

        Raises:
            RuntimeError: If the context is sealed.
            TypeError: If ``artifacts`` is not a mapping or a key is unsupported.
        """
        self._require_mutable()
        if not isinstance(artifacts, Mapping):
            raise TypeError(
                "Expected a mapping of artifact IDs, Artifact, or "
                "ArtifactDefinition to values."
            )

        instances: dict[_ArtifactReference, Data[object]] = {}

        for key, value in artifacts.items():
            self._validate_reference(key)
            instances[key] = Data(value=value)

        self._update_ordered_instances(instances)

    def get(
        self,
        artifact: _ArtifactReference,
    ) -> Data[object] | None:
        """Return an artifact's wrapped value, or ``None`` if it is unset.

        Before submission, ``artifact`` must be the exact declaration object used
        with :meth:`set`. Definitions and integer IDs become available only on the
        normalized submission context.
        """
        if self._registry is None:
            if isinstance(artifact, Artifact):
                return self._instances.get(artifact)
            self._validate_reference(artifact)
            self._require_registry()
        return self._instances.get(self._resolve_artifact(artifact))

    def clear(self) -> None:
        """Remove every value from this mutable builder context."""
        self._require_mutable()
        self._instances.clear()


    def _validate(self) -> bool:
        """Return whether every graph entry exists in a normalized context.

        This is available on a submitted run's context, not on a mutable builder.
        Submission validates builder values against its explicit graph.

        Raises:
            RuntimeError: If called before submission normalization.
        """
        registry = self._require_registry()
        return all(
            registry.source_for(definition) in self._instances
            for definition in registry.definitions
            if definition.role is ArtifactRole.ENTRY
        )

    def _clear_entries(self, registry: ArtifactRegistry | None = None) -> None:
        if registry is None:
            registry = self._require_registry()
        entry_ids = {
            id(registry.source_for(definition))
            for definition in registry.definitions
            if definition.role is ArtifactRole.ENTRY
        }
        for reference in tuple(self._instances):
            artifact = self._resolve_with_registry(reference, registry)
            if id(artifact) in entry_ids:
                self._instances.pop(reference, None)

    def _release(self) -> None:
        self._instances.clear()

    @classmethod
    def _from_normalized(
        cls,
        source: ArtifactContext,
        registry: ArtifactRegistry,
        instances: Mapping[Artifact, Data[object]],
    ) -> ArtifactContext:
        context = cls(name=source.name, description=source.description)
        context._registry = registry
        context._instances = dict(instances)
        context._seal()
        return context

    def _is_normalized_for(self, registry: ArtifactRegistry) -> bool:
        return self._is_sealed and self._registry is registry

    def _require_registry(self) -> ArtifactRegistry:
        if self._registry is None:
            raise RuntimeError(
                "graph-relative artifact access is unavailable before submission "
                "normalization"
            )
        return self._registry

    def _resolve_artifact(
        self,
        artifact: _ArtifactReference,
    ) -> Artifact:
        return self._resolve_with_registry(artifact, self._require_registry())

    @staticmethod
    def _resolve_with_registry(
        artifact: _ArtifactReference,
        registry: ArtifactRegistry,
    ) -> Artifact:
        if isinstance(artifact, Artifact):
            if not any(artifact is source for source in registry.sources):
                raise KeyError("The Artifact does not belong to this graph.")
            return artifact

        if type(artifact) is int:
            for definition in registry.definitions:
                if definition.artifact_id == artifact:
                    return registry.source_for(definition)
            raise KeyError(f"Unknown artifact ID: {artifact!r}.")

        if isinstance(artifact, ArtifactDefinition):
            for definition in registry.definitions:
                if artifact is definition:
                    return registry.source_for(definition)
            raise KeyError("The ArtifactDefinition does not belong to this graph.")

        raise TypeError(
            "Expected int, Artifact, or ArtifactDefinition, "
            f"got {type(artifact).__name__!r}."
        )

    @staticmethod
    def _validate_reference(artifact: object) -> None:
        if (
            type(artifact) is int
            or isinstance(artifact, (Artifact, ArtifactDefinition))
        ):
            return
        raise TypeError(
            "Expected int, Artifact, or ArtifactDefinition, "
            f"got {type(artifact).__name__!r}."
        )
