# Read reports and artifact history

After a run finalizes, `run.report.data` exposes structured context evidence. `run.report` supplies formatting/reporting helpers. Check state and failure before reading retained values; waiting alone does not establish success.

Useful questions are: which step ran, skipped or failed; which attempt produced the result; whether Stop was requested; and whether an artifact was registered, cleared or retained. Execution, attempt, lifecycle and artifact records answer different parts of those questions.

`run.artifact(reference)` returns an `ArtifactResult` when artifact reporting is available. A value can be `None` because a route was absent or because policy released the payload. The default recording mode keeps only the latest lifecycle record per artifact. To trace the sequence of updates and clears, choose `RecordingMode.DIAGNOSTIC` before starting the Engine.

## Print or save the report

```python
run.wait(timeout=10)
print(run.state.value)
print(run.report.format())
run.report.save("run-report.txt")
```

Use `run.report.data` when application code needs structured fields rather than text. The saved run visualization provides the same formatted report in its **Report** tab. These operations read the execution result; they do not validate the graph declaration.

## Walk from a report to an execution record

Follow `run.report.data.executions` to a step, then read `step.attempts` and each `attempt.records`. A step report identifies its outcome even when an attempt has no optional records. Read explicit application values separately through `run.records(key)`.

This complete program records a sum and prints the step outcome and diagnostic record types:

```{literalinclude} ../../_examples/diagnostics.py
:language: python
```

With the default `Engine()`, the example prints three lines.

```text
Sum finished None
LogRecord
MetricRecord
```

`None` is the step's skip reason. The `total` application record contains `6`. To see a `TimerRecord` for the named `sum` timer, pass `EngineSettings(recording_mode=RecordingMode.DIAGNOSTIC)` to `Engine`. Both settings types are available from `jayrun.settings`. The observer in the example captures [context events](progress.md).

## Recording modes

| Evidence in a local run | `STANDARD` (default) | `DIAGNOSTIC` | `MINIMAL` |
| --- | --- | --- | --- |
| Execution logs and numeric metrics | Recorded | Recorded | Omitted |
| Named timers | Omitted | Recorded | Omitted |
| Per-attempt `FailureRecord` on failure | Omitted | Recorded | Recorded |
| Artifact lifecycle | Latest record per artifact | Retained sequence | Latest record per artifact |

All three modes preserve step outcomes, attempt counts and explicit context records. Inspect `run.report.data.failure` when a run fails. Timers measure named intervals, while a step report also carries its overall duration.

`ContextHistoryEntry` in `jayrun.context` describes lifecycle history; the identically named persistence type describes a stored context entry. Alias the types when using both. A report actor/origin describes who initiated an operation; it is not a transferable authorization token.

For an interactive account, open the inline [completed conditional run](../visualization/runs.md#follow-a-conditional-execution). Its **Report** tab presents the formatted report, **Artifacts** presents retained availability/history, and **Failure** presents captured failure details. The [calibration run](../../model/lifetime.md#inspect-the-first-run) also shows resource setup and configuration alongside artifact flow.

See [reference](../../reference/records.md), [progress and events](progress.md) and [history persistence](persistence.md).
