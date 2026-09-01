from dataclasses import dataclass, field
from typing import TypeAlias

from ...core.artifact.base import Artifact
from ...core.graph.definition.artifact import ArtifactDefinition
from .engine import RetryPolicy

ArtifactReference: TypeAlias = int | Artifact | ArtifactDefinition


@dataclass(frozen=True, slots=True)
class ArtifactPolicy:
    """Control which artifact values remain available after execution.

    Args:
        retain_all: Retain every eligible final artifact when ``True``.
        retained_artifacts: Explicit exit-artifact IDs, declarations, or inspected
            definitions to retain when ``retain_all`` is ``False``.
        release_entry_artifacts: Release submitted entry values as soon as graph
            execution no longer needs them.
    """

    retain_all: bool = True
    retained_artifacts: tuple[ArtifactReference, ...] = ()
    release_entry_artifacts: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.retain_all, bool):
            raise TypeError("retain_all must be a bool")

        if not isinstance(self.retained_artifacts, tuple):
            raise TypeError("retained_artifacts must be a tuple")

        for reference in self.retained_artifacts:
            if type(reference) is int:
                if reference < 0:
                    raise ValueError("retained artifact IDs must be non-negative")
                continue

            if isinstance(reference, (Artifact, ArtifactDefinition)):
                continue

            raise TypeError(
                "retained_artifacts must contain only int, "
                "Artifact, or ArtifactDefinition instances"
            )

        if len(set(self.retained_artifacts)) != len(self.retained_artifacts):
            raise ValueError("retained_artifacts cannot contain duplicate references")

        if self.retain_all and self.retained_artifacts:
            raise ValueError("retained_artifacts must be empty when retain_all is True")

        if not isinstance(self.release_entry_artifacts, bool):
            raise TypeError("release_entry_artifacts must be a bool")


@dataclass(frozen=True, slots=True)
class ContextSettings:
    """Configure execution behavior for one submitted context.

    Args:
        artifact_policy: Artifact retention and entry-release policy.
        retry_policy: Optional override of the engine retry policy.
        max_iterations: Maximum graph iterations, or ``None`` for unbounded
            iteration controlled through runtime supervision.
        max_repeats: Maximum additional executions per step session, or ``None`` for
            no context-level cap.
    """

    artifact_policy: ArtifactPolicy = field(default_factory=ArtifactPolicy)
    retry_policy: RetryPolicy | None = None
    max_iterations: int | None = 1
    max_repeats: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_policy, ArtifactPolicy):
            raise TypeError("artifact_policy must be an ArtifactPolicy instance")

        if self.retry_policy is not None and not isinstance(
            self.retry_policy,
            RetryPolicy,
        ):
            raise TypeError("retry_policy must be a RetryPolicy instance or None")

        self._validate_positive_integer(
            self.max_iterations,
            "max_iterations",
        )
        self._validate_positive_integer(
            self.max_repeats,
            "max_repeats",
        )

    @staticmethod
    def _validate_positive_integer(
        value: int | None,
        name: str,
    ) -> None:
        if isinstance(value, bool):
            raise TypeError(f"{name} must be an int or None")

        if value is None:
            return

        if not isinstance(value, int):
            raise TypeError(f"{name} must be an int or None")

        if value < 1:
            raise ValueError(f"{name} must be greater than or equal to one")
