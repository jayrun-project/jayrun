(observability-and-inspection)=
# Observability and Inspection

Jayrun exposes three complementary forms of observation:

- a live `ContextRun` for lifecycle state and context-stored values;
- terminal context, execution, and artifact reports;
- explicit external telemetry or persistence owned by application code.

## Observe a context run

`Engine.submit()` returns the object to observe:

```python
run = engine.submit(artifacts, configs)

print(run.context_id)
print(run.state.value)
print(run.iteration_count)
```

The run updates in place. `run.done` becomes true only after terminal reporting and retained artifacts are ready.

The engine also exposes currently registered work:

```python
for run in engine.contexts:
    print(run.context_id, run.state.value)
```

Terminal contexts are automatically released from this live registry. Any run already held by the application remains usable.

## Wait for changes instead of polling

```python
run.wait(ContextState.PAUSED, timeout=60)
```

or, in asynchronous code:

```python
await run.wait_async(ContextState.PAUSED, timeout=60)
```

Omit the state to wait for terminal finalization. State-specific waits accept only non-terminal states and also return if the context terminates first, so inspect `run.state` afterward.

## Publish and inspect progress

Operators store progress in their own context:

```python
self.context.store("validation_accuracy", accuracy)
```

Application code or an authorized supervisor reads it from the run:

```python
latest = run.get_value("validation_accuracy")
history = run.get_values("validation_accuracy")
record = run.get_value_record("validation_accuracy")
```

A {py:class}`jayrun.context.ValueRecord` includes the originating step, execution number, graph iteration, context ID, key, value, and timestamp. The payload is stored by reference.

Use context records for progress and lifecycle decisions. Use artifacts when a value participates in graph dependencies. Use external storage when it must survive the process.

## Context reports

After finalization, every run exposes one immutable {py:class}`jayrun.context.ContextReport`:

```python
run.wait()
report = run.report

print(report.state.value)
print(report.iteration_count)
print(report.created_at, report.finished_at)
print(report.failure)
```

The report contains:

- terminal state and stop-request information;
- lifecycle and iteration history;
- submission, validation, start, update, and finish times;
- execution reports in recording order;
- failure and failed-step information when applicable.

`run.report` raises `ContextNotTerminatedError` before finalization. Normal operator failures are represented by `run.state` and `run.report.failure`; waiting does not re-raise them.

## Execution reports

Each execution report describes one logical operator or resource session in one graph iteration:

```python
for execution in run.report.executions:
    print(
        execution.step_name,
        execution.iteration,
        execution.execution_count,
        execution.outcome.value,
    )
```

Retry attempts and operator repetitions remain grouped under the session. A skipped operator has no attempts and includes a skip reason.

User diagnostics are created through `self.execution`:

```python
self.execution.log("starting validation")
self.execution.metric("accuracy", 0.94)
self.execution.start_timer("validation")
# work
self.execution.stop_timer("validation")
```

Recording detail depends on `RuntimeMode`. Production mode favors compact reports; debug mode retains additional lifecycle and failure detail.

## Artifact results

Successful retained outputs are accessed through the run:

```python
result = run.artifact(output_model)

model = result.value
placement = result.placement
artifact_history = result.report
```

An {py:class}`jayrun.context.ArtifactResult` pairs final `Data` with artifact lifecycle records. It is distinct from the submission `ArtifactContext`.

`ArtifactPolicy` selects which successful exit payloads remain non-`None`. Cleared and non-retained artifacts still expose lifecycle results; an unknown reference or a rejected submission without artifact execution data raises `KeyError`. Failed and aborted runs do not expose successful partial output payloads.

## External telemetry

For durable monitoring, call an application-owned client from an operator or resource. Bind the client as a shared resource when it should be reused:

```python
class MetricsClient(BaseResource):
    def setup(self) -> Data:
        return Data(value=create_metrics_client())

    def teardown(self, data: Data) -> None:
        data.value.close()
```

The graph can then emit metrics without making the engine registry a durable database. The same pattern applies to logs, traces, object stores, model registries, and message brokers.

## Persisting a result through a sink

An output-free operator can make external persistence the terminal action:

```python
class SaveModel(BaseOperator):
    def __init__(self, *, model, outputs=(), **kwargs):
        super().__init__(**kwargs)
        self.model = ArtifactField(required=True)
        self.outputs = ()

    def execute(self) -> None:
        save_model(self.model.value)
```

External effects must be idempotent or transactionally protected. Retries, repetitions, placement restarts, and resubmission can invoke user code more than once; Jayrun does not promise exactly-once side effects.

## Thread and process boundaries

`ContextRun` is safe for its documented observation and control methods, but objects inside stored values and artifact results are not deep-copied or made thread-safe. Copy or serialize application payloads explicitly when crossing a thread, process, or network boundary.

See {doc}`Operational Interfaces <../interfaces/index>` for record creation and {doc}`Engine and Context Lifecycle <../runtime/engine-and-context-lifecycle>` for waiting and control.
