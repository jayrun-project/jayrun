"""Public types returned by graph inspection and reporting.

Obtain views through graph.inspect and graph.report; these exports support
annotations and result inspection, without exposing the compiled execution plan.
"""

from .core.graph.definition import (
    ArtifactDefinition,
    ArtifactRole,
    ConfigDefinition,
    ResourceDefinition,
    RequirementDefinition,
    SerializerDefinition,
)
from .core.graph.operator_reference import OperatorReference
from .core.graph.inspection.graph import GraphInspection
from .core.graph.inspection.artifact import ArtifactInspection
from .core.graph.inspection.field import FieldInspection
from .core.graph.inspection.resource import ResourceInspection
from .core.graph.inspection.requirement import RequirementInspection
from .core.graph.inspection.serializer import SerializerInspection
from .core.graph.reporting import GraphReporter

from .visualization.adapters.definition import GraphPlotter

__all__ = (
    "GraphPlotter",
    "ArtifactDefinition",
    "ArtifactRole",
    "ConfigDefinition",
    "ResourceDefinition",
    "RequirementDefinition",
    "SerializerDefinition",
    "OperatorReference",
    "GraphInspection",
    "ArtifactInspection",
    "FieldInspection",
    "ResourceInspection",
    "RequirementInspection",
    "SerializerInspection",
    "GraphReporter",
)
