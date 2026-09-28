# Inspect execution results and reports

Submission returns a ContextRun. While it runs, use its state/progress or a dashboard. After finalization, check the outcome and read its reports, retained artifacts and completed-run visualization. Waiting for finalization does not itself assert success.

```python
run.wait(timeout=10)
print(run.state.value)
print(run.report.format())
run.report.save("run-report.txt")
run.plot.save("run.html")
```

Use the graph and submitted run from the [guided workflow](../../start/first-graph.md). A failed or aborted run can still contain useful evidence. The text report and saved visualization present the same run in different forms; neither is a graph-definition validation result.

```{toctree}
:maxdepth: 1

../evidence/reports
runs
dashboard
```

For a worked example with resources and configuration, inspect the inline [calibration run](../../model/lifetime.md#inspect-the-first-run). For a branch that did not execute, use the inline [conditional run](runs.md#follow-a-conditional-execution).

The saved run and dashboard share the Graph, Summary, Failure, Configuration, Settings, Records, Artifacts, Report and Activity panels. A saved file is read-only; the dashboard observes ongoing work and offers only the controls permitted by its authority. [Exporting views](exports.md) explains how to share the captured result.
