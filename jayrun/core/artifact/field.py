from __future__ import annotations

from dataclasses import dataclass, field

from ..declaration.field import DeclarativeField
from .base import Artifact
from .properties import ArtifactProperty


@dataclass(slots=True, frozen=True, kw_only=True, eq=False)
class ArtifactField(DeclarativeField):
    """Declare an operator input or output artifact contract.

    Args:
        name: Optional display name.
        description: Optional explanation of the artifact contract.
        required: Whether the field must be connected. Input fields enforce this
            during operator construction; output fields may still be bound to
            ``None`` to disable a route.
        properties: Optional tuple of artifact properties used by graph validation.
    """

    properties: tuple[ArtifactProperty, ...] | None = None
    artifact: Artifact | None = field(init=False, default=None, repr=False)
    is_bound: bool = field(init=False, default=False, repr=False)

    def __post_init__(self) -> None:
        DeclarativeField.__post_init__(self)

        if self.properties is None:
            object.__setattr__(self, "properties", ())
            return

        if not isinstance(self.properties, tuple):
            raise TypeError(
                f"'properties' must be a tuple of ArtifactProperty instances or None, "
                f"got {type(self.properties).__name__!r}"
            )

        properties_by_type = list()

        for artifact_property in self.properties:
            if not isinstance(artifact_property, ArtifactProperty):
                raise TypeError(
                    f"'properties' must contain only ArtifactProperty instances, "
                    f"got {type(artifact_property).__name__!r}"
                )
            property_type = type(artifact_property)

            if property_type in properties_by_type:
                raise ValueError(
                    f"Duplicate artifact property: {property_type.__name__}."
                )
            properties_by_type.append(property_type)

    def bind(self, artifact: Artifact | None) -> None:
        """Bind this input field to an artifact exactly once.

        Args:
            artifact: Artifact to consume, or ``None`` for an optional field.

        Raises:
            RuntimeError: If the field is already bound.
            TypeError: If ``artifact`` has an unsupported type.
            ValueError: If a required field is bound to ``None``.
        """
        self._bind(artifact, enforce_required=True)

    def _bind(
        self,
        artifact: Artifact | None,
        *,
        enforce_required: bool,
    ) -> None:
        if self.is_bound:
            raise RuntimeError(f"{type(self).__name__} is already bound")

        if artifact is not None and not isinstance(artifact, Artifact):
            raise TypeError(
                f"'artifact' must be an Artifact or None, "
                f"got {type(artifact).__name__!r}"
            )

        if enforce_required and artifact is None and self.required:
            raise ValueError(
                f"Required artifact field {self.display_name!r} cannot be bound to None"
            )

        object.__setattr__(self, "artifact", artifact)
        object.__setattr__(self, "is_bound", True)
