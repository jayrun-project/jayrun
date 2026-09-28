from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core.graph.graph_definition import GraphDefinition
    from .persistence import DatabaseReader


@dataclass(frozen=True, slots=True, init=False)
class Supervisor:
    """Grant a submitted context authority over other context runs.

    Args:
        *graphs: Exact graph objects whose contexts may be observed and controlled.
            When omitted, the authority covers every graph in the engine.
    """

    graphs: tuple[GraphDefinition, ...]

    def __init__(self, *graphs: GraphDefinition) -> None:
        object.__setattr__(self, "graphs", graphs)


@dataclass(frozen=True, slots=True)
class Controller:
    """Grant engine-wide observation and control to a submitted context.

    A controller may also submit registered graph identities through
    ``self.runtime.submit(...)`` and asynchronously request engine shutdown.
    Controller contexts execute locally through supervision capacity and cannot
    be transferred. An optional ``history`` reader explicitly grants its existing
    session scope. The runtime lends an attenuated view for this controller
    lifetime; it cannot close/flush the store or acquire additional live rights.
    """

    history: DatabaseReader | None = None

    def __post_init__(self) -> None:
        # A history grant is local, explicit and independent of live authority.
        # Default Controller() does not import persistence or reveal its store.
        if self.history is not None:
            from .persistence import DatabaseReader
            if type(self.history) is not DatabaseReader:
                raise TypeError("history must be a DatabaseReader or None")
