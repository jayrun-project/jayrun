"""A small lazy snapshot facade, shared by declaration adapters."""
from collections.abc import Callable
from pathlib import Path

from . import renderer


class Plot:
    def __init__(self, snapshot: Callable[[], dict]) -> None:
        self._snapshot = snapshot

    def build(self) -> dict:
        """Return a fresh portable snapshot, including current declared bindings."""
        return self._snapshot()

    def to_html(self) -> str:
        return renderer.render_html(self.build())

    def show(self) -> Path:
        return renderer.show(self.build())

    def save(self, path: str | Path) -> Path:
        return renderer.save(self.build(), path)
