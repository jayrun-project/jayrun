# Describe and repeat an execution

Use `self.execution` inside an operator's `execute()` or a resource's `setup()` to attach diagnostics to that invocation. The Engine's recording mode determines which diagnostics appear in the step report. Use `self.context.record()` when the application needs named values through `run.records(key)`.

## Logs, metrics and timers

This fragment belongs inside `execute()`, where `self.source` is a declared input:

```python
self.execution.log("starting calculation")
self.execution.start_timer("calculation")
try:
    result = sum(self.source.value)
finally:
    self.execution.stop_timer("calculation")
self.execution.metric("total", float(result))
return result
```

The default `STANDARD` mode records the log and metric. Choose `DIAGNOSTIC` to also record the elapsed duration of `calculation`. The `finally` block stops the timer even when the calculation raises. The [recording mode table](../evidence/reports.md#recording-modes) shows what appears in each attempt.

Resource setup can use these same diagnostic methods while loading a model or opening a client. Resource teardown has no injected execution handle; clean up using its Data argument.

## Request another operator execution

`repeat()` asks Jayrun to invoke the current operator again after the current call returns. `number` is one-based within the current operator step session. Both are operator-only additions to the execution interface.

```{literalinclude} ../../_examples/repetition.py
:language: python
:pyobject: Increment
```

On execution 1, the operator requests a repeat and publishes its incremented value. If context policy allows it, execution 2 reads the refreshed feedback value and increments it again. The operator does not request another repeat on execution 2. A new graph iteration starts a new step session and numbering starts again.

The [complete repeat/iteration example](../runs/iteration.md) connects that feedback artifact and limits the graph to two iterations. An ordinary output with a different identity does not automatically become the repeated invocation's input. `ContextSettings.max_repeats` counts additional executions, so `1` allows two executions in a session.

Full signatures: [self.execution reference](../../interfaces/execution.md).
