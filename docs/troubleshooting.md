(troubleshooting)=
# Troubleshooting

This page maps common symptoms to the first state, report, or declaration to inspect. Enable `RuntimeMode.DEBUG` when complete attempt, timer, failure, and artifact histories are required.

## A context remains queued

Inspect the run and runtime capacity:

```python
print(run.state)
```

A `QUEUED` context has validated but has not been admitted. Common causes include executor pressure, declared CPU memory pressure, active contexts with stronger admission priority, and unresolved runtime capacity.

Check `EngineSettings.max_workers`, `max_tasks`, CPU `RuntimeDevice.memory_limit_gb`, and the workload's resource and placement requirements. Executor limits are runtime-wide, not per context.

## A context remains in placement waiting

`PLACEMENT_WAITING` means at least one execution requested capacity that is temporarily unavailable. Other independent routes may still run.

Verify:

- the requested `Device` and `Backend` are declared in `EngineSettings.runtime_devices`;
- `device_id`, exclusivity, group size, and memory requirements are feasible;
- placement requests are deterministic across invocation restarts;
- idle placement-backed resources can be evicted when capacity is needed.

An impossible request fails the execution. A temporarily unavailable request waits for reconciliation; user code should not catch internal placement-control exceptions or poll the allocator.

See {doc}`Placement and Capacity <runtime/placement-and-capacity>`.

## An artifact result has `value is None`

The artifact declaration and lifecycle report can remain visible after its payload has been cleared. Typical causes are:

- the artifact is intermediate and no longer required;
- `ArtifactPolicy(retain_all=False)` did not select that exit artifact;
- the context failed or was aborted;
- the value was never produced because its operator was skipped.

Inspect `ArtifactResult.report` and its final artifact state. Successful exit artifacts are retained by default.

See {ref}`artifact-retention` for selection and clearing rules.

## An execution reports the wrong number of outputs

Match the return value to the operator's connected-output contract:

- when no output is connected, return `None`;
- when one field is declared and connected, return one value;
- when several fields are declared and at least one is connected, return a tuple with one position per declared field;
- use `None` at unbound positions in a mixed output tuple.

For conditional routing, every route field is bound to an artifact and the operator returns `None` for each inactive route. That runtime `None` disables downstream work. It is different from an output field bound to `None`, which creates no graph route.

See {ref}`artifact-output-bindings`, {ref}`terminal-operators`, and {ref}`conditional-routing`.

## The engine entered `FAILED`

Inspect all three failure surfaces:

```python
print(engine.failure)
print(engine.secondary_failures)
print(engine.cleanup_failures)
```

Under `FailureMode.FAIL_FAST`, an exhausted context failure intentionally fails the engine. Under `CONTINUE`, an engine failure normally indicates runtime infrastructure, escaped `BaseException`, startup, invariant, or cleanup failure.

Create a new engine after shutdown; a failed engine cannot be restarted. Retain affected context runs and debug reports before discarding the process.

See {doc}`Failure and Reliability Model <reliability/failure-and-reliability>`.

## Shutdown takes longer than expected

Graceful shutdown waits for accepted work to drain. A finite `timeout` ends the graceful coordination interval and escalates to forced shutdown; it is not a deadline that can safely terminate arbitrary code.

Check for:

- blocking synchronous operators or resource setup;
- native calls that ignore cancellation;
- resource teardown waiting on external systems;
- application-owned background work that retained invocation-bound interfaces;
- paused contexts, which Jayrun resumes during graceful shutdown so they can drain.

Use bounded library calls and cooperative cancellation. Use `shutdown(forced=True)` when remaining work should be abandoned, while retaining the same interruption limitations.

## CUDA or Torch uses the wrong device

A Jayrun placement reserves capacity but does not move application data. Use `placement.device_id` with the device library and return placement-bearing {py:class}`jayrun.Data`:

```python
placement = self.placement.cuda(memory_gb=2)
device = f"cuda:{placement.device_id}"
tensor = tensor.to(device)
return Data(value=tensor, placement=placement)
```

Confirm that the runtime declaration matches physical device IDs visible to the process. Container remapping and `CUDA_VISIBLE_DEVICES` can change that mapping.

For a placement group, use every member deliberately; Jayrun does not shard tensors or construct Torch distributed process groups automatically.

## A supervisor cannot see a target context

Pass the exact target graph object when submitting the supervisor:

```python
supervisor = engine.submit(
    supervisor_artifacts,
    supervisor_configs,
    supervises=(training_graph,),
)
```

Inside the supervisor, `self.runtime.contexts` contains only live contexts whose `run.graph` is one of those exact objects. An equivalent graph built as a separate Python object is intentionally a different scope. Targets that have already finalized are no longer in the live registry.

The supervisor cannot submit contexts. Targets must be originated by application code through `Engine.submit()`.

See {doc}`MNIST Inference and Supervised Training <tutorials/mnist-inference-and-training>` for a complete supervision workflow.

## A normal context failure was not raised by `wait()`

This is expected. `wait()` and `wait_async()` expose normal context failures through the finalized run:

```python
run.wait()
if run.report.failure is not None:
    raise RuntimeError("context failed") from run.report.failure
```

Response-deadline expiration is different: `wait(..., timeout=...)` raises `TimeoutError`, while the context continues running.

## Results accumulate in memory

Successful exit artifacts are retained by default in each completed `ContextRun`. Terminal contexts are released from the engine registry automatically.

Release application references after consuming or persisting their results:

```python
del run
```

For fire-and-forget submissions, use `ArtifactPolicy(retain_all=False)` and avoid collecting completed runs indefinitely. Persist required results through an operator or consume them before dropping the run.

## Reporting a framework defect

Include:

- Jayrun and Python versions;
- operating system and device backend versions;
- engine and context settings;
- primary, secondary, and cleanup failures;
- affected context runs and debug reports;
- the smallest graph that reproduces the problem.

Remove credentials and sensitive artifact payloads before sharing diagnostics.
