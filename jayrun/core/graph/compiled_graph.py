from __future__ import annotations

from dataclasses import dataclass
from types import FunctionType

from ...engine.execution.execution_mode import ExecutionMode
from ..artifact.base import Artifact
from ..artifact.field import ArtifactField
from ..config.field import ConfigField
from ..resource.base import BaseResource
from ..resource.field import ResourceField
from .definition import RequirementDefinition


@dataclass(slots=True, frozen=True, kw_only=True)
class CompiledStep:
    group_indices: tuple[int, ...]
    successor_indices: frozenset[int]
    initial_dependency_count: int
    output_mask: tuple[bool, ...]
    execution_mode: ExecutionMode
    layout_position: tuple[int, int]
    requirements: tuple[RequirementDefinition, ...]


@dataclass(slots=True, frozen=True, kw_only=True)
class CompiledOperatorStep(CompiledStep):
    execute_method: FunctionType
    bound_artifact_fields: tuple[ArtifactField, ...]
    declared_artifact_fields: tuple[ArtifactField, ...]
    config_fields: tuple[ConfigField, ...]
    bound_resources: tuple[tuple[ResourceField, BaseResource], ...]
    output_fields: tuple[ArtifactField, ...]
    operator_name: str


@dataclass(slots=True, frozen=True, kw_only=True)
class CompiledResourceStep(CompiledStep):
    resource_field: ResourceField
    resource: BaseResource
    config_fields: tuple[ConfigField, ...]
    setup_method: FunctionType
    teardown_method: FunctionType
    resource_name: str


@dataclass(slots=True, frozen=True, kw_only=True)
class CompiledGraph:
    steps: tuple[CompiledStep, ...]
    entry_artifacts: tuple[Artifact, ...]
    artifacts: tuple[Artifact, ...]
    initial_dependency_counts: tuple[int, ...]
    requirements: tuple[RequirementDefinition, ...]
