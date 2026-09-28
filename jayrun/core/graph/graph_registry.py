from __future__ import annotations

import threading
from collections.abc import Iterator
from functools import cached_property
from typing import TYPE_CHECKING

from .graph_definition import GraphDefinition
from .inspection.registry import GraphIdentity, GraphRegistryInspection

if TYPE_CHECKING:
    from ...visualization._facade import Plot
    from .reporting import GraphReporter


class GraphRegistry:
    """Store versioned graph definitions with bidirectional lookup.

    A forward lookup by ``(key, version)`` returns the original
    :class:`~jayrun.GraphDefinition`. A reverse lookup by graph returns its key and
    version. Registering a graph seals its serializer bindings.
    """

    def __init__(self) -> None:
        self._graphs: dict[GraphIdentity, GraphDefinition] = {}
        self._identities: dict[GraphDefinition, GraphIdentity] = {}
        self._lock = threading.RLock()
        self._inspection = GraphRegistryInspection(self)

    def register(self, key: str, graph: GraphDefinition) -> GraphDefinition:
        """Register and return a confirmed graph definition.

        The graph's :attr:`~jayrun.GraphDefinition.version` completes its registry
        identity. Repeating the identical registration is idempotent.

        Args:
            key: Non-empty logical graph key shared by its versions.
            graph: Confirmed graph definition to register.

        Returns:
            The same graph definition supplied by the caller.

        Raises:
            TypeError: If ``key`` or ``graph`` has an unsupported type.
            ValueError: If the key is empty, the identity is occupied, or the graph
                already has another identity in this registry.
            RuntimeError: If the graph is not confirmed.
        """
        self._validate_key(key)
        if not isinstance(graph, GraphDefinition):
            raise TypeError("graph must be a GraphDefinition instance")
        if not graph.confirmed:
            raise RuntimeError("The graph must be confirmed before registration.")

        identity = (key, graph.version)

        with self._lock:
            registered = self._graphs.get(identity)
            if registered is not None:
                if registered is graph:
                    graph._seal()
                    return graph
                raise ValueError(
                    f"Graph identity {identity!r} is already registered."
                )

            previous_identity = self._identities.get(graph)
            if previous_identity is not None:
                raise ValueError(
                    f"The graph is already registered as {previous_identity!r}."
                )

            graph._compiled_graph
            graph._seal()
            self._graphs[identity] = graph
            self._identities[graph] = identity
            return graph

    def __getitem__(
        self,
        reference: GraphIdentity,
    ) -> GraphDefinition:
        """Resolve a ``(key, version)`` identity."""
        if isinstance(reference, tuple):
            if len(reference) != 2:
                raise TypeError("graph identity must be a (key, version) tuple")
            key, version = reference
            if not isinstance(key, str) or not isinstance(version, str):
                raise TypeError("graph identity must contain strings")
            return self.graph_for(key, version)
        raise TypeError(
            "registry references must be (key, version)"
        )

    def graph_for(self, key: str, version: str) -> GraphDefinition:
        """Return the graph registered under ``(key, version)``."""
        self._validate_key(key)
        if not isinstance(version, str):
            raise TypeError("version must be a string")

        with self._lock:
            try:
                return self._graphs[(key, version)]
            except KeyError:
                raise KeyError(
                    f"Graph {(key, version)!r} is not registered."
                ) from None

    def identity_for(self, graph: GraphDefinition) -> GraphIdentity:
        """Return ``(key, version)`` for a graph in this registry."""
        if not isinstance(graph, GraphDefinition):
            raise TypeError("graph must be a GraphDefinition instance")
        with self._lock:
            try:
                return self._identities[graph]
            except KeyError:
                raise KeyError(
                    "The graph is not registered in this registry."
                ) from None

    def key_for(self, graph: GraphDefinition) -> str:
        """Return the logical key assigned to a graph in this registry."""
        return self.identity_for(graph)[0]

    def versions(self, key: str) -> tuple[str, ...]:
        """Return versions registered for ``key`` in registration order."""
        self._validate_key(key)
        with self._lock:
            return tuple(
                version
                for registered_key, version in self._graphs
                if registered_key == key
            )

    @property
    def graphs(self) -> tuple[GraphDefinition, ...]:
        """Registered graph definitions in registration order."""
        with self._lock:
            return tuple(self._graphs.values())

    @property
    def identities(self) -> tuple[GraphIdentity, ...]:
        """Registered ``(key, version)`` identities in registration order."""
        with self._lock:
            return tuple(self._graphs)

    @property
    def inspect(self) -> GraphRegistryInspection:
        """Live graph, resource-sharing, serializer, and requirement inspection."""
        return self._inspection

    @cached_property
    def report(self) -> GraphReporter:
        """Live registry overview, shared resources, conflicts, and graph reports."""
        from .reporting import GraphReporter, _format_registry

        return GraphReporter(
            lambda compact: _format_registry(self, compact), "graph_registry_report.txt"
        )

    @cached_property
    def plot(self) -> Plot:
        """Offline selector over a fresh coherent snapshot of registered graphs.

        show() opens the viewer; save(path) embeds every included graph. Existing
        saved/opened views never monitor later registrations; show/save again to
        refresh. Viewing does not register, bind, or execute work.
        """
        from ...visualization.adapters.registry import registry_plot

        return registry_plot(self)

    def __iter__(self) -> Iterator[GraphIdentity]:
        return iter(self.identities)

    def __len__(self) -> int:
        with self._lock:
            return len(self._graphs)

    def __contains__(self, reference: object) -> bool:
        with self._lock:
            if isinstance(reference, GraphDefinition):
                return reference in self._identities
            if isinstance(reference, tuple) and len(reference) == 2:
                return (
                    isinstance(reference[0], str)
                    and isinstance(reference[1], str)
                    and reference in self._graphs
                )
            return False

    def _entries(self) -> tuple[tuple[GraphIdentity, GraphDefinition], ...]:
        with self._lock:
            return tuple(self._graphs.items())

    @staticmethod
    def _validate_key(key: str) -> None:
        if not isinstance(key, str):
            raise TypeError("key must be a string")
        if not key.strip():
            raise ValueError("key must not be empty")
