from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

from ...core.artifact.base import Artifact
from ...core.graph.definition.artifact import ArtifactDefinition
from ...core.graph.registry.artifact import ArtifactRegistry
from ..artifact.result import ArtifactResult
from ..context.step_reference import StepReference
from ..recorders.context.report import ContextReport
from .context_state import ContextState
from .context_status import ContextHistoryEntry


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    """Immutable point-in-time view of one execution context.

    Attributes:
        context_id: Unique ID assigned at submission.
        state: Current lifecycle state.
        finalized: Whether final reporting and artifact retention are complete.
        revision: Monotonic snapshot revision.
        iteration_count: Number of completed graph iterations.
        stop_requested: Whether graceful stopping has been requested.
        created_at: Submission timestamp.
        updated_at: Timestamp of the latest state change.
        validated_at: Validation-completion timestamp, if reached.
        started_at: Execution-start timestamp, if reached.
        finished_at: Terminal-state timestamp, if reached.
        history: Ordered context-state history.
        report: Context observability report when available.
        artifacts: Retained artifact results keyed by artifact declaration.
        failure: Context failure, if any.
        failed_step: Graph step associated with the failure, if any.
    """

    context_id: int
    state: ContextState
    finalized: bool
    revision: int
    iteration_count: int
    stop_requested: bool
    created_at: datetime
    updated_at: datetime
    validated_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    history: tuple[ContextHistoryEntry, ...]
    report: ContextReport | None
    artifacts: Mapping[Artifact, ArtifactResult]
    failure: Exception | None
    failed_step: StepReference | None
    _artifact_registry: ArtifactRegistry = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "artifacts",
            MappingProxyType(dict(self.artifacts)),
        )

    def artifact(
        self,
        reference: int | ArtifactDefinition | Artifact,
    ) -> ArtifactResult:
        """Return a retained artifact result by ID, definition, or declaration.

        Raises:
            KeyError: If the reference is unknown or its result was not retained.
            TypeError: If the reference type is unsupported.
        """
        artifact = self._resolve_artifact(reference)
        try:
            return self.artifacts[artifact]
        except KeyError:
            raise KeyError(
                f"artifact result is unavailable for context {self.context_id!r}"
            ) from None

    def _resolve_artifact(
        self,
        reference: int | ArtifactDefinition | Artifact,
    ) -> Artifact:
        if type(reference) is int:
            for definition in self._artifact_registry.definitions:
                if definition.artifact_id == reference:
                    return self._artifact_registry.source_for(definition)
            raise KeyError(f"unknown artifact ID: {reference!r}")

        if isinstance(reference, ArtifactDefinition):
            for definition in self._artifact_registry.definitions:
                if definition is reference:
                    return self._artifact_registry.source_for(definition)
            raise KeyError("ArtifactDefinition does not belong to the context graph")

        if isinstance(reference, Artifact):
            for artifact in self._artifact_registry.sources:
                if artifact is reference:
                    return artifact
            raise KeyError("Artifact does not belong to the context graph")

        raise TypeError(
            "artifact reference must be int, ArtifactDefinition, or Artifact"
        )
