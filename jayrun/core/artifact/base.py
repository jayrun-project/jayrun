from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class Artifact:
    """Declare a named value that moves through a graph.

    An artifact describes identity and intent; its runtime value is supplied through
    an :class:`~jayrun.ArtifactContext` or produced by an operator. Declarations use
    identity semantics, so two artifacts with the same name remain distinct.

    Args:
        name: Optional human-readable name used in reports and graph plots.
        description: Optional explanation of the value represented by the artifact.
    """

    name: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        if self.name is not None and not isinstance(self.name, str):
            raise TypeError(
                f"{type(self).__name__} 'name' must be str or None, got {type(self.name).__name__!r}"
            )

        if self.description is not None and not isinstance(self.description, str):
            raise TypeError(
                f"{type(self).__name__} 'description' must be str or None, got {type(self.description).__name__!r}"
            )

    def __repr__(self) -> str:
        name = self.name if self.name is not None else "<unnamed>"
        return f"{type(self).__name__}(name={name!r})"
