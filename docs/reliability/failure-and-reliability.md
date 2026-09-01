(failure-and-reliability)=
# Failure and Reliability Model

Jayrun separates failures by ownership. Invalid public calls fail at the caller boundary, ordinary computation failures belong to one context, and runtime infrastructure failures fail the engine. Retry, failure mode, rollback, and shutdown then determine how far each failure propagates.

This model contains failures; it does not make arbitrary computation transactional or exactly once.

## Failure categories

| Category | Typical source | Observable result | Engine effect |
|---|---|---|---|
| Public input error | Invalid argument type, range, or call state | The public method raises | None |
| Context rejection | Invalid graph values, missing required data, or unresolved context policy | Finalized `ContextRun` in `REJECTED` with `report.failure` | Governed by failure mode |
| Execution failure | Operator, resource, placement, or result-contract failure | Retry, then a finalized run in `FAILED` if exhausted | Governed by failure mode |
| Runtime module failure | Coordinator, executor, registry, messaging, or resource-manager fault | Primary engine failure | Forced coordinated shutdown |
| Cleanup failure | Module or resource teardown fault | `cleanup_failures` and possibly primary engine failure | Engine ends `FAILED` |
| Internal invariant violation | Framework state contradicts its own lifecycle rules | Fatal engine failure | Forced coordinated shutdown |

An ordinary user-code `Exception` returned through an execution boundary is eligible for retry and context failure handling. A non-`Exception` `BaseException`, such as `KeyboardInterrupt` or `SystemExit`, is outside that contract and is reported as a fatal runtime failure.

:::{important}
Failure ownership is determined by where the failure occurs, not merely by its Python type. For example, a `RuntimeError` raised by an operator is a context failure; the same type raised because the executor queue is internally inconsistent is a runtime failure.
:::

## Public input errors

Public methods validate their immediate arguments before mutating runtime state. Invalid types, invalid timeout values, and calls that are incompatible with the engine state raise directly:

```python
from jayrun import Engine


engine = Engine()
engine.start()

try:
    engine.submit(object(), object())
except TypeError:
    assert engine.state.value == "running"
finally:
    engine.shutdown()
```

These errors do not create a context and do not fail a running engine.

Validation that requires a registered context is different. For example, missing required artifact or configuration values produce a `ContextRun` that finalizes in `REJECTED`. Inspect `run.report.failure` for the cause.

## Context failures

A context owns failures produced while validating or executing its declared computation. Common causes include:

- an operator or resource setup raising an ordinary `Exception`;
- an execution violating its output return contract, such as returning a value from a sink or the wrong number of tuple positions;
- a resource setup returning an invalid value;
- an impossible placement request;
- exhausted retry attempts.

When execution fails, Jayrun first applies the effective {py:class}`jayrun.settings.RetryPolicy`. If no retry applies, the context enters failure finalization and reaches `FAILED`. Validation failures reach `REJECTED` instead.

Output-free terminal operators are ordinary executions for failure handling. A successful external write completes the step without publishing an artifact; an exception still follows retry and context-failure policy. Because a retry may repeat the write, sink operations should be idempotent or transactional. See {ref}`terminal-operators`.

```python
run.wait()

if run.state.value in {"failed", "rejected"}:
    print(type(run.report.failure).__name__, run.report.failure)
    print(run.report.failed_step)
```

`ContextRun.wait()`, `Engine.wait()`, and their asynchronous counterparts report normal context failures through the run; they do not raise them in the waiting application.

Failed and aborted contexts do not retain successful artifact payloads. Their lifecycle history, failure, failed-step reference, stored values, and diagnostic report remain inspectable through a run already held by the caller.

## `continue` behavior

`FailureMode.CONTINUE` is the default. After retries are exhausted, Jayrun finalizes the failed context while the engine remains running. Other registered contexts continue independently, and the application may submit more work.

```python
from jayrun.settings import EngineSettings, FailureMode


engine = Engine(EngineSettings(failure_mode=FailureMode.CONTINUE))
```

`CONTINUE` is context-failure isolation. It does not suppress the failure: the terminal run still reports it, and observability records retain the available diagnostics.

## `fail_fast` behavior

`FailureMode.FAIL_FAST` promotes an exhausted context failure to an engine failure:

```python
engine = Engine(EngineSettings(failure_mode=FailureMode.FAIL_FAST))
```

The failed context still records its own outcome. In addition, the engine records the failure, enters `STOPPING`, and begins forced coordinated shutdown. Remaining contexts are driven toward abort and finalization before runtime cleanup.

Fail-fast does not change which exceptions are retryable or how many attempts are allowed. Retry policy is applied first; failure mode is consulted only when a context failure is no longer recoverable.

:::{warning}
Fail-fast reduces the lifetime of a compromised runtime, but it does not roll back external side effects already performed by operators.
:::

## Runtime module failures

Runtime modules implement coordination rather than user computation. Unexpected failures in the coordinator loop, executor submission, registry mutation, messaging, resource management, or placement reconciliation are fatal because Jayrun can no longer guarantee coherent ownership or scheduling.

These failures bypass `CONTINUE`. The engine records the first failure as {py:attr}`jayrun.Engine.failure`, transitions to `STOPPING`, and starts forced shutdown. Later fatal failures are preserved in {py:attr}`jayrun.Engine.secondary_failures`.

An operator's ordinary `Exception` is captured by its execution proxy and does not reach this path. If execution escapes with a non-`Exception` `BaseException`, Jayrun wraps it for context finalization and also reports the original failure to the engine.

## Engine failure transition

A fatal failure follows one centralized transition:

1. Record the first fatal failure as the primary failure.
2. Preserve subsequent fatal failures as secondary failures.
3. Move a running engine from `RUNNING` to `STOPPING`.
4. Establish the shutdown boundary so new submissions are rejected.
5. Start forced coordinated shutdown.
6. Clean runtime modules and record cleanup failures.
7. End in `FAILED` and raise the primary failure at the public lifecycle boundary.

The engine does not transition back to `RUNNING`. Create a new {py:class}`jayrun.Engine` after a failed runtime has shut down.

See {doc}`Engine and Context Lifecycle <../runtime/engine-and-context-lifecycle>` for the complete state model.

## Centralized supervision

Jayrun has one internal lifecycle supervisor responsible for startup, fatal-failure recording, shutdown ownership, cleanup, and the final engine state. This prevents independent modules from running competing shutdown procedures.

This internal mechanism is distinct from workflow supervision through `self.runtime`. A supervising context may inspect and control authorized existing runs. It does not originate contexts, own the engine lifecycle, or replace the internal failure supervisor.

:::{note}
Applications originate contexts through {py:meth}`jayrun.Engine.submit`. Supervising contexts operate only on contexts that already exist.
:::

## Startup rollback

Startup is transactional at the runtime level. The engine enters `STARTING`, constructs the runtime, initializes modules, and starts coordination. If any stage fails, Jayrun:

1. records the startup failure;
2. enters `STOPPING`;
3. runs forced emergency cleanup against the partially built runtime;
4. records any cleanup failures;
5. enters `FAILED`; and
6. raises the primary failure from {py:meth}`jayrun.Engine.start`.

A failed engine cannot be restarted. This avoids reusing modules whose initialization outcome is uncertain.

## Cleanup after partial initialization

Jayrun registers initialized runtime state incrementally so later failure can release what already exists. Context registration similarly removes a partially created execution context and attempts to release sessions, resource pins, recorders, artifact state, and placement reservations.

Runtime cleanup is best effort across all modules: one cleanup failure does not prevent Jayrun from attempting the remaining module cleanups. Multiple failures may be combined or recorded separately.

Resource setup has a narrower boundary. Jayrun can call resource teardown only after setup has returned valid setup data and the resource has been registered. If setup acquires external state and then raises before registration, setup must release that partial state itself.

See {doc}`Resources <../concepts/resources>` for the setup and teardown contract.

## Shutdown failure handling

Shutdown failures are not silently discarded. Jayrun records each failure in {py:attr}`jayrun.Engine.cleanup_failures` while continuing to close other runtime modules.

If no earlier fatal failure exists, the first cleanup failure becomes the engine's primary failure. Otherwise, the original failure remains primary and cleanup failures remain attached as diagnostics. The engine ends in `FAILED`, and `shutdown()` or `shutdown_async()` raises the primary failure after cleanup completes.

When an engine context-manager block and shutdown both fail, the block's exception remains primary. Jayrun adds a note describing the shutdown failure rather than replacing the application error.

## Timeout escalation

The meaning of `timeout` depends on the operation:

| Operation | Timeout behavior |
|---|---|
| `wait()` / `wait_async()` | Raises `TimeoutError`; the context continues |
| Graceful shutdown | Ends the graceful coordination interval, then escalates to forced shutdown |
| Forced shutdown | Bounds the initial forced acknowledgement interval before emergency cleanup |

A graceful shutdown timeout is therefore not returned as a simple `TimeoutError`. Jayrun escalates once to forced shutdown. If the runtime still cannot acknowledge shutdown, or coordination has already failed, the supervisor enters emergency cleanup.

Internal cleanup stages also use bounded waits so failed coordination does not block the shutdown owner indefinitely.

:::{warning}
Forced or emergency shutdown cannot safely interrupt arbitrary synchronous Python, extension, or native code. Design user operations with bounded calls, cooperative cancellation where available, and externally recoverable side effects.
:::

## Reliability guarantees

Within the documented boundaries, Jayrun guarantees that:

- public argument errors are rejected before submission state is mutated;
- graph and context inputs are validated before normal execution;
- ordinary context failures are isolated under `CONTINUE`;
- exhausted failures initiate runtime shutdown under `FAIL_FAST`;
- retries follow the effective retry policy and bounded attempt count;
- fatal runtime failures use one centralized shutdown owner;
- cleanup is attempted for every initialized runtime module;
- partial context and runtime initialization is rolled back where ownership was registered;
- primary, secondary, and cleanup failures remain inspectable;
- placement and resource ownership is released through coordinated finalization and cleanup.

Jayrun does not guarantee exactly-once execution, transactional external side effects, durable in-process results, or safe interruption of arbitrary user code. Retries, repetitions, placement reconciliation, and resubmission can all execute user code more than once.

## Internal invariant violations

An invariant violation means the framework's internal state contradicts a condition required for safe coordination—for example, an impossible lifecycle transition, inconsistent ownership registry, or unexpected executor completion.

Such failures indicate a framework defect or corrupted runtime state. Jayrun keeps them visible, records them as fatal engine failures, and shuts down. It does not disguise them as an ordinary operator failure merely to keep the runtime alive.

Public misuse is not an invariant violation. Invalid public arguments and invalid graph inputs follow their documented public-error or context-rejection paths.

When reporting a suspected invariant violation, retain the primary failure, secondary and cleanup failures, engine state, affected context runs, debug-mode records, and the smallest reproducing graph.

## Related reference

- {doc}`Operators and Executions <../components/operators-and-executions>` — execution attempts, retries, and user-code failure behavior.
- {doc}`Execution Settings <../settings/execution-settings>` — retry and failure-mode configuration.
- {doc}`Engine and Context Lifecycle <../runtime/engine-and-context-lifecycle>` — public engine and context states.
- {doc}`Observability and Inspection <../observability/observability-and-inspection>` — failure reports and diagnostic records.
