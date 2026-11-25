# self.execution

Use self.execution during execute/setup. log, metric and timers describe the current execution; repeat and number are operator-only. [Repetition guide](../guides/runs/iteration.md).

Read [how to use self.execution](../guides/components/execution.md) for hook availability and a worked explanation. This is an injected handle, not an application constructor.

```{py:class} ExecutionInterface
```

```{py:method} ExecutionInterface.log(message)

Record a text message for this execution in `STANDARD` or `DIAGNOSTIC` mode.
```

[Source: log](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/execution.py)

```{py:method} ExecutionInterface.metric(name, value)

Record a numeric metric for this execution in `STANDARD` or `DIAGNOSTIC` mode.
```

[Source: metric](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/execution.py)

```{py:method} ExecutionInterface.start_timer(name)

Start a named elapsed-time measurement in `DIAGNOSTIC` mode. Other recording modes omit named timers.
```

[Source: start_timer](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/execution.py)

```{py:method} ExecutionInterface.stop_timer(name)

Stop the named timer. In `DIAGNOSTIC` mode a matching start produces a `TimerRecord` in the current attempt.
```

[Source: stop_timer](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/execution.py)

```{py:method} ExecutionInterface.repeat()

Request another execution after the current invocation returns.

The context's `max_repeats` setting remains authoritative.
```

[Source: repeat](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/execution.py)

```{py:attribute} ExecutionInterface.number

One-based execution number within the current operator session.
```

[Source: number](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/execution.py)
