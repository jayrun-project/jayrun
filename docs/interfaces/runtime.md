# self.runtime

Use self.runtime inside a running component. [Capability table](../guides/runtime/capabilities.md), [control guide](../guides/runtime/control.md), [Controller submission](../guides/runtime/controller.md) and [history](../guides/runtime/history.md) explain scope and lifetime. The application surface has its own [Engine reference](../reference/engine.md); see [correspondence](../guides/runtime/correspondence.md).

This is an injected handle, not an application constructor.

```{py:class} RuntimeInterface
```

```{py:attribute} RuntimeInterface.name

Human-readable name of this context's engine.
```

[Source: name](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/runtime.py)

```{py:attribute} RuntimeInterface.engine_id

Unique name and UUID of this engine incarnation.

Pass this value to a remote run's
`jayrun.context.ContextRun.transfer` method to reclaim it here.
```

[Source: engine_id](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/runtime.py)

```{py:attribute} RuntimeInterface.alive

Whether this context should continue serving its runtime.

A graceful engine shutdown first settles ordinary contexts, so this
remains true for controllers and supervisors during that drain. It
becomes false when their final shutdown stage begins. For ordinary
contexts it becomes false when stopping, aborting, failing, or
finishing begins. Forced shutdown makes it false immediately.

Use this property as the condition for cooperative polling or service
loops. Event-driven authority code can instead iterate over
`events`, whose queue closes at the same shutdown boundary.
```

[Source: alive](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/runtime.py)

```{py:method} RuntimeInterface.wait(runs, state=None, *, timeout=None)

Synchronously wait for one or more visible context runs.

The behavior and validation are identical to `Engine.wait()`.
```

[Source: wait](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/runtime.py)

```{py:method} RuntimeInterface.wait_async(runs, state=None, *, timeout=None)
:async:

Asynchronously wait for one or more visible context runs.

The behavior and validation are identical to
`Engine.wait_async()`.
```

[Source: wait_async](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/runtime.py)

```{py:attribute} RuntimeInterface.events

This authority context's single bounded destructive event queue.

Repeated access returns the same queue. Both `next` and
`anext` consume its oldest event. During graceful shutdown the
queue closes after ordinary work finalizes, allowing a normal `for` or
`async for` loop to drain and return. It also closes when the authority
context finalizes, and raises
`jayrun.context.ObserverOverflowError` after overflow.

:raises PermissionError: If this context has no supervising authority.
```

[Source: events](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/runtime.py)

```{py:attribute} RuntimeInterface.history

Borrow the history scope explicitly granted through Controller.

Ordinary/supervisor contexts are denied. Controller() without a history
grant returns None, even when its engine records to a Database. A granted
reader expires with this controller or its source database lifecycle.
Reads recheck authority before admission and before returning results.
```

[Source: history](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/runtime.py)

```{py:method} RuntimeInterface.terminal_history(*, after=None, limit=256)

Read bounded finalized summaries with current Controller authority.

This is not an event replay or a full-report store. A gap signals lost
summaries; an expired grant or another engine's cursor is rejected.
Supervisor-scoped cursors are deliberately unsupported, to avoid leaking
hidden activity through global sequence numbers.
```

[Source: terminal_history](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/runtime.py)

```{py:method} RuntimeInterface.apply(snapshot)

Apply one portable context snapshot through local authorization.

For a locally owned context, an embedded request is dispatched through
the normal coordinator. Committed state, records, reports, progress, and
artifacts synchronize the local view. A queued snapshot assigned to this
runtime's `engine_id` is admitted for execution. Duplicate,
obsolete-generation, and stale-revision snapshots have no effect.
During shutdown, committed updates for known contexts remain admissible
while new contexts and control-request snapshots are rejected.

:param snapshot: Immutable snapshot received through application-owned transport.

:raises TypeError: If `snapshot` has an unsupported type.
:raises PermissionError: If the target is outside this authority.
:raises RuntimeError: If the runtime cannot apply the snapshot.
```

[Source: apply](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/runtime.py)

```{py:method} RuntimeInterface.submit(graph_key, artifacts=None, configs=None, *, settings=None)

Submit ordinary registered-graph work from a controller.

Submission creates a new logical context from a `(key, version)` graph
identity plus graph-independent artifact and configuration contexts. It
follows the engine's routing mode and never accepts a snapshot; snapshots
belong to `apply`. Runtime submission cannot create a supervisor or
controller, so authority is intentionally absent from this API.

:param graph_key: Registered `(key, version)` graph identity.
:param artifacts: Optional entry-artifact builder context. Omit it for a graph without required entry artifacts.
:param configs: Optional configuration builder context. Omit it for a graph without required configuration fields.
:param settings: Optional context execution settings.

:returns: The newly submitted context run.

:raises PermissionError: If the caller is not a controller.
:raises RuntimeError: If no graph registry is configured or submission is unavailable.
```

[Source: submit](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/runtime.py)

```{py:method} RuntimeInterface.shutdown(forced=False)

Request engine shutdown from a controlling context.

The request is asynchronous because an executing controller cannot wait
for the runtime that is currently executing it to close. Graceful
shutdown settles ordinary work before stopping authority contexts;
`alive` then becomes false and `events` closes so both
polling and event-driven loops can return.

:param forced: Abort live work instead of stopping future iterations and draining accepted work.

:raises TypeError: If `forced` is not a bool.
:raises PermissionError: If the caller is not a controller.
```

[Source: shutdown](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/runtime.py)

```{py:attribute} RuntimeInterface.unfinished_contexts

Non-terminal runs whose graphs this context supervises.
```

[Source: unfinished_contexts](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/runtime.py)

```{py:attribute} RuntimeInterface.active_contexts

Visible runs in active or draining states.
```

[Source: active_contexts](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/runtime.py)

```{py:attribute} RuntimeInterface.paused_contexts

Visible contexts currently paused.
```

[Source: paused_contexts](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/runtime.py)

```{py:attribute} RuntimeInterface.pressure

Latest authority-scoped runtime pressure snapshot.

Context-state counts include only work owned by this engine and visible
to this authority. Sampling pressure does not emit an event or update
profiling history.
```

[Source: pressure](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/runtime.py)

```{py:attribute} RuntimeInterface.pressures

Local pressure plus received remote pressure samples. These samples are not automatic liveness detection.
```

[Source: pressures](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/runtime.py)

## Pressure snapshot authority

`apply` accepts both ContextSnapshot and PressureSnapshot. Context targets need scope authority; pressure application requires unrestricted supervision/Controller authority. Ordinary visible-run lists are empty, events/submission/shutdown/history operations deny access as described in the capability table.
