from dataclasses import dataclass

from ...core.artifact.base import Artifact
from ..artifact.result import ArtifactResult
from ..messages.origin import CommandOrigin
from ..recorders.execution.records import ExecutionReport
from .step_reference import StepReference


@dataclass(frozen=True, slots=True)
class ContextOutcome:
    actor: CommandOrigin
    executions: tuple[ExecutionReport, ...]
    artifacts: dict[Artifact, ArtifactResult] | None
    failure: Exception | None = None
    failed_step: StepReference | None = None
