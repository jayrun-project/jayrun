from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..operator.base import BaseOperator
    from ..resource.base import BaseResource


@dataclass(slots=True, frozen=True, kw_only=True, eq=False)
class DeclarativeField:
    name: str | None = None
    description: str | None = None
    required: bool = True

    owner: BaseOperator | BaseResource | None = field(
        init=False,
        default=None,
        repr=False,
    )
    attribute_name: str | None = field(
        init=False,
        default=None,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.name is not None and not isinstance(self.name, str):
            raise TypeError("'name' must be str or None")

        if self.description is not None and not isinstance(self.description, str):
            raise TypeError("'description' must be str or None")

        if not isinstance(self.required, bool):
            raise TypeError("'required' must be bool")

    @property
    def display_name(self) -> str:
        """Explicit name, registered attribute name, or ``<unnamed>``."""
        return self.name or self.attribute_name or "<unnamed>"

    def _register(
        self,
        owner: BaseOperator | BaseResource,
        attribute_name: str,
    ) -> None:
        if self.owner is not None:
            raise RuntimeError(f"{type(self).__name__} is already bound.")

        object.__setattr__(self, "owner", owner)
        object.__setattr__(self, "attribute_name", attribute_name)
