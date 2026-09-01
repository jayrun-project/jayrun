(context-interface)=
# Context Interface

`self.context` addresses the graph submission that owns the current execution. It exposes context identity, stored values, and self-lifecycle requests.

## Context identity

```python
context_id = self.context.id
```

This ID matches the corresponding `ContextRun.context_id` and is useful for external logs. Control APIs do not require user code to pass it back to Jayrun.

## Stored values

Context records are visible across operators, repetitions, and graph iterations in the same run:

```python
def execute(self):
    previous = self.context.get_value("best_score")
    score = evaluate(self.model.value)

    if previous is None or score > previous:
        self.context.store("best_score", score)

    return self.model.value
```

Available methods are:

| Method | Result |
| --- | --- |
| `store(key, value)` | Append a value and its provenance |
| `has_value(key)` | Whether at least one record exists |
| `get_value(key)` | Latest value, or `None` |
| `get_values(key)` | All values in recording order |
| `get_value_record(key)` | Latest `ValueRecord`, or `None` |
| `get_value_records(key)` | All records in recording order |

Stored values do not trigger operators or satisfy dependencies. Use an artifact when a value is part of declared graph data flow.

After finalization, the same records remain available through the caller's `ContextRun` methods.

## Pause

```python
self.context.pause()
self.context.pause(duration_seconds=30)
```

Without a duration, the pause is indefinite and another authorized `ContextRun` must call `resume()`. With a duration, Jayrun schedules automatic resumption.

Pause takes effect at a scheduling boundary. It is not a sleep, an `await`, or forced suspension of the current Python instruction.

## Abort

```python
self.context.abort()
```

Abort prevents further dispatch and drains accepted work toward `ABORTED`. The current invocation is not forcefully killed, so return promptly after requesting it.

## Stop iteration

```python
self.context.stop()
```

Stop means stop iteration. Accepted work drains, and no next graph iteration begins. Use abort when remaining work should be abandoned; use stop when an iterative graph has reached its orderly completion condition.

## API summary

```{py:attribute} ContextInterface.id
:type: int

Identifier of the currently executing context.
```

```{py:method} ContextInterface.store(key, value) -> None
Append a context-scoped value record.
```

```{py:method} ContextInterface.pause(duration_seconds=None) -> None
Request a pause at a scheduling boundary. `None` means indefinite.
```

```{py:method} ContextInterface.abort() -> None
Prevent further dispatch and drain toward an aborted terminal state.
```

```{py:method} ContextInterface.stop() -> None
Prevent another graph iteration after accepted work drains.
```

Lifecycle calls enqueue messages and return immediately. Use a `ContextRun` wait when another participant must observe the transition.

Continue with {doc}`Runtime Interface <runtime>` for graph-scoped supervision.
