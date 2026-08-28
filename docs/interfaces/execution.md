(execution-interface)=
# Execution Interface

`self.execution` is the narrowest scope handle. It belongs to the current step session within one context iteration. That session may contain retry attempts and, for an operator, repeated executions.

## Execution-scoped values

Use execution storage for data local to one step session that should not become context or runtime state:

```python
def execute(self) -> object:
    self.execution.store("input_count", len(self.samples.value))
    count = self.execution.get_value("input_count")
    return process(self.samples.value, count=count)
```

The same execution interface remains attached while that session retries or repeats, so its stored values remain visible across those attempts and repetitions. A new session in another graph iteration does not share that storage.

If another step or iteration must read the value, store it on `self.context` instead. Stored values do not participate in artifact flow and cannot satisfy graph dependencies.

## Logs

```python
self.execution.log("starting transformation")
```

Logs are structured user records attached to the current execution report. They are not Python logging configuration and do not automatically persist outside the engine.

## Metrics

```python
self.execution.metric("accuracy", 0.94)
self.execution.metric("sample_count", 128)
```

Metric values must be integers or floating-point numbers. Use metrics for measurements that should appear in execution reports. A supervisor can inspect those reports after they become available in a finalized context snapshot; use runtime-scoped values when live cross-context progress must be visible.

## Timers

```python
self.execution.start_timer("transform")
result = transform(self.input_data.value)
self.execution.stop_timer("transform")
```

Timers record elapsed process time for a named region. Stopping a timer that was not started is harmless. Timers profile work; they do not enforce deadlines or cancel execution.

Logs, metrics, and timers are controlled by engine recording settings. A disabled category accepts calls without adding corresponding records to the report.

:::{note}
Disabling a diagnostic category changes recording only. Calls remain valid and do not need conditional guards in component code.
:::

## Execution number

Operators expose a one-based execution number:

```python
number = self.execution.number
```

The first execution is `1`. A requested repetition advances the number. A retry is another attempt of the current execution and does not represent a new repetition number.

Resource setup receives execution storage and diagnostic methods but does not expose `number` as a public resource capability.

## Repetition

An operator may request another execution of itself:

```python
def execute(self) -> object:
    result = refine(self.input_data.value)

    if not converged(result):
        self.execution.repeat()

    return result
```

`repeat()` records a request; it does not call `execute()` recursively. After the method returns, the engine evaluates the request, graph state, and configured repeat limit before scheduling another execution.

Repetition is available to operators, not resource setup or teardown. An integer {py:attr}`jayrun.settings.ContextSettings.max_repeats` bounds additional executions; `None` permits unbounded repetition.

## Records, retries, and repetitions

The execution report separates attempts and repeated execution numbers. When retry policy schedules another attempt, Jayrun closes the failed attempt record and begins a new one. Repetition increments `self.execution.number` and begins another execution record.

The scoped key-value store is separate from those diagnostic record boundaries and remains available for the lifetime of the step session. It can coordinate retry or repetition logic, but it is not a durable checkpoint.

Use artifacts for graph data, context storage for information that must survive across executions, and external persistence for durable recovery.

## API reference

The common storage methods are documented under {py:class}`ScopeInterface`.

```{py:class} ExecutionInterface
Execution-local storage and diagnostic recording for one step session.
```

```{py:method} ExecutionInterface.log(message) -> None
Record a user log message when log recording is enabled.

:param str message: Message stored in the current execution attempt.
```

```{py:method} ExecutionInterface.metric(name, value) -> None
Record a numeric metric when metric recording is enabled.

:param str name: Metric name.
:param value: Numeric metric value.
:type value: int | float
```

```{py:method} ExecutionInterface.start_timer(name) -> None
Start or restart the named timer when timer recording is enabled.

:param str name: Timer name.
```

```{py:method} ExecutionInterface.stop_timer(name) -> None
Stop the named timer and record its elapsed time. If the timer is unknown or timer recording is disabled, do nothing.

:param str name: Timer name.
```

```{py:class} OperatorExecutionInterface
Execution interface injected into an operator's `execute()` method.
```

```{py:attribute} OperatorExecutionInterface.number
:type: int

One-based execution number within the current step session. Retries do not increment it; accepted repetitions do.
```

```{py:method} OperatorExecutionInterface.repeat() -> None
Request another execution of the current operator after the method returns.

The context's repeat limit remains authoritative. Calling this method does not recurse and does not guarantee that another execution will be admitted.
```

:::{versionadded} 0.1.0
Execution diagnostics, execution numbering, and operator repetition were introduced.
:::

See {doc}`Observability and Inspection <../observability/observability-and-inspection>` for the finalized report and diagnostic-record model.

Next, see {doc}`Context Interface <context>` for state shared across executions in one graph submission.
