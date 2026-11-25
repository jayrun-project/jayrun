```{eval-rst}
.. meta::
   :description: Use ContextRun to wait for a Jayrun graph, pause or stop work, check its final state, and read retained artifact results and application records.
```

(use-contextrun)=
# Wait for and control a graph run with ContextRun

`Engine.submit()` and Controller submission return a `ContextRun`. The same handle supports observation/control while work is active and final evidence after it completes. Obtain it from an Engine or authorized runtime; do not construct it yourself.

## Waiting and outcomes

`run.wait(timeout=...)` and `await run.wait_async(timeout=...)` wait for finalization when no state is supplied. They return the run; they do not raise merely because computation ended in `FAILED` or `REJECTED`. Check `run.state` and `run.report.data.failure`.

Waiting for a non-terminal state, such as `ContextState.PAUSED`, also ends if the run terminates first. Inspect the state after waiting. Terminal states are not accepted as explicit wait targets: omit the target to wait for finalization. Timeout values are seconds; a timeout does not cancel the run. `engine.wait(tuple_of_runs, ...)` shares one timeout budget across that tuple. The runtime equivalents use the same waiting helpers.

## Control intent and committed state

| Request | Intended effect | Completion to observe |
| --- | --- | --- |
| `pause(duration_seconds=None)` | Request a pause of running work at a scheduling boundary, with optional timed resume | `PAUSED` if the request takes effect. A queued run ignores a pause request. |
| `resume()` | Resume paused work | Committed active state or finalization |
| `stop()` | Prevent another graph iteration and drain accepted work | Usually `FINISHED`, with `stop_requested` evidence |
| `abort()` | Prevent further dispatch and drain toward abortion | `ABORTED` after finalization |
| `transfer(target_engine_id)` | Assign ordinary work to an engine incarnation at an eligible boundary | A local assignment from `ROUTING` can admit the run without changing owner. A change of owner advances the generation. |

A request returning is not proof its effect has committed. Stop also lets paused work drain; it is not a synonym for abort. Current stop behavior does not produce a special success outcome separate from `FINISHED`. Compatibility enum members are not a guide to current transition semantics.

## Results and retention

Read `run.artifact(reference)` after finalization. An early read raises `ContextNotTerminatedError`. A rejected submission can have a finalized report but no artifact account, in which case the lookup raises `KeyError`. When available, the `ArtifactResult` contains the retained value and lifecycle evidence. A `None` value can mean the route was absent or the payload was released. The [recording mode](../evidence/reports.md#recording-modes) determines how much artifact history you can inspect.

`run.records(key)` returns retained committed records, not all records ever written. `run.report.data` is the structured report; `run.report` also offers presentation. `snapshot()` captures portable context evidence, not a transport protocol. Release application references when you no longer need retained results.

Reference: [ContextRun, states and results](../../reference/context-run.md). Runtime-issued handles also obey [authority lifetime](../runtime/capabilities.md).
