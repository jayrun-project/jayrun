(execution-interface)=
# Execution Interface

`self.execution` describes the current operator or resource step session within one graph iteration.

## Logs, metrics, and timers

```python
self.execution.log("starting validation")
self.execution.metric("accuracy", 0.94)

self.execution.start_timer("validation")
score = validate(model)
self.execution.stop_timer("validation")
```

These calls add structured records to the execution report when their categories are enabled. They do not configure Python logging, persist data externally, or enforce deadlines.

Stopping an unknown timer is harmless. Disabling a recording category changes only what appears in reports; component code does not need conditional guards.

## Execution number

Operators expose a one-based repetition number:

```python
number = self.execution.number
```

The first execution is `1`. An accepted repetition increments the number. A retry starts another attempt of the same execution and does not increment it.

## Repetition

An operator may request another execution of itself:

```python
def execute(self):
    result = refine(self.input.value)
    if not converged(result):
        self.execution.repeat()
    return result
```

`repeat()` records a request; it does not recurse. Jayrun evaluates the request after `execute()` returns. `ContextSettings.max_repeats` remains authoritative.

Repetition belongs to one operator session. Whole-graph iteration is a context setting and is controlled with `ContextRun.stop()` or `self.context.stop()`.

## API summary

```{py:method} ExecutionInterface.log(message) -> None
Record a user log message for the current execution.
```

```{py:method} ExecutionInterface.metric(name, value) -> None
Record a numeric metric for the current execution.
```

```{py:method} ExecutionInterface.start_timer(name) -> None
Start or restart a named wall-clock timer.
```

```{py:method} ExecutionInterface.stop_timer(name) -> None
Stop a named timer and record its elapsed duration.
```

```{py:attribute} OperatorExecutionInterface.number
:type: int

One-based execution number within the current operator session.
```

```{py:method} OperatorExecutionInterface.repeat() -> None
Request another execution after the current invocation returns.
```

See {doc}`Observability and Inspection <../observability/observability-and-inspection>` for terminal reports. Continue with {doc}`Context Interface <context>` for values and lifecycle decisions that span executions.
