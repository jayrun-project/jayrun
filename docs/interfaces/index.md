# Injected interfaces

Jayrun provides these handles during BaseOperator.execute() and BaseResource.setup(). Resource teardown has a separate cleanup object. The [component-interface guide](../guides/components/index.md) explains the lifecycle and demonstrates their use. Use them through `self`; do not construct their implementation classes or retain them as global capabilities.

| Handle | Responsibility |
| --- | --- |
| `self.execution` | Current invocation logs, metrics, timers; operator repetition |
| `self.context` | Current context control and structured records |
| `self.runtime` | Engine identity and authority-scoped cross-context operations |
| `self.placement` | Capacity admission before application allocation |

```{toctree}
:maxdepth: 1

execution
context
runtime
placement
```

See [runtime capabilities](../guides/runtime/capabilities.md) for per-member grants and [Engine/runtime correspondence](../guides/runtime/correspondence.md) for related application APIs.
