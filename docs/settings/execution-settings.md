(execution-settings)=
# Execution Settings

Execution settings control how Jayrun runs declared computation. They define runtime diagnostics, failure behavior, executor capacity, device capacity, artifact retention, iteration, repetition, and supervision. They are operational policy—not values injected through {py:class}`jayrun.ConfigField`.

All settings objects are immutable validated values. Pass {py:class}`jayrun.settings.EngineSettings` to {py:class}`jayrun.Engine`, and pass {py:class}`jayrun.settings.ContextSettings` to {py:meth}`jayrun.Engine.submit`.

## Settings ownership and boundary

The boundary is the lifetime of the decision:

| Settings object | Supplied when | Applies to | Can it override the other scope? |
|---|---|---|---|
| `EngineSettings` | Constructing `Engine` | Every context in that engine | Establishes runtime-wide policy and defaults |
| `ContextSettings` | Submitting one context | Only that graph submission | May replace only the engine's retry policy |

`EngineSettings` owns decisions that require one coherent runtime: diagnostic mode, response to an exhausted context failure, executor capacity, managed devices, and the default retry policy. A context cannot change those capacities or the engine-wide failure mode.

`ContextSettings` owns decisions local to one submission: artifact retention, iteration and repetition bounds, supervising capability, and an optional retry-policy override. Different contexts in the same engine may use different context settings.

The nested policy objects follow that ownership:

| Object | Owner | Purpose |
|---|---|---|
| `ArtifactPolicy` | Context | Select retained exit payloads and entry-reference handling |
| `RetryPolicy` | Engine default or context override | Define retryable exceptions and attempt limits |
| `RuntimeDevice` | Engine | Declare capacity managed by the placement system |

Settings do not flow through the graph and are not available as operator config fields. Operators interact with their effects through the operational interfaces and runtime behavior.

## Engine settings

{py:class}`jayrun.settings.EngineSettings` configures one runtime:

```python
from jayrun import Engine
from jayrun.settings import EngineSettings, FailureMode, RetryPolicy


settings = EngineSettings(
    failure_mode=FailureMode.CONTINUE,
    retry_policy=RetryPolicy(
        max_attempts=3,
        retry_on=(TimeoutError, ConnectionError),
    ),
    max_workers=8,
    max_tasks=256,
)

engine = Engine(settings)
```

| Field | Default | Meaning |
|---|---:|---|
| `runtime_mode` | `PRODUCTION` | Diagnostic recording detail |
| `failure_mode` | `CONTINUE` | Runtime response to a context failure |
| `retry_policy` | `RetryPolicy()` | Default execution retry policy: one attempt and no retryable exceptions |
| `max_workers` | `None` | Synchronous worker limit; `None` selects the platform default |
| `max_tasks` | `None` | Asynchronous task limit; `None` selects Jayrun's default |
| `runtime_devices` | `()` | Managed device declarations; CPU is added when absent |

Production mode records logs and metrics but omits detailed timers, failure histories, and full artifact history. Debug mode retains those additional diagnostics.

## Context settings

{py:class}`jayrun.settings.ContextSettings` applies to one submission:

```python
from jayrun.settings import ArtifactPolicy, ContextSettings, RetryPolicy


context_settings = ContextSettings(
    artifact_policy=ArtifactPolicy(retain_all=False),
    retry_policy=RetryPolicy(max_attempts=2, retry_on=(TimeoutError,)),
    max_iterations=5,
    max_repeats=3,
    supervising=False,
)

context_id = engine.submit(
    artifacts,
    configs,
    context_settings=context_settings,
)
```

| Field | Default | Meaning |
|---|---:|---|
| `artifact_policy` | retain all exits | Final artifact retention and entry-reference policy |
| `retry_policy` | `None` | Context retry override; `None` inherits the engine policy |
| `max_iterations` | `1` | Maximum graph iterations; `None` is unbounded |
| `max_repeats` | `None` | Maximum additional executions per step session; `None` is unbounded |
| `supervising` | `False` | Grant supervising runtime capabilities |

Iteration and repetition are separate limits. `max_iterations=5` allows at most five graph iterations. `max_repeats=3` allows the initial execution plus at most three requested repetitions in each step session.

The {py:attr}`jayrun.settings.ContextSettings.supervising` flag grants that context the restricted `RuntimeInterface` capabilities used to inspect and control other existing contexts. It does not allow a component to originate or submit contexts.

(artifact-policy-settings)=
## Artifact policy

The default {py:class}`jayrun.settings.ArtifactPolicy` retains every exit artifact:

```python
ArtifactPolicy()
```

Select specific exit artifacts by disabling `retain_all`:

```python
policy = ArtifactPolicy(
    retain_all=False,
    retained_artifacts=(result,),
)
```

References may be artifact objects, graph-local artifact IDs, or artifact definitions returned by inspection. Selected references must resolve to exit artifacts in the submitted graph.

Set `retain_all=False` with an empty tuple for fire-and-forget work. Set `release_entry_artifacts=True` to clear the submitted context's input mapping after its values have been loaded into the runtime artifact store.

Retention changes payload lifetime, not artifact records. Cleared results still expose their transition report, but `ArtifactResult.value` is `None`.

See {ref}`artifact-retention` for the complete artifact lifecycle.

## Retry policy

{py:class}`jayrun.settings.RetryPolicy` controls whether an individual failed execution is attempted again. `max_attempts` includes the initial attempt, and `retry_on` contains the `Exception` subclasses eligible for another attempt.

```python
retry_policy = RetryPolicy(
    max_attempts=3,
    retry_on=(TimeoutError, ConnectionError),
)
```

Retry matching uses normal exception inheritance, so listing `ConnectionError` also matches its subclasses. Duplicate exception classes are removed while preserving their order. When `max_attempts > 1` and `retry_on` is empty, Jayrun normalizes it to `(Exception,)`. When `max_attempts == 1`, `retry_on` must remain empty because no retry can occur.

The engine policy is the default for every submitted context:

```python
engine_settings = EngineSettings(
    retry_policy=RetryPolicy(
        max_attempts=3,
        retry_on=(TimeoutError, ConnectionError),
    ),
)
```

A context with `retry_policy=None`, including the default `ContextSettings()`, inherits that complete policy. Supplying a context policy replaces the engine policy as a whole:

```python
context_settings = ContextSettings(
    retry_policy=RetryPolicy(
        max_attempts=2,
        retry_on=(TemporaryServiceError,),
    ),
)
```

For this context, only `TemporaryServiceError` is retryable and at most two attempts are made. `TimeoutError` and `ConnectionError` are not inherited from the engine policy. Exception sets and attempt limits are never merged.

:::{warning}
Retries repeat user code and can repeat external side effects. Use idempotent writes, transactions, or application-level deduplication when an operator interacts with an external system.
:::

## Failure mode

{py:class}`jayrun.settings.FailureMode` controls what happens after a context failure is no longer retryable:

| Mode | Behavior |
|---|---|
| `CONTINUE` | Isolate the failed context; the engine and other contexts continue |
| `FAIL_FAST` | Mark the engine failed and begin coordinated forced shutdown |

Failure mode is engine-wide. Context settings can override retry behavior, but cannot override the engine's response to an exhausted failure.

See {doc}`Failure and Reliability Model <../reliability/failure-and-reliability>` for containment, fail-fast escalation, and cleanup behavior.

## Runtime mode

{py:class}`jayrun.settings.RuntimeMode` selects recording detail:

| Mode | Records |
|---|---|
| `PRODUCTION` | Logs, metrics, and the latest artifact transition state |
| `DEBUG` | Production records plus timers, execution failure history, and complete artifact history |

Debug mode increases diagnostic retention. It does not change operator semantics, validation rules, or failure policy.

See {doc}`Observability and Inspection <../observability/observability-and-inspection>` for the resulting context, execution, attempt, and artifact report structures.

## Executor limits

Synchronous and asynchronous execution use separate capacities:

- `max_workers` bounds the thread pool used by synchronous operators and synchronous resource setup.
- `max_tasks` bounds concurrently registered asynchronous execution tasks on the runtime event loop.

When `max_workers` is `None`, Jayrun uses `min(32, (os.cpu_count() or 1) + 4)`. When `max_tasks` is `None`, asynchronous capacity is 1000.

These are runtime-wide limits, not per-context limits. Context scheduling, dependencies, resources, and placement capacity may reduce actual concurrency further.

## Runtime device declarations

Declare accelerator capacity with {py:class}`jayrun.settings.RuntimeDevice`:

```python
from jayrun.placement import Backend, Device
from jayrun.settings import EngineSettings, RuntimeDevice


cuda_device = RuntimeDevice(
    device=Device.GPU,
    backends=(Backend.CUDA,),
    device_id=0,
    memory_limit_gb=8,
)

settings = EngineSettings(runtime_devices=(cuda_device,))
```

Accelerators require at least one backend, a non-negative device ID, and a positive finite memory limit. Device-kind and device-ID pairs must be unique.

Jayrun automatically appends a CPU declaration if one is absent. A CPU declaration may set `memory_limit_gb` to define the memory-pressure limit used by scheduler admission. It cannot specify backends, a device ID, or `exclusive_only=True`. CPU memory is not reserved through a placement lease.

`exclusive_only=True` makes an accelerator permanently available only to exclusive placement requests. It differs from requesting `exclusive=True` for one lease through {py:class}`PlacementInterface`.

See {doc}`Placement Interface <../interfaces/placement>` for reservation requests and {doc}`Placement and Capacity <../runtime/placement-and-capacity>` for allocation, contention, and admission behavior.

## Constructing settings in Python

Settings are frozen dataclasses. Construct complete policy objects before starting or submitting work:

```python
engine_settings = EngineSettings(max_workers=4)
context_settings = ContextSettings(max_iterations=2)

with Engine(engine_settings) as engine:
    context_id = engine.submit(
        artifacts,
        configs,
        context_settings=context_settings,
    )
    snapshot = engine.wait(context_id)
```

Create a new settings object when policy changes. Do not treat a running engine's settings as mutable control state.

:::{important}
YAML support belongs to graph configuration values. Jayrun does not load engine or context settings from `ConfigContext` YAML.
:::

## Validation and precedence

Settings validate their types and ranges during construction. Graph-local artifact references are resolved when a context is registered.

The effective policy follows these rules:

1. Engine settings establish runtime mode, failure mode, the default retry policy, executor limits, and managed devices.
2. Context settings establish artifact policy, iteration and repetition limits, supervision, and an optional retry override.
3. A context retry policy replaces the engine retry policy; `None` inherits it.
4. `retain_all=True` is normalized to the submitted graph's concrete exit artifacts.
5. Retained artifact IDs and definitions are resolved against that graph.

## Internal combined settings

Jayrun internally produces a context-effective record after resolving engine defaults, context overrides, and graph-local artifact references.

This combined representation is implementation detail. Applications should not import or construct it. Use only {py:class}`jayrun.settings.EngineSettings`, {py:class}`jayrun.settings.ContextSettings`, and their documented nested policy objects.

For an executable combination of indefinite iteration, pause milestones, supervision, and placed model artifacts, see {doc}`MNIST Inference and Supervised Training <../tutorials/mnist-inference-and-training>`.

## API reference

```{py:class} jayrun.settings.EngineSettings(runtime_mode=RuntimeMode.PRODUCTION, failure_mode=FailureMode.CONTINUE, retry_policy=RetryPolicy(), max_workers=None, max_tasks=None, runtime_devices=())
Configure one engine runtime.

:param jayrun.settings.RuntimeMode runtime_mode: Production or debug recording mode.
:param jayrun.settings.FailureMode failure_mode: Continue or fail-fast behavior after context failure.
:param jayrun.settings.RetryPolicy retry_policy: Default execution retry policy inherited by contexts that do not supply an override.
:param max_workers: Positive synchronous worker count, or `None` for the platform default.
:type max_workers: int | None
:param max_tasks: Positive asynchronous task capacity, or `None` for Jayrun's default.
:type max_tasks: int | None
:param runtime_devices: One managed device or a tuple of managed devices.
:type runtime_devices: jayrun.settings.RuntimeDevice | tuple[jayrun.settings.RuntimeDevice, ...]
:raises TypeError: If an option has an invalid type.
:raises ValueError: If limits are non-positive or device declarations conflict.
```

```{py:class} jayrun.settings.ContextSettings(artifact_policy=ArtifactPolicy(), retry_policy=None, max_iterations=1, max_repeats=None, supervising=False)
Configure one submitted context.

:param jayrun.settings.ArtifactPolicy artifact_policy: Artifact retention and entry-reference policy.
:param retry_policy: Complete retry-policy replacement, or `None` to inherit the engine policy.
:type retry_policy: jayrun.settings.RetryPolicy | None
:param max_iterations: Positive graph-iteration limit, or `None` for unbounded iteration.
:type max_iterations: int | None
:param max_repeats: Positive additional-execution limit, or `None` for unbounded repetition.
:type max_repeats: int | None
:param bool supervising: Whether the context receives supervising runtime capabilities.
:raises TypeError: If an option has an invalid type.
:raises ValueError: If an iteration or repetition limit is below one.
```

```{py:attribute} jayrun.settings.ContextSettings.max_repeats
:type: int | None

Maximum number of additional executions accepted for one operator step session. The initial execution is not counted. `None` permits unbounded repetition.
```

```{py:attribute} jayrun.settings.ContextSettings.supervising
:type: bool

Whether the submitted context receives capability-controlled cross-context inspection and lifecycle operations through its runtime interface.

This setting does not allow the context to submit or originate other contexts.
```

```{py:class} jayrun.settings.ArtifactPolicy(retain_all=True, retained_artifacts=(), release_entry_artifacts=False)
Configure final artifact payload retention for one submitted context.

:param bool retain_all: Retain every exit artifact after normal or stop-requested iteration finalization.
:param tuple retained_artifacts: Selected exit references to retain when `retain_all` is false.
:param bool release_entry_artifacts: Clear the submitted context's input mapping after loading entry values.
:raises TypeError: If an option or retained reference has an invalid type.
:raises ValueError: If IDs are negative, references are duplicated, or selected references are supplied with `retain_all=True`.
```

```{py:class} jayrun.settings.RetryPolicy(max_attempts=1, retry_on=())
Configure exception-based execution retries.

:param int max_attempts: Maximum attempts per execution, including the initial attempt.
:param tuple retry_on: `Exception` subclasses eligible for another attempt; an empty tuple with multiple attempts is normalized to `(Exception,)`.
:raises TypeError: If arguments or exception entries have invalid types.
:raises ValueError: If `max_attempts` is below one or `retry_on` is supplied with one attempt.
```

```{py:class} jayrun.settings.RuntimeDevice(device=Device.CPU, backends=(), device_id=None, memory_limit_gb=None, exclusive_only=False)
Declare one device managed by the engine runtime.

:param Device device: Device kind.
:param tuple backends: Supported {py:class}`Backend` values.
:param device_id: Non-negative accelerator ID, or `None` for CPU.
:type device_id: int | None
:param memory_limit_gb: Positive finite capacity in decimal gigabytes. For accelerators this is allocatable placement capacity; for CPU it is the scheduler's memory-pressure limit.
:type memory_limit_gb: int | float | None
:param bool exclusive_only: Whether the device accepts only exclusive placement requests.
:raises TypeError: If an option has an invalid type.
:raises ValueError: If device constraints are inconsistent.
```

```{py:class} jayrun.settings.RuntimeMode
Runtime recording mode with `PRODUCTION` and `DEBUG` members.
```

```{py:class} jayrun.settings.FailureMode
Runtime failure policy with `CONTINUE` and `FAIL_FAST` members.
```

:::{versionadded} 0.1.0
Immutable engine and context settings, retention policies, retries, failure modes, runtime modes, executor limits, and managed-device declarations were introduced.
:::

Graph-scoped computational values are documented separately under {doc}`Configuration <../concepts/configuration>`.

Next, read {doc}`Failure and Reliability Model <../reliability/failure-and-reliability>` for the runtime behavior that follows retry exhaustion, context failure, and fail-fast escalation.
