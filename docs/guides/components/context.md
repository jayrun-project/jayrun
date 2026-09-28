# Record values and control the current context

Use `self.context` when the action concerns the run executing this operator or resource setup. For other runs, use an authorized [runtime interface](../runtime/index.md).

## Record a value for the application

Inside an operator, publish a small structured value:

```python
self.context.record("batch", {"count": 12, "loss": 0.25})
```

After that run finalizes, application code can read it:

```python
run.wait(timeout=10)
latest = run.records("batch")[-1]
print(latest.value["loss"])  # 0.25
```

The record carries the run, step, iteration and execution that produced it. The [guided workflow](../../start/first-graph.md) is a complete runnable record example. Inside the hook, `self.context.records("batch")` reads committed records, and `self.context.id` gives the current context ID.

A call to `record()` queues a detached value. Immediate reading inside the same invocation can still see the previous committed view. Use your local variable if you need the value you just calculated; use records to inspect committed results. [Record values and retention](../evidence/records.md) explains accepted types and limits.

## Stop after reaching a goal

For an iterative operator whose declared `state` input is also regenerated as an output:

```python
state = self.state.value
advance_one_block(state)  # Your application function.
if state.finished:
    self.context.stop()
return state
```

Stop lets the accepted graph iteration drain and prevents the next one. The rest of the current method still executes, so it can publish its final result. Configure unbounded or sufficiently many graph iterations through ContextSettings when using a computation-driven stopping condition.

## Pause for review or abort

`self.context.pause()` requests an indefinite pause at a scheduling boundary; application code or an authorized supervisor resumes it through a ContextRun. Supplying `duration_seconds` requests timed resume. The call does not suspend the current Python method halfway through its statements.

`self.context.abort()` prevents further dispatch and drains toward ABORTED. It does not undo statements already executed or forcibly stop the current native call. Choose Stop when accepted work should finish normally; choose abort when the remaining work should be abandoned.

The [document tutorial](../../tutorials/document-ingestion.md) demonstrates pause/review/resume. See [ContextRun lifecycle control](../runs/context-run.md) for the application side and [self.context reference](../../interfaces/context.md) for every member.
