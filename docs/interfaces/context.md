# self.context

Use self.context for the currently executing context. record means queued acceptance, records reads retained committed values; neither is durable storage. [Recording guide](../guides/evidence/records.md).

Read [how to use self.context](../guides/components/context.md) for hook availability and a worked explanation. This is an injected handle, not an application constructor.

```{py:class} ContextInterface
```

```{py:method} ContextInterface.record(key, value)

Validate and detach a value before queueing it for context commitment.

Return means queued acceptance, not committed visibility. An immediate
records() call may still see the preceding snapshot. Capacity violations
raise before queueing; shutdown or ownership transfer may discard pending
requests. Recording does not acknowledge an application action.
```

[Source: record](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/base.py)

```{py:method} ContextInterface.records(key)

Return context-scoped records for `key` in recording order.
```

[Source: records](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/context.py)

```{py:method} ContextInterface.abort()

Prevent further dispatch and drain this context toward `ABORTED`.
```

[Source: abort](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/context.py)

```{py:method} ContextInterface.stop()

Stop iteration after accepted work drains, preventing a next iteration.
```

[Source: stop](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/context.py)

```{py:method} ContextInterface.pause(duration_seconds=None)

Request a pause at a controlled scheduling boundary.

:param duration_seconds: Non-negative automatic-resume delay, or `None` to require a supervising context to resume this context.
```

[Source: pause](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/context.py)

```{py:attribute} ContextInterface.id

ID of the currently executing context.
```

[Source: id](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/context.py)
