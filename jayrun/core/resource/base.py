from __future__ import annotations

from abc import ABC, abstractmethod
from functools import wraps
from typing import TYPE_CHECKING, ClassVar

from ..config.field import ConfigField

if TYPE_CHECKING:
    from ...engine.interfaces.context import ContextInterface
    from ...engine.interfaces.execution import ExecutionInterface
    from ...engine.interfaces.placement import PlacementInterface
    from ...engine.interfaces.runtime import RuntimeInterface
    from ..context.runtime_data import Data


class BaseResource(ABC):
    """Base class for a managed value shared with an operator execution.

    Subclasses declare configuration fields in ``__init__`` and implement
    :meth:`setup` and :meth:`teardown`. Jayrun injects the same runtime interfaces
    available to operators. A resource instance is immutable after construction.

    Args:
        name: Optional name used in graph inspection and runtime records.
        description: Optional explanation of the managed resource.
    """

    __version__: ClassVar[str] = "0.1.0"
    requirements: ClassVar[tuple[str, ...]] = ()

    execution: ExecutionInterface
    placement: PlacementInterface
    context: ContextInterface
    runtime: RuntimeInterface

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
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)

        if name is not None and not isinstance(name, str):
            raise TypeError(
                f"{type(self).__name__} 'name' must be str or None, "
                f"got {type(name).__name__!r}"
            )

        if description is not None and not isinstance(description, str):
            raise TypeError(
                f"{type(self).__name__} 'description' must be str or None, "
                f"got {type(description).__name__!r}"
            )

        self._name = name
        self._description = description

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
        def wrapped_init(self: BaseResource, **kwargs: object) -> None:
            original_init(self, **kwargs)

            for attribute_name, value in self.__dict__.items():
                if isinstance(value, ConfigField):
                    value._register(self, attribute_name)

            object.__setattr__(self, "_resource_initialized", True)

        cls.__init__ = wrapped_init

    def __setattr__(self, name: str, value: object) -> None:
        if name in self._RUNTIME_ATTRIBUTE_NAMES:
            raise AttributeError(f"{name!r} is reserved for runtime use")

        if name.startswith("_runtime_"):
            raise AttributeError(f"{name!r} is reserved for runtime use")

        if getattr(self, "_resource_initialized", False):
            raise AttributeError(f"{type(self).__name__} is immutable")

        current = self.__dict__.get(name)

        if isinstance(current, ConfigField):
            raise AttributeError(f"Cannot reassign declarative field {name!r}")

        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        if getattr(self, "_resource_initialized", False):
            raise AttributeError(f"{type(self).__name__} is immutable")

        super().__delattr__(name)

    @property
    def name(self) -> str | None:
        """Optional resource name."""
        return self._name

    @property
    def description(self) -> str | None:
        """Optional resource description."""
        return self._description

    @property
    def config_fields(self) -> tuple[ConfigField, ...]:
        """Configuration fields declared directly by this resource."""
        return tuple(
            value for value in self.__dict__.values() if isinstance(value, ConfigField)
        )

    @property
    def display_name(self) -> str:
        """Configured name, or the resource class name when unnamed."""
        return self.name or type(self).__name__

    @abstractmethod
    def setup(self) -> Data:
        """Create the value supplied to the bound operator field.

        Implementations may be regular or ``async`` methods. The returned
        :class:`~jayrun.Data` records both the value and its placement.
        """
        raise NotImplementedError

    @abstractmethod
    def teardown(self, data: Data) -> None:
        """Release a value previously returned by :meth:`setup`.

        Implementations may be regular or ``async`` methods. Teardown runs after the
        dependent operator execution, including when that execution fails.

        Args:
            data: Resource data created by :meth:`setup`.
        """
        raise NotImplementedError

    def __repr__(self) -> str:
        name = self.name if self.name is not None else "<unnamed>"
        return f"{type(self).__name__}(name={name!r})"
