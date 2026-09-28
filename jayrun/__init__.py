"""Public graph construction, execution, and data-context API.

Exports are resolved on demand so the portable visualization package can be
imported without loading execution, declaration, or validation modules.
"""
from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .authority import Controller, Supervisor
    from .core.artifact.base import Artifact
    from .core.artifact.context import ArtifactContext
    from .core.artifact.field import ArtifactField
    from .core.config.context import ConfigContext
    from .core.config.field import ConfigField
    from .core.context.runtime_data import Data
    from .core.graph.artifact_flow import ArtifactFlow
    from .core.graph.graph_definition import GraphDefinition
    from .core.operator.base import BaseOperator
    from .core.resource.base import BaseResource
    from .core.resource.field import ResourceField
    from .core.serializer.base import BaseSerializer
    from .engine.api import Engine
    from .engine.engine_state import EngineState, RuntimeActivity
    from .registry import GraphRegistry

__version__ = "0.3.0"

__all__ = (
    "__version__", "Artifact", "ArtifactContext", "ArtifactField", "ArtifactFlow",
    "BaseOperator", "BaseResource", "BaseSerializer", "ConfigContext", "ConfigField",
    "Controller", "Data", "Engine", "EngineState", "RuntimeActivity", "GraphDefinition", "GraphRegistry",
    "ResourceField", "Supervisor",
)

_EXPORTS = {
    "Artifact": ".core.artifact.base", "ArtifactContext": ".core.artifact.context",
    "ArtifactField": ".core.artifact.field", "ArtifactFlow": ".core.graph.artifact_flow",
    "BaseOperator": ".core.operator.base", "BaseResource": ".core.resource.base",
    "BaseSerializer": ".core.serializer.base", "ConfigContext": ".core.config.context",
    "ConfigField": ".core.config.field", "Controller": ".authority",
    "Data": ".core.context.runtime_data", "Engine": ".engine.api",
    "EngineState": ".engine.engine_state", "RuntimeActivity": ".engine.engine_state",
    "GraphDefinition": ".core.graph.graph_definition", "GraphRegistry": ".registry",
    "ResourceField": ".core.resource.field", "Supervisor": ".authority",
}


def __getattr__(name: str) -> object:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
