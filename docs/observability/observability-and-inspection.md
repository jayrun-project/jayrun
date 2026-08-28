(observability-and-inspection)=
# Observability and Inspection

Jayrun exposes completed computation as immutable context snapshots, context and execution reports, artifact results, and structured diagnostic records. Operators can also publish durable results or live telemetry to external systems explicitly.

Observability data has two distinct paths:

- **Finalized reports** describe context, execution, and artifact history after execution drains.
- **Operational-interface records** provide scoped values while workflows are running.

They are complementary. A {py:class}`ValueRecord` is not an {py:class}`ExecutionRecord`, and neither is a durable external log by itself.

## Context snapshots

The application inspects a context through {py:meth}`jayrun.Engine.get`, {py:meth}`jayrun.Engine.wait`, or {py:meth}`jayrun.Engine.wait_async`:

```python
snapshot = engine.get(context_id)

if snapshot is not None:
    print(snapshot.state.value, snapshot.revision)
```

A {py:class}`ContextSnapshot` is a structurally immutable point-in-time view. Fetch another snapshot to observe a later revision. Artifact payloads and exception objects are referenced rather than deep-copied.

Before terminal finalization, `report` may be `None` and retained results may not yet be available. Waiting without a requested state returns only after a terminal context has finalized:

```python
snapshot = engine.wait(context_id)

if snapshot is None:
    raise RuntimeError("context is unavailable")
```

Lifecycle fields, timestamps, history, failure information, and the complete snapshot API are documented in {doc}`Engine and Context Lifecycle <../runtime/engine-and-context-lifecycle>`.

## Artifact results

Every finalized artifact is represented by an {py:class}`ArtifactResult`:

```python
result = snapshot.artifact(output_artifact)

value = result.value
placement = result.placement
history = result.report
```

The result pairs the final {py:class}`jayrun.Data` container with an ordered tuple of {py:class}`ArtifactRecord` objects. A cleared or non-retained artifact remains inspectable, but its payload value is `None`.

Failed and aborted contexts do not publish partial payloads. Their artifact reports can still explain which values were registered, updated, or cleared before finalization.

See {doc}`Artifacts and Data Flow <../concepts/artifacts-and-data-flow>` for result retention, clearing, placement metadata, and the canonical artifact-result API.

## Context reports

A finalized execution context attaches one {py:class}`ContextReport` to `snapshot.report`:

```python
report = snapshot.report

if report is not None:
    for execution in report.executions:
        print(execution.step_name, execution.outcome.value)
```

`ContextReport.executions` contains {py:class}`ExecutionReport` objects in the order they were recorded. It includes operator executions, resource setup executions, and steps skipped because required runtime data was unavailable.

A rejected submission has no execution context and therefore no context report. Its validation error is available through `snapshot.failure`.

## Execution records

An {py:class}`ExecutionReport` describes one logical step session in one context iteration. Retries and repetitions remain grouped inside that report:

```python
for execution in snapshot.report.executions:
    print(
        execution.step_kind,
        execution.step_name,
        execution.iteration,
        execution.execution_count,
        execution.outcome.value,
    )

    for attempt in execution.attempts:
        print(attempt.execution, attempt.attempt)
```

Each {py:class}`AttemptRecord` identifies the repeated execution number and retry attempt number, then contains its diagnostic records.

The diagnostic record hierarchy is:

| Record | Payload |
|---|---|
| {py:class}`LogRecord` | `message` |
| {py:class}`MetricRecord` | `name`, `value` |
| {py:class}`TimerRecord` | `name`, `elapsed_time` |
| {py:class}`FailureRecord` | `exception` |

All four inherit `origin` and `execution` from {py:class}`ExecutionRecord`. `RecordOrigin.USER` identifies calls made through `self.execution`; `RecordOrigin.INTERNAL` identifies framework-generated diagnostics.

A skipped step has `outcome=ExecutionOutcome.SKIPPED`, no attempts, `execution_count=0`, and a textual `skip_reason`.

:::{note}
{py:class}`ValueRecord` belongs to scoped key-value storage and carries a key, value, timestamp, context, iteration, and execution provenance. Diagnostic `ExecutionRecord` objects instead belong to finalized execution reports.
:::

## Artifact records

An {py:class}`ArtifactRecord` describes one artifact lifecycle observation:

| Attribute | Meaning |
|---|---|
| `state` | `UNREGISTERED`, `REGISTERED`, `UPDATED`, or `CLEARED` |
| `actor` | Entry, operator, or internal runtime actor |
| `step_index` | Associated compiled step, when applicable |
| `iteration` | Context iteration containing the observation |

Production recording retains the latest lifecycle record for each artifact. Debug recording retains the complete ordered history. When an artifact has no transition, its report contains one `UNREGISTERED` record.

Artifact records describe Jayrun's references and transitions. They do not provide byte-level data lineage, external storage versions, or mutation tracking inside a mutable payload.

## Logs

Record a structured message from an operator or resource setup:

```python
self.execution.log("starting transformation")
```

The message becomes a user-origin {py:class}`LogRecord` in the current attempt. Logs are recorded in both production and debug modes.

Jayrun execution logs are not calls to Python's `logging` package. They do not inherit application handlers, formatting, levels, or destinations, and they are not streamed before context finalization.

Use an external logging client directly when messages must be searchable or visible while execution is still running.

## Metrics

Record a numeric measurement with {py:meth}`ExecutionInterface.metric`:

```python
self.execution.metric("sample_count", 128)
self.execution.metric("accuracy", 0.94)
```

Metrics become {py:class}`MetricRecord` objects attached to the current attempt. Production and debug modes both retain them.

Metric names are local strings. Jayrun does not aggregate them across executions, assign units, calculate percentiles, or export them automatically. Perform aggregation after finalization or send measurements to an external monitoring client during execution.

## Timers

Use named timers to measure a region:

```python
self.execution.start_timer("transform")
result = transform(self.input_data.value)
self.execution.stop_timer("transform")
```

In debug mode, `stop_timer()` creates a {py:class}`TimerRecord` whose `elapsed_time` is measured with a monotonic high-resolution process clock. Starting the same name again replaces its previous start. Stopping an unknown timer is harmless.

Production mode accepts timer calls but records no timer values. Timers measure elapsed duration; they do not enforce deadlines or interrupt execution.

:::{warning}
If execution exits before a named timer is stopped, that timer produces no user record. Use `try`/`finally` when the measurement must close on both success and failure.
:::

```python
self.execution.start_timer("transform")
try:
    result = transform(self.input_data.value)
finally:
    self.execution.stop_timer("transform")
```

## Production and debug recorders

Select recording detail through {py:class}`jayrun.settings.RuntimeMode`:

```python
from jayrun import Engine
from jayrun.settings import EngineSettings, RuntimeMode


engine = Engine(
    EngineSettings(runtime_mode=RuntimeMode.DEBUG),
)
```

| Recorded information | `PRODUCTION` | `DEBUG` |
|---|---:|---:|
| Context and execution reports | Yes | Yes |
| Logs | Yes | Yes |
| Metrics | Yes | Yes |
| Timers | No | Yes |
| Failure records inside attempts | No | Yes |
| Artifact lifecycle report | Latest state | Complete history |

The context failure itself remains available through `snapshot.failure` in either mode. Production mode omits the duplicate failure record inside the attempt report; it does not hide the context outcome.

Jayrun chooses the production or debug context, execution, and artifact recorder implementations internally. Applications should select `RuntimeMode`, not construct recorder classes or attach custom recorders.

Recording mode is engine-wide and fixed when the engine is constructed. It does not change scheduling, retry, failure policy, retention, or component behavior.

## Persisting results through operators

Jayrun keeps snapshots and retained artifacts in process memory. An operator should write durable results when they must outlive context deletion, pruning, engine shutdown, or process termination.

This terminal operator writes JSON to a temporary file and atomically replaces the destination without creating an artificial graph output:

```python
import json
from pathlib import Path

from jayrun import ArtifactField, BaseOperator, ConfigField


class PersistJson(BaseOperator):
    def __init__(
        self,
        *,
        input_data,
        name=None,
        description=None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.input_data = ArtifactField(required=True)
        self.destination = ConfigField(value_type=str, required=True)
        self.outputs = ()

    def execute(self) -> None:
        destination = Path(self.destination.value)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.input_data.value),
            encoding="utf-8",
        )
        temporary.replace(destination)
```

The external file is the durable result; the operator publishes no artifact. The same pattern applies to databases, object stores, HTTP endpoints, message brokers, experiment trackers, and model registries. When later graph work needs a reference to the external result, declare and return a connected output artifact instead. See {ref}`terminal-operators`.

:::{important}
An operator may execute again because of retry, repetition, placement restart, or another context submission. External writes must therefore be idempotent or protected by transactions, deterministic object keys, compare-and-swap logic, or equivalent application guarantees. Jayrun does not provide exactly-once side effects.
:::

Persist before deleting or pruning the completed context. Deleting a context releases Jayrun's retained references; it does not delete an external result created by the operator.

## External monitoring integration

An application can poll immutable snapshots and use `revision` to avoid publishing the same lifecycle observation twice:

```python
import time


last_revision = -1

while True:
    snapshot = engine.get(context_id)
    if snapshot is None:
        break

    if snapshot.revision != last_revision:
        publish_state(
            context_id=snapshot.context_id,
            state=snapshot.state.value,
            revision=snapshot.revision,
        )
        last_revision = snapshot.revision

    if snapshot.finalized:
        break

    time.sleep(0.5)
```

This exposes lifecycle progress, not live execution-report records. Context and execution reports are attached at finalization.

For live telemetry, use one of these boundaries:

- Call an external logging, metrics, or tracing client from an operator or resource.
- Bind that client as a runtime-managed resource when it should be shared.
- Store live cross-context progress through `self.runtime` for supervising workflows.
- Persist finalized reports and artifact results from the application after `wait()`.

A supervising context can inspect context IDs and snapshots through {doc}`Runtime Interface <../interfaces/runtime>`. Runtime-scoped {py:class}`ValueRecord` objects support in-workflow coordination but are not exposed through the application-facing `Engine` API.

:::{warning}
Do not send mutable snapshot payloads to another thread or process under the assumption that they were copied. Serialize or copy application-owned payloads explicitly at the integration boundary.
:::

## Report API reference

Snapshot, artifact-result, artifact-record, and operational-interface methods have canonical API anchors in their owning chapters. This section defines the finalized report model.

```{py:class} ContextReport(executions)
Immutable finalized report for one executed context.

:param tuple executions: Execution reports in recording order.
```

```{py:attribute} ContextReport.executions
:type: tuple[ExecutionReport, ...]

Operator, resource, and skipped-step reports in recording order.
```

```{py:class} ExecutionReport(step_index, step_kind, step_name, layout_position, context_id, iteration, attempts, execution_count, outcome, skip_reason=None)
Immutable report for one logical step session in one context iteration.
```

```{py:attribute} ExecutionReport.step_index
:type: int

Compiled graph step index.
```

```{py:attribute} ExecutionReport.step_kind
:type: str

Step kind, such as `operator` or `resource`.
```

```{py:attribute} ExecutionReport.step_name
:type: str

Display name of the executed step.
```

```{py:attribute} ExecutionReport.layout_position
:type: tuple[int, int]

Compiled graph layout position.
```

```{py:attribute} ExecutionReport.context_id
:type: int

Owning context identifier.
```

```{py:attribute} ExecutionReport.iteration
:type: int

One-based context iteration.
```

```{py:attribute} ExecutionReport.attempts
:type: tuple[AttemptRecord, ...]

Retry attempts across all repeated executions in this session.
```

```{py:attribute} ExecutionReport.execution_count
:type: int

Number of repeated executions represented by the report; zero for a skipped step.
```

```{py:attribute} ExecutionReport.outcome
:type: ExecutionOutcome

Final session outcome.
```

```{py:attribute} ExecutionReport.skip_reason
:type: str | None

Reason for a skipped step, otherwise `None`.
```

```{py:class} AttemptRecord(execution, attempt, records)
Immutable diagnostic group for one retry attempt of one repeated execution.
```

```{py:attribute} AttemptRecord.execution
:type: int

One-based repeated execution number.
```

```{py:attribute} AttemptRecord.attempt
:type: int

One-based retry attempt number within that execution.
```

```{py:attribute} AttemptRecord.records
:type: tuple[ExecutionRecord, ...]

Diagnostic records emitted during the attempt.
```

```{py:class} ExecutionRecord(origin, execution)
Immutable base for one execution diagnostic record.
```

```{py:attribute} ExecutionRecord.origin
:type: RecordOrigin

Whether user code or Jayrun emitted the record.
```

```{py:attribute} ExecutionRecord.execution
:type: int

Repeated execution number associated with the record.
```

```{py:class} LogRecord(origin, execution, message)
Execution diagnostic containing one message.
```

```{py:attribute} LogRecord.message
:type: str

Recorded user message.
```

```{py:class} MetricRecord(origin, execution, name, value)
Execution diagnostic containing one numeric measurement.
```

```{py:attribute} MetricRecord.name
:type: str

Metric name.
```

```{py:attribute} MetricRecord.value
:type: int | float

Recorded numeric value.
```

```{py:class} TimerRecord(origin, execution, name, elapsed_time)
Execution diagnostic containing one elapsed duration.
```

```{py:attribute} TimerRecord.name
:type: str

Timer name.
```

```{py:attribute} TimerRecord.elapsed_time
:type: float

Elapsed seconds.
```

```{py:class} FailureRecord(origin, execution, exception)
Debug-mode execution diagnostic containing one failure.
```

```{py:attribute} FailureRecord.exception
:type: Exception

Recorded exception object.
```

```{py:class} RecordOrigin
Diagnostic origin enumeration containing `INTERNAL` and `USER`.
```

```{py:class} ExecutionOutcome
Execution outcome enumeration containing `FINISHED`, `FAILED`, `CANCELLED`, and `SKIPPED`.
```

:::{versionadded} 0.1.0
Context, execution, attempt, diagnostic, and artifact lifecycle reports were introduced.
:::

Recording detail is configured under {doc}`Execution Settings <../settings/execution-settings>`. Scoped operational records are documented under {doc}`Operational Interfaces <../interfaces/index>`.
