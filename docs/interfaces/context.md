(context-interface)=
# Context Interface

`self.context` addresses the graph submission that owns the current execution. It provides context identity, context-scoped storage, and lifecycle requests affecting that context.

## Context identity

```python
context_id = self.context.id
```

This is the integer identifier returned by `Engine.submit(...)`. It can associate application logs or externally persisted data with the correct run.

## Context-scoped values

Context storage is visible to later executions in the same context:

```python
def execute(self) -> object:
    previous = self.context.get_value("best_score")
    score = evaluate(self.model.value)

    if previous is None or score > previous:
        self.context.store("best_score", score)

    return score
```

Every `store()` appends a record. `get_value()` returns the latest value, while `get_values()` returns the recorded sequence.

Context storage suits progress, decisions, and coordination within one submitted run. It is not artifact flow: stored values do not trigger operators, satisfy dependencies, or become retained results.

Context-scoped stored values are available while the execution context is active and are released when the context finalizes. They are not copied into `ContextSnapshot`; use artifacts, execution reports, or external persistence for information required after finalization.

## Lifecycle requests

Lifecycle methods submit requests to the engine coordinator. They do not interrupt Python at the call site and do not wait until the transition is visible. After making a request, return from the component promptly and let the engine apply it at a controlled boundary.

### Pause

```python
self.context.pause()
self.context.pause(duration_seconds=30)
```

Without a duration, the context remains paused until a supervising context resumes it. With a non-negative duration, the engine schedules resumption after that interval.

Pause affects context scheduling; it is not equivalent to `await`, a thread sleep, or forceful suspension of the current instruction.

### Abort

```python
self.context.abort()
```

Abort requests that the engine stop dispatching further work and drain the context into an aborted terminal outcome. Use it when the remaining work should be abandoned intentionally rather than reported as an uncaught operator failure.

The current invocation is not forcibly killed. It should return promptly after requesting abort.

### Stop the current iteration

```python
self.context.stop()
```

In Jayrun, **stop means stop iteration**. It requests an orderly end to the current iteration and prevents another iteration from beginning. It does not mean “stop the context immediately.”

Use `stop()` when an iterative graph has reached its stopping condition. Use `abort()` when its remaining work should be abandoned.

## Choosing artifacts or context values

Use an artifact when the value is part of declared graph data flow. Use context storage when the value is observational or used for lifecycle decisions without defining a dependency.

For example, a produced model is an artifact; a “best validation score so far” used by a supervising decision may be a context value. If downstream operators require that score as input, declare it as an artifact instead.

## API reference

The common storage methods are documented under {py:class}`ScopeInterface`.

```{py:class} ContextInterface
Context identity, storage, and lifecycle requests for the graph submission that owns the current execution.
```

```{py:attribute} ContextInterface.id
:type: int

Identifier assigned by `Engine.submit()` to the current context.
```

```{py:method} ContextInterface.pause(duration_seconds=None) -> None
Request that the current context pause at a controlled scheduling boundary.

:param duration_seconds: Non-negative pause duration, or `None` to require explicit resumption by a supervisor.
:type duration_seconds: int | float | None
:raises TypeError: If `duration_seconds` is not an integer, float, or `None`; booleans are rejected.
:raises ValueError: If `duration_seconds` is negative.
```

```{py:method} ContextInterface.abort() -> None
Request that no further work be dispatched and that the current context drain toward an aborted terminal state.
```

```{py:method} ContextInterface.stop() -> None
Request an orderly end to the current iteration and prevent a later iteration from beginning.
```

:::{important}
Lifecycle methods enqueue requests. They neither interrupt the current Python instruction nor wait for the requested transition.
:::

:::{versionadded} 0.1.0
Context identity, scoped storage, and lifecycle requests were introduced.
:::

Next, see {doc}`Runtime Interface <runtime>` for information shared across contexts and supervising control.
