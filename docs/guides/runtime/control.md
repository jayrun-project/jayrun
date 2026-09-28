# Observe and control other runs

Submit a supervising graph with `authority=Supervisor(work_graph)` to restrict it to that graph, or use `Supervisor()` for unrestricted live supervision. If the Engine has a registry, register the relevant graphs first. This authority does not grant Controller-only submission or history access.

Inside an async operator, with the granted scope:

```python
visible = self.runtime.unfinished_contexts
await self.runtime.wait_async(visible, timeout=10)
```

The tuple is a snapshot of visible handles, not a subscription to future submissions. `active_contexts` includes active/draining work; `paused_contexts` selects paused runs. The caller's own context is excluded. Control individual runs using the canonical [ContextRun API](../runs/context-run.md): pause, resume, Stop, abort or transfer. State changes are committed facts; request return is only acceptance.

## Event-driven supervision

```python
async for event in self.runtime.events:
    # Inspect the public event, then act on an authorized run if appropriate.
    self.execution.log(type(event).__name__)
```

This is a fragment for an authority-bearing async component. Repeated `events` access returns the same bounded queue. Both sync and async iteration destructively consume it; two readers compete rather than receive independent copies. Overflow raises `ObserverOverflowError`. On normal closure, queued events can drain before iteration ends. Do not assume a new access resets an overflowed queue or replays missed work.

## Pressure

`pressure` samples the current local, authority-scoped view. `pressures` includes that local sample and received remote pressure samples. Remote samples arrive only through application transport and authorized `apply`; their presence is not a heartbeat service or proof that a worker is currently healthy. Applying a pressure snapshot requires unrestricted supervision or Controller authority.

For terminal outcomes beyond live lists, use [Controller terminal history](history.md). A plain Supervisor cannot substitute an unrestricted live scope for that grant.
