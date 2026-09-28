from __future__ import annotations

from functools import cached_property

from ..artifact.base import Artifact
from ..operator.base import BaseOperator
from .graph_component import GraphComponent


class ArtifactFlow(GraphComponent):
    """Order the operators that consume one artifact.

    Nested flows are allowed when they refer to the same artifact. A flow describes
    consumption order; an operator may consume several artifacts and therefore
    appear in several flows. The first operator may instead have no artifact inputs,
    making it an independent graph root. Later operators must consume the flow
    artifact. A one-operator, artifact-free flow represents an independent operator
    with no artifact input, such as a supervisor.

    Args:
        *components: Operators or nested flows in consumption order.
        artifact: Artifact consumed by the flow's operators. This may be omitted only
            for a one-operator flow whose operator has no artifact inputs.
        name: Optional flow name.
        description: Optional flow description.
    """

    def __init__(
        self,
        *components: GraphComponent,
        artifact: Artifact | None = None,
        name: str | None = None,
        description: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(
            name=name,
            description=description,
            **kwargs,
        )

        if artifact is not None and not isinstance(artifact, Artifact):
            raise TypeError(
                "'artifact' must be an Artifact or None, "
                f"got {type(artifact).__name__!r}"
            )

        if not components:
            raise ValueError("ArtifactFlow must contain at least one component")

        self._artifact = artifact
        self._components = components

        for component in components:
            self._validate_component(component, artifact)

        self._validate_operator_sequence()

    @staticmethod
    def _validate_component(
        component: GraphComponent,
        artifact: Artifact | None,
    ) -> None:
        if isinstance(component, ArtifactFlow):
            if component.artifact is not artifact:
                raise ValueError(
                    f"Nested artifact flow {component.artifact!r} "
                    f"does not match {artifact!r}"
                )

            return

        if isinstance(component, BaseOperator):
            return

        raise TypeError(
            f"ArtifactFlow components must be BaseOperator or "
            f"ArtifactFlow instances, got {type(component).__name__!r}"
        )

    def _validate_operator_sequence(self) -> None:
        operators = self.operators
        first, *remaining = operators

        if self.artifact is None:
            if first.input_artifacts:
                raise ValueError(
                    "An artifact-free flow must start with an operator that has "
                    "no artifact inputs"
                )
            if remaining:
                raise ValueError(
                    "An artifact-free flow can contain only one operator"
                )
            return

        if first.input_artifacts and not self._consumes_flow_artifact(first):
            raise ValueError(
                f"First operator {first.display_name!r} neither starts without "
                f"artifact inputs nor consumes flow artifact {self.artifact!r}"
            )

        for operator in remaining:
            if not self._consumes_flow_artifact(operator):
                raise ValueError(
                    f"Only the first operator may have no flow-artifact input; "
                    f"operator {operator.display_name!r} does not consume "
                    f"artifact {self.artifact!r}"
                )

    def _consumes_flow_artifact(self, operator: BaseOperator) -> bool:
        return any(
            input_artifact is self.artifact
            for input_artifact in operator.input_artifacts
        )

    @property
    def artifact(self) -> Artifact | None:
        """Artifact carried by this flow, or ``None`` for an artifact-free root."""
        return self._artifact

    @property
    def components(self) -> tuple[GraphComponent, ...]:
        """Direct operators and nested flows in declaration order."""
        return self._components

    @property
    def operators(self) -> tuple[BaseOperator, ...]:
        """Flattened operator sequence for this flow."""
        return self._operators

    @cached_property
    def _operators(self) -> tuple[BaseOperator, ...]:
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
