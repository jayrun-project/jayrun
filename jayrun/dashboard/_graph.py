"""Normal graph/resource ownership for the optional dashboard."""
import asyncio
import math
from dataclasses import dataclass

from .. import ArtifactContext, ArtifactFlow, BaseOperator, BaseResource, ConfigContext, ConfigField, Data, GraphDefinition, ResourceField
from ..settings import ContextSettings


@dataclass(frozen=True, slots=True)
class DashboardSubmission:
    """Named inputs for normal Engine.submit; authority stays with the caller.

    The bundle is immutable, but its graph follows GraphDefinition's existing
    binding/registration rules. None uses the ordinary submission defaults.
    Preparing these inputs performs no execution, hosting or storage work.
    """
    graph: GraphDefinition
    artifacts: ArtifactContext | None = None
    configs: ConfigContext | None = None
    settings: ContextSettings | None = None


class _HTTPResource(BaseResource):
    def __init__(self, *, host, port, recent_window_seconds=1800, max_recent_contexts=1000):
        super().__init__(name='Dashboard HTTP service')
        self.host = ConfigField(value_type=str, required=False, default=host)
        self.port = ConfigField(value_type=int, required=False, default=port)
        self.recent_window_seconds = ConfigField(value_type=float, required=False, default=float(recent_window_seconds))
        self.max_recent_contexts = ConfigField(value_type=int, required=False, default=max_recent_contexts)

    async def setup(self):
        from ._service import _Host
        if type(self.port.value) is not int or not 0<=self.port.value<=65535:
            raise ValueError('port must be between 0 and 65535')
        if not self.host.value.strip():raise ValueError('host must be nonempty')
        if not 1<=self.max_recent_contexts.value<=10000:
            raise ValueError('max_recent_contexts must be from 1 to 10000')
        if not math.isfinite(self.recent_window_seconds.value) or self.recent_window_seconds.value<=0:
            raise ValueError('recent_window_seconds must be positive and finite')
        return Data(value=_Host(self.host.value, self.port.value,
            recent_window_seconds=self.recent_window_seconds.value,
            max_recent_contexts=self.max_recent_contexts.value))

    async def teardown(self, data):
        await data.value.close()


class _Observe(BaseOperator):
    def __init__(self, *, duration):
        super().__init__(name='Dashboard controller')
        self.http = ResourceField()
        self.duration = ConfigField(value_type=float, required=False, default=None if duration is None else float(duration))
        self.outputs = ()

    async def execute(self):
        owner = self.http.value
        # Historical access is explicitly granted through submission authority,
        # not carried in graph configs or cached with the HTTP resource.
        service = await owner.open(self.runtime, self.context)
        try:
            self.context.record('dashboard_url', service.url)
            print(f'Jayrun dashboard: {service.url}', flush=True)
            await service.serve(None if self.duration is None else self.duration.value)
        finally:
            # Resources may remain cached beyond this context. Close at the
            # controller boundary as well; teardown is an idempotent backstop.
            try:
                await service.close()
            finally:
                owner.services.discard(service)
        return ()


def dashboard_graph(*, host: str = '127.0.0.1', port: int = 8765,
                    duration: float | None = None, recent_window_seconds: float = 1800,
                    max_recent_contexts: int = 1000) -> GraphDefinition:
    """Return a graph for Engine.submit(..., authority=Controller()).

    Host/port are declared ConfigFields. Non-loopback hosting supplies no
    authentication. Duration bounds the service loop, not engine lifetime.
    For stored history, explicitly submit with Controller(history=reader).
    This graph never opens, writes, flushes or closes its historical source.
    The listening URL is recorded under ``dashboard_url`` on the controller run.
    """
    if not isinstance(host, str) or not host.strip():
        raise ValueError('host must be a nonempty bind address')
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError('port must be an integer from 0 to 65535')
    if duration is not None and (type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0):
        raise ValueError('duration must be positive and finite or None')
    if type(recent_window_seconds) not in (int,float) or not math.isfinite(recent_window_seconds) or recent_window_seconds<=0:
        raise ValueError('recent_window_seconds must be positive and finite')
    if type(max_recent_contexts) is not int or not 1<=max_recent_contexts<=10000:
        raise ValueError('max_recent_contexts must be from 1 to 10000')
    operator = _Observe(duration=duration)
    graph = GraphDefinition(ArtifactFlow(operator))
    graph.bind_resources({operator.http: _HTTPResource(host=host, port=port, recent_window_seconds=recent_window_seconds, max_recent_contexts=max_recent_contexts)})
    graph.confirm()
    return graph


def prepare_dashboard(*, host: str = '127.0.0.1', port: int = 8765,
                      duration: float | None = None, recent_window_seconds: float = 1800,
                      max_recent_contexts: int = 1000) -> DashboardSubmission:
    """Prepare a dashboard for explicit submission with the caller's authority.

    Preparation is independent of browser location and starts no service. The
    supplied graph observes its executing runtime; host/port select the listener,
    not a remote engine. A remote-observation source would be an application-owned
    binding with its own authority, not an implication of this helper's name.

    All options follow dashboard_graph and its lifecycle-managed ConfigFields.
    No artifacts/config overrides are required; None preserves submit defaults,
    including one context iteration and the normal record limits. Duration=None
    serves until the controller is stopped; port=0 requests an available port.
    """
    return DashboardSubmission(dashboard_graph(
        host=host, port=port, duration=duration,
        recent_window_seconds=recent_window_seconds,
        max_recent_contexts=max_recent_contexts,
    ))
