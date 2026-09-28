# Read reports and artifact history

After a run finalizes, `run.report.data` exposes structured context evidence. `run.report` supplies formatting/reporting helpers. Check state and failure before reading retained values; waiting alone does not establish success.

Useful questions are: which step ran, skipped or failed; which attempt produced the result; whether Stop was requested; and whether an artifact was registered, cleared or retained. Execution, attempt, lifecycle and artifact records answer different parts of those questions.

`run.artifact(reference)` returns an `ArtifactResult` with value and history. A value can be `None` because a route was absent or because policy released it; history and retained-policy information distinguish those situations. An exit selected for retention differs from an intermediate already consumed.

## Print or save the report

```python
run.wait(timeout=10)
print(run.state.value)
print(run.report.format())
run.report.save("run-report.txt")
```

Use `run.report.data` when application code needs structured fields rather than text. The saved run visualization provides the same formatted report in its **Report** tab. These operations read the execution result; they do not validate the graph declaration.

## Walk from a report to an execution record

The hierarchy is `run.report.data` → `executions` → `attempts` → `records`. Each execution report names a graph step and its outcome; each attempt contains its logs, metrics, timers and failure records. An explicit context record is read separately through `run.records(key)`.

This complete program records a sum and prints the step outcome and diagnostic record types:

```{literalinclude} ../../_examples/diagnostics.py
:language: python
```

Look for the `Sum` step with outcome `finished`, followed by LogRecord, TimerRecord and MetricRecord entries. Framework timing records may also appear. The application record `total` contains `6`. The observer is created before submission and closed before its remaining queued events are drained; [events](progress.md) explains that separate view.

## Recording modes

`RecordingMode.STANDARD` is the default. `DIAGNOSTIC` requests richer optional evidence and `MINIMAL` reduces optional recording. These modes do not remove mandatory lifecycle ownership or turn missing optional data into a zero-valued fact. Explicit context records have their own bounds and meaning.

`ContextHistoryEntry` in `jayrun.context` describes lifecycle history; the identically named persistence type describes a stored context entry. Alias the types when using both. A report actor/origin describes who initiated an operation; it is not a transferable authorization token.

For an interactive account, open the inline [completed conditional run](../visualization/runs.md#follow-a-conditional-execution). Its **Report** tab presents the formatted report, **Artifacts** presents retained availability/history, and **Failure** presents captured failure details. The [calibration run](../../model/lifetime.md#inspect-the-first-run) also shows resource setup and configuration alongside artifact flow.

See [reference](../../reference/records.md), [progress and events](progress.md) and [history persistence](persistence.md).
