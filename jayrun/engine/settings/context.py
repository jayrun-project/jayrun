from dataclasses import dataclass, field
import sys
from typing import TypeAlias

from .._snapshot_compat import restore_settings
from ...core.artifact.base import Artifact
from ...core.graph.definition.artifact import ArtifactDefinition
from .engine import RetryPolicy

ArtifactReference: TypeAlias = int | Artifact | ArtifactDefinition


@dataclass(frozen=True, slots=True, kw_only=True)
class ArtifactPolicy:
    """Control which artifact values remain available after execution.

    Args:
        retained_artifacts: Explicit exit-artifact IDs, declarations, or inspected
            definitions to retain; None retains all exits and () retains none.
        release_entry_artifacts: Release submitted entry values as soon as graph
            execution no longer needs them, then empty any remaining submitted
            artifact context and recovery checkpoint at finalization.
    """

    retained_artifacts: tuple[ArtifactReference, ...] | None = None
    release_entry_artifacts: bool = False

    def __post_init__(self) -> None:
        if self.retained_artifacts is not None and not isinstance(self.retained_artifacts, tuple):
            raise TypeError("retained_artifacts must be a tuple")

        for reference in self.retained_artifacts or ():
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

        if len(set(self.retained_artifacts or ())) != len(self.retained_artifacts or ()):
            raise ValueError("retained_artifacts cannot contain duplicate references")

        if not isinstance(self.release_entry_artifacts, bool):
            raise TypeError("release_entry_artifacts must be a bool")


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


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordPolicy:
    """Bound application values written through a context's record interface.

    Args:
        history_per_key: Keep the latest N committed records per key. None
            keeps every admitted record for that key.
        max_keys: Maximum distinct keys across retained and pending records.
        max_value_bytes: Maximum accounted bytes per value, up to 64 MiB.
        max_total_bytes: Maximum accounted bytes across retained and pending values.
    """

    history_per_key: int | None = 64
    max_keys: int = 256
    max_value_bytes: int = 65_536
    max_total_bytes: int = 8_388_608

    def __post_init__(self) -> None:
        _validate_positive_integer(self.history_per_key, "history_per_key")
        for name in ("max_keys", "max_value_bytes", "max_total_bytes"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_value_bytes > 64 * 1024 * 1024:
            raise ValueError("max_value_bytes cannot exceed 64 MiB")


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextSettings:
    """Configure execution behavior for one submitted context.

    Args:
        artifact_policy: Artifact retention and entry-release policy.
        retry_policy: Optional override of the engine retry policy.
        max_iterations: Maximum graph iterations, or ``None`` for unbounded
            iteration controlled through runtime supervision.
        max_repeats: Maximum additional executions per step session, or ``None`` for
            no context-level cap.
        execution_history_limit: Number of recent graph iterations with detailed
            step reports. Also bounds lifecycle entries and diagnostic transitions
            per artifact. None keeps full native history (the default).
        record_policy: Retention and admission limits for application records.
    """

    __setstate__ = restore_settings

    artifact_policy: ArtifactPolicy = field(default_factory=ArtifactPolicy)
    retry_policy: RetryPolicy | None = None
    max_iterations: int | None = 1
    max_repeats: int | None = None
    execution_history_limit: int | None = None
    record_policy: RecordPolicy = field(default_factory=RecordPolicy)

    def __post_init__(self) -> None:
        _validate_positive_integer(self.execution_history_limit, "execution_history_limit")
        if self.execution_history_limit is not None and self.execution_history_limit > sys.maxsize:
            raise ValueError("execution_history_limit exceeds the maximum collection size")
        if not isinstance(self.record_policy, RecordPolicy):
            raise TypeError("record_policy must be a RecordPolicy instance")
        if not isinstance(self.artifact_policy, ArtifactPolicy):
            raise TypeError("artifact_policy must be an ArtifactPolicy instance")

        if self.retry_policy is not None and not isinstance(
            self.retry_policy,
            RetryPolicy,
        ):
            raise TypeError("retry_policy must be a RetryPolicy instance or None")

        _validate_positive_integer(
            self.max_iterations,
            "max_iterations",
        )
        if self.max_repeats is not None and type(self.max_repeats) is not int:
            raise TypeError("max_repeats must be an int or None")
        if self.max_repeats is not None and self.max_repeats < 0:
            raise ValueError("max_repeats must be a non-negative int or None")
