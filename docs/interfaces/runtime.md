(runtime-interface)=
# Runtime Interface

`self.runtime` addresses the engine runtime shared by all registered contexts. Its storage API is generally available to running components, while cross-context inspection and lifecycle control require supervising capability.

## Runtime-scoped values

```python
self.runtime.store("service_generation", 4)
generation = self.runtime.get_value("service_generation")
```

Runtime storage supports information shared across contexts. Because it is wider than context scope and remains available for the runtime's lifetime, use it deliberately:

- prefer artifacts for graph data;
- prefer context storage for per-context progress;
- avoid retaining large context-specific objects at runtime scope.

Deleting the context that created a runtime record does not remove that record. Runtime storage therefore supports genuine cross-context state, but it can also retain referenced objects until shutdown.

:::{warning}
Do not use runtime storage as an unbounded result cache. Stored payloads remain reachable until runtime shutdown.
:::

## Supervising contexts

Cross-context capabilities are available only when the current context was submitted with {py:attr}`jayrun.settings.ContextSettings.supervising` enabled. This restriction lets ordinary operators use runtime records without granting them authority over unrelated work.

A supervisor can inspect context lifecycle, review finalized outcomes, share progress through runtime-scoped values, and request lifecycle changes. Capability is enforced by the runtime; an operator name or class hierarchy does not grant it.

## Context inspection

```python
snapshot = self.runtime.get(context_id)

all_ids = self.runtime.context_ids
active_ids = self.runtime.active_context_ids
paused_ids = self.runtime.paused_context_ids
```

`get(context_id)` returns a structurally immutable `ContextSnapshot`, or `None` if the identifier is unavailable. Depending on lifecycle state, the snapshot can expose state, revision, history, failure information, a finalized report, and retained artifact results.

A snapshot is a point-in-time observation, not a live context object. Call `get()` again to observe a later revision. It does not expose another context's context-scoped key-value store. Objects contained in artifact results are referenced rather than deep-copied, so their own mutability is unchanged.

The ID properties return tuples:

- `context_ids` contains all registered context IDs;
- `active_context_ids` contains contexts currently participating in runtime work;
- `paused_context_ids` contains paused contexts.

Inspection never exposes mutable registry or execution-context internals.

## Supervising lifecycle requests

```python
self.runtime.pause(context_id)
self.runtime.pause(context_id, duration_seconds=30)
self.runtime.resume(context_id)
self.runtime.stop(context_id)
self.runtime.abort(context_id)
```

The terminology matches `self.context`:

- `pause()` requests a paused state;
- `resume()` requests that a paused context continue;
- `stop()` stops iteration;
- `abort()` stops further dispatch and drains the context.

These methods enqueue coordinator commands. They do not block until the target reaches the requested state. Inspect a later snapshot when confirmation matters.

## Capability errors

Calling cross-context inspection or control from a context without {py:attr}`jayrun.settings.ContextSettings.supervising` enabled raises `RuntimeCapabilityError`. This is a capability boundary, not a recoverable absence of the target context.

For a supervising context, `get()` returns `None` when a correctly typed context ID is not registered. Invalid argument types raise public input errors.

## Runtime values are not durable storage

Runtime records disappear with runtime cleanup. Use an operator to write important state to a database, object store, or filesystem when it must survive engine shutdown.

## API reference

The common storage methods are documented under {py:class}`ScopeInterface`.

```{py:exception} RuntimeCapabilityError
Raised when a context without supervising capability attempts cross-context inspection or control.
```

```{py:class} RuntimeInterface
Runtime-scoped storage and capability-controlled cross-context operations.
```

```{py:method} RuntimeInterface.get(context_id) -> ContextSnapshot | None
Return the current immutable snapshot for `context_id`, or `None` when it is not registered.

:param int context_id: Target context identifier.
:raises RuntimeCapabilityError: If the current context is not supervising.
:raises TypeError: If `context_id` is not exactly an integer.
```

```{py:attribute} RuntimeInterface.context_ids
:type: tuple[int, ...]

Identifiers of all registered contexts.

:raises RuntimeCapabilityError: If the current context is not supervising.
```

```{py:attribute} RuntimeInterface.active_context_ids
:type: tuple[int, ...]

Identifiers of registered contexts currently participating in runtime work.

:raises RuntimeCapabilityError: If the current context is not supervising.
```

```{py:attribute} RuntimeInterface.paused_context_ids
:type: tuple[int, ...]

Identifiers of paused contexts.

:raises RuntimeCapabilityError: If the current context is not supervising.
```

```{py:method} RuntimeInterface.pause(context_id, duration_seconds=None) -> None
Request that another context pause.

:param int context_id: Target context identifier.
:param duration_seconds: Non-negative pause duration, or `None` for explicit resumption.
:type duration_seconds: int | float | None
:raises RuntimeCapabilityError: If the current context is not supervising.
:raises TypeError: If either argument has an invalid type; booleans are not valid durations.
:raises ValueError: If `duration_seconds` is negative.
```

```{py:method} RuntimeInterface.resume(context_id) -> None
Request that a paused context resume.

:param int context_id: Target context identifier.
:raises RuntimeCapabilityError: If the current context is not supervising.
:raises TypeError: If `context_id` is not exactly an integer.
```

```{py:method} RuntimeInterface.stop(context_id) -> None
Request that the target context end its current iteration and begin no later iteration.

:param int context_id: Target context identifier.
:raises RuntimeCapabilityError: If the current context is not supervising.
:raises TypeError: If `context_id` is not exactly an integer.
```

```{py:method} RuntimeInterface.abort(context_id) -> None
Request that no further work be dispatched for the target context and that it drain toward an aborted terminal state.

:param int context_id: Target context identifier.
:raises RuntimeCapabilityError: If the current context is not supervising.
:raises TypeError: If `context_id` is not exactly an integer.
```

:::{versionadded} 0.1.0
Runtime-scoped storage and supervising context operations were introduced.
:::

Next, see {doc}`Placement Interface <placement>`, which requests leases from runtime-managed capacity without creating another scope.

For an end-to-end control pattern, see {doc}`MNIST Inference and Supervised Training <../tutorials/mnist-inference-and-training>`.
