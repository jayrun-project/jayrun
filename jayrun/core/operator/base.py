from __future__ import annotations

from abc import ABC, abstractmethod
from functools import wraps
from typing import TYPE_CHECKING, ClassVar

from ..artifact.base import Artifact
from ..artifact.field import ArtifactField
from ..config.field import ConfigField
from ..declaration.field import DeclarativeField
from ..graph.graph_component import GraphComponent
from ..resource.field import ResourceField

if TYPE_CHECKING:
    from ...engine.interfaces.context import ContextInterface
    from ...engine.interfaces.execution import ExecutionInterface
    from ...engine.interfaces.placement import PlacementInterface
    from ...engine.interfaces.runtime import RuntimeInterface


class BaseOperator(GraphComponent, ABC):
    """Base class for synchronous or asynchronous graph operations.

    Subclasses declare artifact, config, and resource fields in ``__init__`` and
    implement :meth:`execute`. During execution Jayrun injects ``execution``,
    ``placement``, ``context``, and ``runtime`` interfaces. Operator instances become
    immutable after construction.

    Args:
        name: Optional name used in graph inspection and runtime records.
        description: Optional explanation of the operation.
    """

    __version__: ClassVar[str] = "0.1.0"
    requirements: ClassVar[tuple[str, ...]] = ()

    execution: ExecutionInterface
    placement: PlacementInterface
    context: ContextInterface
    runtime: RuntimeInterface
    outputs: tuple[ArtifactField, ...]

    _RUNTIME_ATTRIBUTE_NAMES: ClassVar[frozenset[str]] = frozenset(
        {
            "execution",
            "placement",
            "context",
            "runtime",
        }
    )

    def __init__(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)

        declared_names = set(cls.__dict__)
        declared_names.update(cls.__dict__.get("__annotations__", {}))

        for attribute_name in declared_names:
            if (
                attribute_name in cls._RUNTIME_ATTRIBUTE_NAMES
                or attribute_name.startswith("_runtime_")
            ):
                raise TypeError(
                    f"{cls.__name__} cannot declare reserved attribute "
                    f"{attribute_name!r}"
                )

        original_init = cls.__init__

        @wraps(original_init)
        def wrapped_init(self: BaseOperator, **kwargs: object) -> None:
            original_init(self, **kwargs)

            self._register_declarative_fields()
            self._bind_input_artifacts(kwargs)
            self._bind_output_artifacts(kwargs)
            object.__setattr__(self, "_operator_initialized", True)

        cls.__init__ = wrapped_init

    def _register_declarative_fields(self) -> None:
        for attribute_name, value in self.__dict__.items():
            if isinstance(value, DeclarativeField):
                value._register(self, attribute_name)

        if "outputs" not in self.__dict__:
            raise TypeError(f"{type(self).__name__} must define 'self.outputs'")

        if not isinstance(self.outputs, tuple):
            raise TypeError("'self.outputs' must be a tuple")

        for index, field in enumerate(self.outputs):
            if not isinstance(field, ArtifactField):
                raise TypeError(
                    "'self.outputs' must contain only ArtifactField instances"
                )

            field._register(self, f"outputs[{index}]")

    def _bind_input_artifacts(
        self,
        arguments: dict[str, object],
    ) -> None:
        input_fields = self.declared_artifact_fields

        for field in input_fields:
            attribute_name = field.attribute_name

            if attribute_name is None:
                raise RuntimeError("ArtifactField is not registered")

            if attribute_name not in arguments:
                raise TypeError(f"Missing artifact argument {attribute_name!r}")

            field.bind(arguments[attribute_name])

        self._validate_artifact_group(
            input_fields,
            group_name="input",
            require_connected=True,
        )

    def _bind_output_artifacts(
        self,
        arguments: dict[str, object],
    ) -> None:
        if "outputs" not in arguments:
            if not self.outputs:
                return

            raise TypeError("'outputs' argument is required")

        output_artifacts = arguments["outputs"]

        if not isinstance(output_artifacts, tuple):
            raise TypeError("'outputs' must be a tuple")

        if len(output_artifacts) != len(self.outputs):
            raise ValueError(
                "Number of output artifacts does not match the declared output fields"
            )

        for field, artifact in zip(self.outputs, output_artifacts):
            field._bind(artifact, enforce_required=False)

        self._validate_artifact_group(
            self.outputs,
            group_name="output",
            require_connected=False,
        )

    @staticmethod
    def _validate_artifact_group(
        fields: tuple[ArtifactField, ...], *, group_name: str, require_connected: bool
    ) -> None:
        artifacts = tuple(
            field.artifact for field in fields if field.artifact is not None
        )

        if require_connected and not artifacts:
            raise ValueError(
                f"An operator must have at least one connected {group_name} artifact"
            )

        artifact_ids = {id(artifact) for artifact in artifacts}

        if len(artifact_ids) != len(artifacts):
            raise ValueError(
                f"Multiple {group_name} fields cannot use the same artifact"
            )

    def __setattr__(self, name: str, value: object) -> None:
        if name in self._RUNTIME_ATTRIBUTE_NAMES:
            raise AttributeError(f"{name!r} is reserved for runtime use")

        if name.startswith("_runtime_"):
            raise AttributeError(f"{name!r} is reserved for runtime use")

        if getattr(self, "_operator_initialized", False):
            raise AttributeError(f"{type(self).__name__} is immutable")

        if name == "outputs" and "outputs" in self.__dict__:
            raise AttributeError("Cannot reassign declarative field 'outputs'")

        current = self.__dict__.get(name)

        if isinstance(current, DeclarativeField):
            raise AttributeError(f"Cannot reassign declarative field {name!r}")

        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        if getattr(self, "_operator_initialized", False):
            raise AttributeError(f"{type(self).__name__} is immutable")

        super().__delattr__(name)

    @property
    def config_fields(self) -> tuple[ConfigField, ...]:
        """Configuration fields declared directly by this operator."""
        return tuple(
            value for value in self.__dict__.values() if isinstance(value, ConfigField)
        )

    @property
    def resource_fields(self) -> tuple[ResourceField, ...]:
        """Resource fields declared directly by this operator."""
        return tuple(
            value
            for value in self.__dict__.values()
            if isinstance(value, ResourceField)
        )

    @property
    def declared_artifact_fields(self) -> tuple[ArtifactField, ...]:
        """Artifact input fields declared directly by this operator."""
        return tuple(
            value
            for value in self.__dict__.values()
            if isinstance(value, ArtifactField)
        )

    @property
    def bound_artifact_fields(self) -> tuple[ArtifactField, ...]:
        """Declared input fields that are connected to artifacts."""
        return tuple(
            field
            for field in self.declared_artifact_fields
            if field.artifact is not None
        )

    @property
    def input_artifacts(self) -> tuple[Artifact, ...]:
        """Artifacts consumed by connected input fields."""
        return tuple(
            field.artifact
            for field in self.declared_artifact_fields
            if field.artifact is not None
        )

    @property
    def output_artifacts(self) -> tuple[Artifact, ...]:
        """Artifacts produced by connected output fields."""
        return tuple(
            field.artifact for field in self.outputs if field.artifact is not None
        )

    @property
    def display_name(self) -> str:
        """Configured name, or the operator class name when unnamed."""
        if self.name is None:
            return type(self).__name__

        return self.name

    @abstractmethod
    def execute(self) -> object | tuple[object, ...]:
        """Perform one execution and return values for connected outputs.

        Implementations may be regular or ``async`` methods. Return one value per
        declared output field; values corresponding to outputs bound to ``None`` are
        ignored by the runtime.
        """
        raise NotImplementedError

    def __repr__(self) -> str:
        name = self.name if self.name is not None else "<unnamed>"
        return f"{type(self).__name__}(name={name!r})"
