# Engine and runtime correspondence

Engine is the application's lifecycle owner. `self.runtime` is a capability granted to a running component. Shared vocabulary makes the two surfaces familiar; scope and ownership still differ. Their references remain separate: [Engine](../../reference/engine.md) and [self.runtime](../../interfaces/runtime.md).

| Purpose | Application Engine | Injected self.runtime | Relationship |
| --- | --- | --- | --- |
| Identity | `name`, `engine_id` | `name`, `engine_id` | Same engine incarnation vocabulary |
| Unfinished/active work | `unfinished_contexts`, `active_contexts` | Same names | Runtime filters authority and excludes caller |
| Waiting | `wait`, `wait_async` | `wait`, `wait_async` | Shared wait helpers and timeout rules |
| Local pressure | `pressure` | `pressure` | Runtime scope filters counts |
| Delivered evidence | `apply(snapshot)` | `apply(snapshot)` | Context/pressure snapshots; runtime checks authority |
| Submission | GraphDefinition or registered identity; may grant authority | Registered identity only; Controller; no authority parameter | Similar operation, narrower capability |
| Events | `observer(capacity=...)` creates an observer | `events` returns one fixed queue | Different acquisition/ownership |
| Terminal summaries | `terminal_history(...)` | `terminal_history(...)` | Same paging vocabulary; Controller only inside a component |
| Durable history | `database` lifecycle owner | `history` borrowed reader | Explicit Controller reader grant |
| Shutdown | `shutdown`, `shutdown_async`, timeout | `shutdown(forced=False)` | Owner waits; Controller requests only |

## Waiting in application code

With an Engine and submitted runs:

```python
await engine.wait_async(runs, timeout=10)
```

## Waiting in a supervising component

With an authority-bearing async operator:

```python
visible = self.runtime.unfinished_contexts
await self.runtime.wait_async(visible, timeout=10)
```

Both wait for finalization by default, share a tuple's timeout budget and return the supplied handle(s). Neither verifies a successful outcome. Once a run is obtained, its lifecycle and result operations are documented once on [ContextRun](../runs/context-run.md).

## Surfaces without a counterpart

Engine owns construction, `start`, context-manager shutdown and failure diagnostics. Runtime exposes `alive`, `paused_contexts` and `pressures`; do not invent Engine counterparts. `pressures` includes received remote samples, not just plural local counts. Engine `observer()` is not a runtime factory, and a Controller has no `shutdown_async()` method.

See [capability table](capabilities.md) for ordinary contexts, scoped/unrestricted Supervisors and Controllers, and [history](history.md) for borrowed-reader lifetime.
