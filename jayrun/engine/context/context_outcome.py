from dataclasses import dataclass

from ...core.artifact.base import Artifact
from ..artifact.result import ArtifactResult
from ..recorders.execution.records import ExecutionReport
from ..registry.identities import BaseIdentity
from .step_reference import StepReference


@dataclass(frozen=True, slots=True)
class ContextOutcome:
    actor: BaseIdentity
    executions: tuple[ExecutionReport, ...]
    artifacts: dict[Artifact, ArtifactResult] | None
    failure: Exception | None = None
    failed_step: StepReference | None = None
