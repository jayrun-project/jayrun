from dataclasses import dataclass, field, replace

from ...core.artifact.base import Artifact
from ...core.graph.definition.artifact import ArtifactDefinition
from ...core.graph.registry.artifact import ArtifactRegistry
from .context import ArtifactPolicy, ContextSettings, RecordPolicy
from ._instrumentation import _InstrumentationPolicy
from .engine import (
    EngineSettings,
    FailureMode,
    RetryPolicy,
    RecordingMode,
)


@dataclass(frozen=True, slots=True)
class CombinedContextSettings:
    recording_mode: RecordingMode
    failure_mode: FailureMode
    retry_policy: RetryPolicy
    artifact_policy: ArtifactPolicy
    max_iterations: int | None
    max_repeats: int | None
    execution_history_limit: int | None = None
    record_policy: RecordPolicy = field(default_factory=RecordPolicy)
    instrumentation: _InstrumentationPolicy = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "instrumentation", _InstrumentationPolicy.for_mode(self.recording_mode))

    @classmethod
    def from_settings(
        cls,
        engine_settings: EngineSettings,
        context_settings: ContextSettings | None,
        artifact_registry: ArtifactRegistry,
    ) -> "CombinedContextSettings":
        if not isinstance(engine_settings, EngineSettings):
            raise TypeError("engine_settings must be an EngineSettings instance")

        if context_settings is None:
            context_settings = ContextSettings()
        elif not isinstance(context_settings, ContextSettings):
            raise TypeError(
                "context_settings must be a ContextSettings instance or None"
            )

        if not isinstance(artifact_registry, ArtifactRegistry):
            raise TypeError("artifact_registry must be an ArtifactRegistry instance")

        artifact_policy = cls._normalize_artifact_policy(
            context_settings.artifact_policy,
            artifact_registry,
        )

        return cls(
            recording_mode=engine_settings.recording_mode,
            failure_mode=engine_settings.failure_mode,
            retry_policy=(
                context_settings.retry_policy
                if context_settings.retry_policy is not None
                else engine_settings.retry_policy
            ),
            artifact_policy=artifact_policy,
            max_iterations=context_settings.max_iterations,
            max_repeats=context_settings.max_repeats,
            execution_history_limit=context_settings.execution_history_limit,
            record_policy=context_settings.record_policy,
        )

    @classmethod
    def _normalize_artifact_policy(
        cls,
        policy: ArtifactPolicy,
        registry: ArtifactRegistry,
    ) -> ArtifactPolicy:
        if policy.retained_artifacts is None:
            retained_artifacts = tuple(
                artifact
                for artifact in registry.sources
                if registry.definition_for(artifact).is_exit
            )
        else:
            retained_artifacts = tuple(
                cls._resolve_retained_artifact(reference, registry)
                for reference in policy.retained_artifacts
            )

            cls._validate_retained_artifacts(
                retained_artifacts,
                registry,
            )

        return replace(
            policy,
            retained_artifacts=retained_artifacts,
        )

    @staticmethod
    def _resolve_retained_artifact(
        reference: int | Artifact | ArtifactDefinition,
        registry: ArtifactRegistry,
    ) -> Artifact:
        try:
            return registry.resolve(reference)
        except KeyError as error:
            raise ValueError("Retained artifact reference does not belong to the graph") from error

    @staticmethod
    def _validate_retained_artifacts(
        artifacts: tuple[Artifact, ...],
        registry: ArtifactRegistry,
    ) -> None:
        retained_ids: set[int] = set()

        for artifact in artifacts:
            artifact_identity = id(artifact)

            if artifact_identity in retained_ids:
                raise ValueError(
                    "Multiple retained artifact references resolve to the same Artifact"
                )

            retained_ids.add(artifact_identity)

            definition = registry.definition_for(artifact)

            if not definition.is_exit:
                raise ValueError(
                    f"Retained artifact {artifact!r} is not an exit artifact"
                )
