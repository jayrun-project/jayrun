from __future__ import annotations

from functools import cached_property

from ..artifact.base import Artifact
from ..operator.base import BaseOperator
from .graph_component import GraphComponent


class ArtifactFlow(GraphComponent):
    """Order the operators that consume one artifact.

    Nested flows are allowed when they refer to the same artifact. A flow describes
    consumption order; an operator may consume several artifacts and therefore
    appear in several flows.

    Args:
        *components: Operators or nested flows in consumption order.
        artifact: Artifact consumed by every component.
        name: Optional flow name.
        description: Optional flow description.
    """

    def __init__(
        self,
        *components: GraphComponent,
        artifact: Artifact,
        name: str | None = None,
        description: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(
            name=name,
            description=description,
            **kwargs,
        )

        if not isinstance(artifact, Artifact):
            raise TypeError(
                f"'artifact' must be an Artifact, got {type(artifact).__name__!r}"
            )

        if not components:
            raise ValueError("ArtifactFlow must contain at least one component")

        for component in components:
            self._validate_component(component, artifact)

        self._artifact = artifact
        self._components = components

    @staticmethod
    def _validate_component(
        component: GraphComponent,
        artifact: Artifact,
    ) -> None:
        if isinstance(component, ArtifactFlow):
            if component.artifact is not artifact:
                raise ValueError(
                    f"Nested artifact flow {component.artifact!r} "
                    f"does not match {artifact!r}"
                )

            return

        if isinstance(component, BaseOperator):
            if any(
                input_artifact is artifact
                for input_artifact in component.input_artifacts
            ):
                return

            raise ValueError(
                f"Operator {component.display_name!r} does not consume "
                f"artifact {artifact!r}"
            )

        raise TypeError(
            f"ArtifactFlow components must be BaseOperator or "
            f"ArtifactFlow instances, got {type(component).__name__!r}"
        )

    @property
    def artifact(self) -> Artifact:
        """Artifact carried by this flow."""
        return self._artifact

    @property
    def components(self) -> tuple[GraphComponent, ...]:
        """Direct operators and nested flows in declaration order."""
        return self._components

    @cached_property
    def operators(self) -> tuple[BaseOperator, ...]:
        """Flattened operator sequence for this flow."""
        operators: list[BaseOperator] = []

        for component in self._components:
            if isinstance(component, BaseOperator):
                operators.append(component)
            else:
                operators.extend(component.operators)

        return tuple(operators)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}"
            f"(name={self.name!r}, artifact={self.artifact!r}, "
            f"components={len(self.components)})"
        )
