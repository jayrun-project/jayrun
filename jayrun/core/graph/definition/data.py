from dataclasses import dataclass


@dataclass(slots=True, frozen=True, kw_only=True)
class DataDefinition:
    """Immutable name and description captured during graph inspection."""

    name: str | None
    description: str | None
