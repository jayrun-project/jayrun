(engine-and-context-lifecycle)=
# Engine and Context Lifecycle

An `Engine` owns execution capacity, the runtime event loop, shared resources, placement accounting, and live context coordination. Each submission returns one stable `ContextRun` for observation, waiting, control, and terminal results.

## Engine lifecycle

| State | Meaning |
| --- | --- |
| `CREATED` | Constructed but not started |
| `STARTING` | Runtime modules are initializing |
| `RUNNING` | Accepting submissions |
| `STOPPING` | Rejecting submissions and cleaning up |
| `STOPPED` | Shutdown completed |
| `FAILED` | A runtime-level failure occurred |

While running, `engine.activity` is either `IDLE` or `ACTIVE`. Activity does not change the engine lifecycle state.

## Starting the engine

For a synchronous application, let Jayrun own a background event loop:

```python
engine = Engine()
engine.start()
```

For an asynchronous application, adopt its running loop:

```python
engine.start(loop=asyncio.get_running_loop())
```

Jayrun never closes an application-owned loop.

The context-manager form is the simplest synchronous lifecycle:

```python
with Engine() as engine:
    run = engine.submit(artifacts, configs)
    run.wait()
```

## Submitting a context

```python
run = engine.submit(
    artifacts,
    configs,
    context_settings=context_settings,
)
```

`artifacts` must be an `ArtifactContext`, `configs` must be a `ConfigContext`, and both must belong to the same confirmed graph. Dictionaries are intentionally not accepted by `submit()`; context objects provide a stable boundary for validation, capture, and future serialization policies.

The engine captures sealed submission views. They are available as `run.artifact_context` and `run.config_context`. The caller may reuse or mutate its original context objects without altering the submitted run.

Submission validates the context and returns promptly. It does not wait for execution to finish.

## The stable `ContextRun`

`ContextRun` is one API across the whole lifecycle:

```python
run.context_id
run.graph
run.artifact_context
run.config_context
run.state
run.iteration_count
run.done
```

The object updates in place. When `done` becomes true, the run exposes:

```python
run.report
run.artifact(output_artifact)
run.get_value("progress")
```

The live registry releases terminal contexts automatically, but application-held runs retain their reports, stored values, and selected artifact results.

## Context states

| State | Meaning |
| --- | --- |
| `SUBMITTED` | Registered for validation |
| `VALIDATING` | Submission values and settings are being checked |
| `VALIDATED` | Accepted for scheduling |
| `REJECTED` | Submission validation failed |
| `QUEUED` | Waiting for scheduler admission |
| `RUNNING` | Dispatching or executing graph work |
| `PLACEMENT_WAITING` | Waiting for temporarily unavailable capacity |
| `PAUSED` | Held at a scheduling boundary |
| `ABORTING` | Draining after abort was requested |
| `FAILING` | Draining after execution failure |
| `FINISHED` | Completed normally |
| `STOPPED` | Completed after iteration stop was requested |
| `FAILED` | Completed with failure |
| `ABORTED` | Completed after abortion |

`REJECTED`, `FINISHED`, `STOPPED`, `FAILED`, and `ABORTED` are terminal. `ABORTING` and `FAILING` are draining states.

## Waiting synchronously

Wait for terminal finalization by omitting a state:

```python
run.wait(timeout=30)
```

Wait for an exact non-terminal decision point:

```python
run.wait(ContextState.PAUSED, timeout=30)
```

If the context terminates before reaching the requested non-terminal state, the wait also returns; inspect `run.state` before acting.

`engine.wait(run)` is a convenience equivalent. It also accepts a tuple and applies one timeout budget:

```python
engine.wait(tuple(runs), timeout=30)
```

Do not call synchronous waiting from a thread that is running an event loop. Use asynchronous waiting instead.

## Waiting asynchronously

A run is directly awaitable:

```python
await run
```

The explicit form supports state and timeout arguments:

```python
await run.wait_async(ContextState.PAUSED, timeout=30)
```

Wait for several runs concurrently through the engine or a supervisor runtime:

```python
await engine.wait_async(tuple(runs), timeout=30)
```

Waiting never re-raises an operator failure in the waiting task. Inspect `run.state` and `run.report.failure`.

## Lifecycle control

The same methods are available on application-held and supervisor-provided runs:

```python
run.pause()
run.pause(duration_seconds=30)
run.resume()
run.stop()
run.abort()
```

These methods enqueue coordinator messages and return immediately.

- `pause()` holds scheduling at a controlled boundary. `None` means indefinite.
- `resume()` continues a paused context.
- `stop()` prevents another graph iteration after accepted work drains.
- `abort()` prevents further dispatch and drains toward `ABORTED`.

Control on a terminal run is a no-op. A timed-out wait does not cancel or abort the context.

## Context-stored values

Operators publish progress or coordination values through `self.context`:

```python
self.context.store("accuracy", accuracy)
```

The run exposes the same record stream:

```python
run.has_value("accuracy")
run.get_value("accuracy")
run.get_values("accuracy")
run.get_value_record("accuracy")
run.get_value_records("accuracy")
```

Records remain available after finalization. They are observational state, not graph dependencies or durable persistence.

## Reports and artifact results

`run.report` and `run.artifact(...)` are intentionally unavailable before finalization and raise `ContextNotTerminatedError`.

After waiting:

```python
run.wait()

if run.state is ContextState.FINISHED:
    model_result = run.artifact(model)
else:
    raise RuntimeError("training did not finish") from run.report.failure
```

`ContextReport` contains terminal state, timestamps, lifecycle history, iteration count, execution reports, and failure information. `ArtifactResult` contains retained `Data`, placement, and artifact lifecycle records.

Artifacts can be addressed by declaration, inspected definition, or graph-local integer ID. Only results selected by `ArtifactPolicy` are retained.

## Inspecting live engine work

```python
engine.contexts
engine.active_contexts
```

Both properties return tuples of `ContextRun`s in submission order. `contexts` contains live non-terminal runs; `active_contexts` narrows that set to active or draining states. Terminal runs are no longer in the engine registry, though runs already held by callers remain valid.

## Supervising selected graphs

A supervisor is submitted like any graph:

```python
supervisor = engine.submit(
    supervisor_artifacts,
    supervisor_configs,
    supervises=(training_graph,),
)
```

Within that graph, `self.runtime.contexts` exposes only live contexts submitted from the exact graph objects in `supervises`. The returned objects use the same wait, record, and control methods shown above.

Supervisors do not submit new contexts. They return decisions as artifacts; application code can then originate replacement submissions.

## Graceful shutdown

```python
engine.shutdown(timeout=30)
```

Graceful shutdown rejects new submissions, requests stop for future iterations, resumes paused contexts, drains accepted work, finalizes runs, tears down shared resources, releases placement capacity, and closes runtime services.

When the engine shares an application event loop:

```python
await engine.shutdown_async(timeout=30)
```

## Forced shutdown

```python
engine.shutdown(forced=True, timeout=30)
```

Forced shutdown requests abort for every live context, then waits for draining and cleanup. Python code already executing is not killed at an arbitrary instruction, so user components should avoid unbounded blocking operations and respond promptly to their normal return boundaries.

Shutdown is idempotent and coordinated across concurrent callers. A timeout reports that cleanup has not yet completed; it does not silently abandon runtime-owned resources.

See {doc}`Failure and Reliability Model <../reliability/failure-and-reliability>` for failure escalation and {doc}`Observability and Inspection <../observability/observability-and-inspection>` for report details.
