(engine-and-context-lifecycle)=
# Engine and Context Lifecycle

The {py:class}`jayrun.Engine` owns one Jayrun runtime. Applications start it, submit graph contexts, inspect immutable snapshots, retain or delete completed results, and shut the runtime down. This chapter describes that lifecycle from the application boundary.

The engine lifecycle and a context lifecycle are related but independent. One running engine can host many contexts, and each context progresses to its own terminal state before remaining registered for inspection.

## Engine states

{py:class}`EngineState` describes the engine lifecycle:

| State | Meaning |
|---|---|
| `CREATED` | Constructed but not started |
| `STARTING` | Runtime modules and the coordinator are starting |
| `RUNNING` | Accepting submissions and coordinating work |
| `STOPPING` | The shutdown boundary has been established |
| `STOPPED` | Normal shutdown and cleanup have completed |
| `FAILED` | A fatal runtime or cleanup failure was recorded |

`STARTED` and `IDLE` are compatibility aliases for `RUNNING`; they are not separate lifecycle states. Current work activity is exposed through {py:class}`RuntimeActivity` as `IDLE` or `ACTIVE`.

```python
engine = Engine()
assert engine.state.value == "created"

engine.start()
assert engine.state.value == "running"
```

An engine can start only from `CREATED`. Calling `start()` again while already running is harmless. A stopped or failed engine cannot be restarted; create a new `Engine` instead.

## Starting the engine

The ordinary form creates an engine-owned event loop in a background thread:

```python
from jayrun import Engine


engine = Engine()
engine.start()
```

An asynchronous application may supply an event loop that is already running:

```python
import asyncio


async def main() -> None:
    engine = Engine()
    engine.start(loop=asyncio.get_running_loop())
    try:
        ...
    finally:
        await engine.shutdown_async()
```

Jayrun does not own a supplied loop and does not close it. Use asynchronous waiting and shutdown from that loop; a synchronous wait or shutdown cannot block the runtime loop thread.

:::{important}
`start(loop=...)` requires an event loop that is already running and not closed. Passing a newly created but inactive loop raises `RuntimeError`.

For a complete application example, see {doc}`Denoise Images with FastAPI <../tutorials/denoise-images-with-fastapi>`.
:::

If startup fails, Jayrun records the failure, runs the same cleanup pipeline used by shutdown, transitions to `FAILED`, and raises the failure from `start()`.

## Submitting contexts

One call to {py:meth}`jayrun.Engine.submit` creates one context:

```python
context_id = engine.submit(
    artifacts,
    configs,
    context_settings=context_settings,
)
```

`artifacts` selects the graph and supplies its entry values. `configs` must belong to the same graph; omit it when the graph has no required configuration. `context_settings` overrides engine defaults for this submission only.

Submission validates public argument types before entering the runtime. The context then receives an integer ID and validates its graph, configuration, artifact values, and effective settings. `submit()` returns the ID without waiting for execution.

A submission can be registered yet immediately become `REJECTED` when context validation fails. Inspect its snapshot to obtain the failure.

:::{note}
Context IDs are local to one engine runtime. Do not use an ID from one engine with another engine.
:::

## Context states

{py:class}`ContextState` exposes the complete context lifecycle:

| State | Category | Meaning |
|---|---|---|
| `SUBMITTED` | Registration | Created in the runtime registry |
| `VALIDATING` | Registration | Submission data and graph are being checked |
| `VALIDATED` | Admission | Validation succeeded |
| `REJECTED` | Terminal | Validation failed before execution |
| `QUEUED` | Admission | Waiting for scheduler admission |
| `RUNNING` | Active | Work may be dispatched |
| `PLACEMENT_WAITING` | Active | At least one step is waiting for capacity |
| `PAUSED` | Active | New dispatch is temporarily suspended |
| `ABORTING` | Draining | Further dispatch is prevented while accepted work drains |
| `FAILING` | Draining | A failure is being finalized |
| `FINISHED` | Terminal | The graph completed normally |
| `STOPPED` | Terminal | The current iteration drained after a stop request |
| `FAILED` | Terminal | Execution failed |
| `ABORTED` | Terminal | Abort completed |

`ContextState.is_terminal`, `is_draining`, and `is_active` group states for inspection. A terminal state describes the outcome; `snapshot.finalized` confirms that final reports and retained artifact results have also been attached.

:::{important}
In Jayrun, **stop** means stop iteration. It does not mean “terminate the context immediately.” **Abort** prevents further dispatch and drains accepted work before the context becomes `ABORTED`.
:::

`PLACEMENT_WAITING` does not imply that every route in the context is blocked. Independent ready routes may continue while one step waits for capacity.

## Session and execution lifecycle

Within each context iteration, Jayrun creates a logical execution session for every runnable operator or resource step. A session is not a worker thread or coroutine; the executor manager dispatches its individual attempts to the appropriate execution capacity.

A session progresses conceptually through:

1. **Idle** — ready to be dispatched.
2. **Dispatched** — one synchronous or asynchronous attempt is running.
3. **Placement waiting** — a placement request is temporarily unavailable.
4. **Finished, failed, or cancelled** — the current run has an outcome.
5. **Finalized** — its report is attached to the context outcome.

A retry reuses the session, clears its failure, and starts another attempt. An operator repetition also reuses the session, resets attempt counting, and preserves the session-scoped execution interface storage. A new context iteration creates a new set of step sessions.

Placement reconciliation may restart the invocation from the beginning of its deterministic placement-request sequence. Abort cancels undispatched sessions and requests cancellation of dispatched work before finalization.

See {doc}`Operators and Executions <../components/operators-and-executions>` for retry and repetition semantics, and {doc}`Execution Interface <../interfaces/execution>` for session-scoped records and values.

## Waiting synchronously

With no requested state, {py:meth}`jayrun.Engine.wait` waits for terminal finalization:

```python
snapshot = engine.wait(context_id)
```

Wait for a particular non-terminal state by passing `state`:

```python
from jayrun.context import ContextState


snapshot = engine.wait(
    context_id,
    state=ContextState.RUNNING,
    timeout=10,
)
```

If the context becomes terminal before the requested state is observed, `wait()` returns its finalized terminal snapshot. State waiting is therefore an observation boundary, not a guarantee that the context will enter that state.

`wait()` returns `None` when the ID is unavailable, including after that context has been deleted or pruned. A normal context failure is returned in `snapshot.failure`; it is not raised in the waiting thread.

:::{warning}
Do not call synchronous `wait()` from the event loop used by Jayrun. Use {py:meth}`jayrun.Engine.wait_async` so the loop remains able to coordinate the context.
:::

## Waiting asynchronously

{py:meth}`jayrun.Engine.wait_async` provides the same condition and result semantics without blocking the caller's event loop:

```python
snapshot = await engine.wait_async(
    context_id,
    timeout=30,
)
```

Several contexts can be awaited concurrently:

```python
snapshots = await asyncio.gather(
    *(engine.wait_async(context_id) for context_id in context_ids)
)
```

Cancellation of the caller's wait removes that waiter. It does not cancel the Jayrun context.

## Response deadlines

The `timeout` on `wait()` and `wait_async()` is a response deadline for that one call. It must be finite and non-negative. If the condition is not reached, the call raises `TimeoutError` and unregisters its waiter.

```python
try:
    snapshot = engine.wait(context_id, timeout=2)
except TimeoutError:
    snapshot = engine.get(context_id)
```

The context continues running after a wait timeout. The caller may inspect it, wait again, or arrange lifecycle control through an operational interface.

Shutdown uses `timeout` differently: it is the graceful coordination interval. If the runtime does not become shutdown-ready within that interval, Jayrun escalates once to forced shutdown and then enters emergency cleanup if coordination still cannot complete. The timeout is not an execution deadline for arbitrary user code.

:::{warning}
Python cannot safely interrupt arbitrary running thread, extension, or native code. Keep user operations reasonably bounded even when forced shutdown is available.
:::

## Inspecting snapshots

{py:meth}`jayrun.Engine.get` returns the latest {py:class}`ContextSnapshot` without waiting:

```python
snapshot = engine.get(context_id)
if snapshot is not None:
    print(snapshot.state, snapshot.revision)
```

A snapshot is a structurally immutable point-in-time value. It never updates in place; call `get()` or a wait method again to observe a later revision. Artifact payload objects are referenced rather than deep-copied.

Useful fields include:

| Field | Meaning |
|---|---|
| `context_id` | Runtime-local identifier |
| `state`, `finalized` | Current lifecycle and finalization state |
| `revision`, `history` | Ordered lifecycle history |
| `iteration_count`, `stop_requested` | Iteration progress and stop intent |
| `created_at`, `validated_at`, `started_at`, `finished_at` | UTC lifecycle timestamps |
| `report` | Final context execution report, when available |
| `artifacts` | Retained artifact results |
| `failure`, `failed_step` | Failure and its step reference, when applicable |

Use `snapshot.artifact(reference)` to resolve a retained result by artifact declaration, inspected artifact definition, or graph-local artifact ID.

## Paused contexts

Pause is available inside a workflow through {py:meth}`ContextInterface.pause` and to a supervising context through {py:meth}`RuntimeInterface.pause`:

```python
self.context.pause()
self.context.pause(duration_seconds=30)
```

A pause request is queued. It does not suspend Python in the middle of the currently executing operator. Once applied, the context enters `PAUSED` and Jayrun stops dispatching new work for it. A duration schedules an automatic resume request.

Only a supervising runtime interface can explicitly resume another paused context. A context can schedule its own timed resume by providing `duration_seconds` when it requests the pause.

Graceful shutdown does not remain blocked by a paused context: it requests iteration stop, resumes the context, and lets its current iteration drain toward `STOPPED`.

## Result retention

Terminal contexts remain registered after finalization. Successful contexts retain exit artifacts by default because `ArtifactPolicy.retain_all` defaults to `True`. Intermediate values can still be cleared when they are no longer required.

A graph ending only in output-free sinks may have no exit artifacts. Its finalized snapshot still contains lifecycle and execution reports, but there is no exit payload for the retention policy to keep. The external effects belong to the destination systems, not to Jayrun's artifact registry.

Retention has two layers:

- the artifact policy decides which values enter the finalized snapshot;
- the context registry keeps that snapshot, report, history, and retained values until deletion, pruning, or engine shutdown.

Context results are process-local. Persist results explicitly when they must survive engine or process termination.

See {doc}`Artifacts and Data Flow <../concepts/artifacts-and-data-flow>` for artifact selection and clearing rules.

## Deleting contexts

Delete a known finalized terminal context after consuming or persisting its result:

```python
removed = engine.delete(context_id)
```

The method returns `True` when the context was removed and `False` when the ID was unavailable. Deleting an active or terminal-but-not-yet-finalized context raises `RuntimeError`.

Deletion removes the registry-owned snapshot state, including retained artifacts, report, and lifecycle history. Existing snapshots remain ordinary Python objects and can outlive registry deletion.

## Pruning contexts

{py:meth}`jayrun.Engine.prune` deletes finalized terminal contexts in completion order:

```python
deleted_ids = engine.prune(limit=100)
```

`limit=None` removes every eligible context. A non-negative integer removes at most that many; `limit=0` removes none. Older `finished_at` values are selected first, with context ID used as a deterministic tie-breaker.

Pruning never removes active or unfinalized contexts. It returns the removed IDs as a tuple.

:::{important}
For services that submit contexts continuously, delete results after consumption or prune periodically. Default result retention is intentionally convenient, but unbounded retained contexts also retain their selected payloads.
:::

## Graceful shutdown

The normal shutdown path is:

```python
engine.shutdown()
```

Graceful shutdown establishes a boundary that rejects new submissions, cancels delayed control messages, and requests iteration stop for non-terminal contexts. Paused contexts are resumed. Accepted work drains, contexts finalize, executors close, cached resources tear down, placement capacity is released, and the runtime loop closes.

With `timeout=None`, shutdown waits without a caller-defined graceful deadline. With a finite timeout, the runtime escalates to the forced path if graceful coordination does not finish in time.

Repeated shutdown after `STOPPED` is harmless. Calling shutdown on an engine that was never started transitions it directly from `CREATED` to `STOPPED`.

If shutdown encounters a fatal engine or cleanup failure, the engine ends in `FAILED` and raises its primary failure. Additional runtime and cleanup failures remain available through `secondary_failures` and `cleanup_failures`.

See {doc}`Failure and Reliability Model <../reliability/failure-and-reliability>` for startup rollback, timeout escalation, and failure precedence.

## Forced shutdown

Use forced shutdown when remaining work should be abandoned:

```python
engine.shutdown(forced=True, timeout=5)
```

Forced shutdown requests abort for every non-terminal, non-draining context, cancels placement waits, and asks executors to cancel their sessions before cleanup. Contexts that reach normal coordinated finalization become `ABORTED` rather than `STOPPED`.

When `forced=True` and `timeout=None`, Jayrun uses a bounded internal acknowledgement interval before switching to emergency cleanup. Supplying `timeout` replaces that initial interval.

Forced shutdown is lifecycle containment, not unsafe thread termination. Already running synchronous or native calls may ignore cancellation; emergency cleanup avoids waiting indefinitely for executor shutdown but cannot make arbitrary code interruptible.

## Context-manager usage

Use an engine as a synchronous context manager for the common start-and-graceful-shutdown lifecycle:

```python
from jayrun import Engine


with Engine() as engine:
    context_id = engine.submit(artifacts, configs)
    snapshot = engine.wait(context_id)
```

`__enter__()` starts the engine and returns it. `__exit__()` calls graceful shutdown even when the block raises. If both the block and shutdown fail, the block's exception remains primary and receives a note describing the shutdown failure.

For an asynchronous application, `Engine` is not an asynchronous context manager. Use `try`/`finally` with `await engine.shutdown_async()`.

## API reference

```{py:class} jayrun.Engine(settings=None)
Own and coordinate one Jayrun runtime.

:param settings: Engine settings, or `None` for defaults.
:type settings: EngineSettings | None
:raises TypeError: If `settings` is not an `EngineSettings` instance or `None`.
```

```{py:method} jayrun.Engine.start(loop=None) -> None
Start the runtime.

:param loop: Running application-owned event loop, or `None` for an engine-owned background loop.
:type loop: asyncio.AbstractEventLoop | None
:raises TypeError: If `loop` has an invalid type.
:raises RuntimeError: If the engine cannot start from its current state or the supplied loop is closed or not running.
:raises TimeoutError: If an external loop does not start the coordinator in time.
```

```{py:method} jayrun.Engine.submit(artifacts, configs=None, context_settings=None) -> int
Register one graph context and return its runtime-local identifier.

:param jayrun.ArtifactContext artifacts: Entry artifact values and graph identity.
:param configs: Configuration values for the same graph.
:type configs: jayrun.ConfigContext | None
:param context_settings: Per-context execution settings.
:type context_settings: ContextSettings | None
:returns: Registered context identifier.
:rtype: int
:raises TypeError: If an argument has an invalid type.
:raises RuntimeError: If the engine is not running.
```

```{py:method} jayrun.Engine.get(context_id) -> ContextSnapshot | None
Return the latest snapshot without waiting.

:param int context_id: Context identifier.
:returns: Immutable snapshot, or `None` if unavailable.
:raises TypeError: If `context_id` is not exactly an integer.
```

```{py:method} jayrun.Engine.wait(context_id, *, state=None, timeout=None) -> ContextSnapshot | None
Wait synchronously for finalization or a requested non-terminal state.

:param int context_id: Context identifier.
:param state: Requested state, or `None` for terminal finalization.
:type state: ContextState | None
:param timeout: Finite non-negative response deadline in seconds.
:type timeout: int | float | None
:returns: Matching or finalized snapshot, or `None` if unavailable.
:raises TypeError: If an argument has an invalid type.
:raises ValueError: If `timeout` is negative or non-finite.
:raises TimeoutError: If the condition is not reached before the deadline.
:raises RuntimeError: If synchronous waiting would block the runtime loop.
```

```{py:method} jayrun.Engine.wait_async(context_id, *, state=None, timeout=None) -> ContextSnapshot | None
Asynchronously wait for finalization or a requested non-terminal state.

:param int context_id: Context identifier.
:param state: Requested state, or `None` for terminal finalization.
:type state: ContextState | None
:param timeout: Finite non-negative response deadline in seconds.
:type timeout: int | float | None
:returns: Matching or finalized snapshot, or `None` if unavailable.
:raises TypeError: If an argument has an invalid type.
:raises ValueError: If `timeout` is negative or non-finite.
:raises TimeoutError: If the condition is not reached before the deadline.
```

```{py:method} jayrun.Engine.delete(context_id) -> bool
Delete one finalized terminal context.

:param int context_id: Context identifier.
:returns: Whether the context was removed.
:rtype: bool
:raises TypeError: If `context_id` is not exactly an integer.
:raises RuntimeError: If the context is not terminal and finalized.
```

```{py:method} jayrun.Engine.prune(*, limit=None) -> tuple[int, ...]
Delete finalized terminal contexts in completion order.

:param limit: Maximum number to remove, or `None` for all eligible contexts.
:type limit: int | None
:returns: Removed context identifiers.
:raises TypeError: If `limit` is not an integer or `None`.
:raises ValueError: If `limit` is negative.
```

```{py:method} jayrun.Engine.shutdown(forced=False, timeout=None) -> None
Shut down the runtime synchronously.

:param bool forced: Whether to begin by aborting remaining contexts.
:param timeout: Finite non-negative coordination interval in seconds.
:type timeout: int | float | None
:raises TypeError: If an argument has an invalid type.
:raises ValueError: If `timeout` is negative or non-finite.
:raises RuntimeError: If synchronous shutdown would block the runtime loop.
```

```{py:method} jayrun.Engine.shutdown_async(forced=False, timeout=None) -> None
Shut down the runtime without blocking the caller's event loop.

:param bool forced: Whether to begin by aborting remaining contexts.
:param timeout: Finite non-negative coordination interval in seconds.
:type timeout: int | float | None
:raises TypeError: If an argument has an invalid type.
:raises ValueError: If `timeout` is negative or non-finite.
:raises RuntimeError: If an engine-owned runtime loop attempts to shut itself down.
```

```{py:method} jayrun.Engine.__enter__() -> jayrun.Engine
Start and return the engine for synchronous context-manager use.
```

```{py:method} jayrun.Engine.__exit__(exception_type, exception, traceback) -> None
Run graceful shutdown when leaving a synchronous context-manager block.

If the block already raised, a shutdown failure is attached as a note instead of replacing the block's exception.
```

```{py:attribute} jayrun.Engine.state
:type: EngineState

Current engine lifecycle state.
```

```{py:attribute} jayrun.Engine.activity
:type: RuntimeActivity

Current runtime activity, independently of engine lifecycle state.
```

```{py:attribute} jayrun.Engine.failure
:type: BaseException | None

Primary fatal runtime or cleanup failure.
```

```{py:attribute} jayrun.Engine.secondary_failures
:type: tuple[BaseException, ...]

Additional fatal failures recorded after the primary failure.
```

```{py:attribute} jayrun.Engine.cleanup_failures
:type: tuple[BaseException, ...]

Failures recorded while shutting down runtime modules and resources.
```

```{py:class} EngineState
Engine lifecycle enumeration containing `CREATED`, `STARTING`, `RUNNING`, `STOPPING`, `STOPPED`, and `FAILED`.
```

```{py:class} RuntimeActivity
Runtime activity enumeration containing `IDLE` and `ACTIVE`.
```

```{py:class} ContextState
Observable context lifecycle enumeration.
```

```{py:attribute} ContextState.is_terminal
:type: bool

Whether the state is `REJECTED`, `FINISHED`, `STOPPED`, `FAILED`, or `ABORTED`.
```

```{py:attribute} ContextState.is_draining
:type: bool

Whether the state is `ABORTING` or `FAILING`.
```

```{py:attribute} ContextState.is_active
:type: bool

Whether the state belongs to active execution or draining.
```

```{py:class} ContextSnapshot
Structurally immutable point-in-time view of one registered context.
```

```{py:attribute} ContextSnapshot.context_id
:type: int

Runtime-local context identifier.
```

```{py:attribute} ContextSnapshot.state
:type: ContextState

Lifecycle state captured by this snapshot.
```

```{py:attribute} ContextSnapshot.finalized
:type: bool

Whether terminal reports and retained results have been attached.
```

```{py:attribute} ContextSnapshot.revision
:type: int

Monotonically increasing lifecycle revision.
```

```{py:attribute} ContextSnapshot.iteration_count
:type: int

Number of context iterations started.
```

```{py:attribute} ContextSnapshot.stop_requested
:type: bool

Whether iteration stop has been requested.
```

```{py:attribute} ContextSnapshot.created_at
:type: datetime.datetime

UTC registration timestamp.
```

```{py:attribute} ContextSnapshot.updated_at
:type: datetime.datetime

UTC timestamp of the latest lifecycle revision.
```

```{py:attribute} ContextSnapshot.validated_at
:type: datetime.datetime | None

UTC validation-completion timestamp.
```

```{py:attribute} ContextSnapshot.started_at
:type: datetime.datetime | None

UTC timestamp at which execution first entered `RUNNING`.
```

```{py:attribute} ContextSnapshot.finished_at
:type: datetime.datetime | None

UTC terminal-transition timestamp.
```

```{py:attribute} ContextSnapshot.history
:type: tuple

Immutable sequence of state transitions, iteration starts, and stop requests.
```

```{py:attribute} ContextSnapshot.report
:type: ContextReport | None

Final context execution report, when available.
```

```{py:attribute} ContextSnapshot.artifacts
:type: collections.abc.Mapping[jayrun.Artifact, ArtifactResult]

Immutable mapping of retained artifact declarations to results.
```

```{py:attribute} ContextSnapshot.failure
:type: Exception | None

Context failure, when the submission was rejected or execution failed.
```

```{py:attribute} ContextSnapshot.failed_step
:type: object | None

`StepReference` for the failed execution step, when available.
```

```{py:method} ContextSnapshot.artifact(reference) -> ArtifactResult
Return a retained artifact result.

:param reference: Artifact declaration, inspected artifact definition, or graph-local artifact ID.
:raises TypeError: If `reference` has an invalid type.
:raises KeyError: If the reference is foreign, unknown, or not retained.
```

:::{versionadded} 0.1.0
Engine lifecycle, synchronous and asynchronous waiting, context snapshots, retention management, and coordinated shutdown were introduced.
:::

Next, read {doc}`Execution Settings <../settings/execution-settings>` to distinguish engine-wide defaults from submission-specific policy and understand retry precedence.
