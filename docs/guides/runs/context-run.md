# Use ContextRun

`Engine.submit()` and Controller submission return a `ContextRun`. The same handle supports observation/control while work is active and final evidence after it completes. Obtain it from an Engine or authorized runtime; do not construct it yourself.

## Waiting and outcomes

`run.wait(timeout=...)` and `await run.wait_async(timeout=...)` wait for finalization when no state is supplied. They return the run; they do not raise merely because computation ended in `FAILED` or `REJECTED`. Check `run.state` and `run.report.data.failure`.

Waiting for a non-terminal state, such as `ContextState.PAUSED`, also ends if the run terminates first. Inspect the state after waiting. Terminal states are not accepted as explicit wait targets: omit the target to wait for finalization. Timeout values are seconds; a timeout does not cancel the run. `engine.wait(tuple_of_runs, ...)` shares one timeout budget across that tuple. The runtime equivalents use the same waiting helpers.

## Control intent and committed state

| Request | Intended effect | Completion to observe |
| --- | --- | --- |
| `pause(duration_seconds=None)` | Pause at a scheduling boundary; optional timed resume | `PAUSED`, unless already terminal |
| `resume()` | Resume paused work | Committed active state or finalization |
| `stop()` | Prevent another graph iteration and drain accepted work | Usually `FINISHED`, with `stop_requested` evidence |
| `abort()` | Prevent further dispatch and drain toward abortion | `ABORTED` after finalization |
| `transfer(engine_id)` | Request execution ownership at a safe boundary | Updated committed owner/generation |

A request returning is not proof its effect has committed. Stop also lets paused work drain; it is not a synonym for abort. Current stop behavior does not produce a special success outcome separate from `FINISHED`. Compatibility enum members are not a guide to current transition semantics.

## Results and retention

Read `run.artifact(reference)` after finalization; a non-finalized run raises `ContextNotTerminatedError`. The returned `ArtifactResult` separates retained value from artifact history. A `None` value can mean absent, cleared or not retained; inspect evidence and retention policy rather than assuming computation failure.

`run.records(key)` returns retained committed records, not all records ever written. `run.report.data` is the structured report; `run.report` also offers presentation. `snapshot()` captures portable context evidence, not a transport protocol. Release application references when you no longer need retained results.

Reference: [ContextRun, states and results](../../reference/context-run.md). Runtime-issued handles also obey [authority lifetime](../runtime/capabilities.md).
