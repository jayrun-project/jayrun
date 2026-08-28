from dataclasses import dataclass


@dataclass(slots=True, frozen=True, kw_only=True)
class RequirementDefinition:
    """Normalized Python package requirement discovered from a component."""

    name: str
    extras: tuple[str, ...]
    specifier: str
    marker: str | None

    def __str__(self) -> str:
        extras = f"[{','.join(self.extras)}]" if self.extras else ""
        marker = f"; {self.marker}" if self.marker is not None else ""
        return f"{self.name}{extras}{self.specifier}{marker}"
