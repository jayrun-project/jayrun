# Read a completed-run visualization

Wait for a ContextRun to finalize, check its outcome, then save its captured execution:

```python
run.wait(timeout=10)
print(run.state.value)
run.plot.save("run.html")
```

A failed or aborted run can also provide useful execution evidence. Saving its plot does not change its outcome.

## Inspect the run workspace

The saved page opens on **Graph**, with the context outcome, iteration counts and
elapsed wall time above it. It uses the same graph viewer, tab renderers and
Light/Dark control as the [dashboard](dashboard.md). The control changes the
whole visualization page, including its header, panels and canvas.

| Tab | Use it to inspect |
| --- | --- |
| Graph | Recorded step outcomes and active durations for the selected iteration; select an operator, resource or artifact for its detail. |
| Summary | Context and graph identities, retained-evidence coverage and records pinned from Records. |
| Failure | The captured failure and failed step, when recorded. |
| Configuration | Captured component configuration values and their provenance. |
| Settings | Requested and effective execution settings. |
| Records | Retained keys and values, numeric charts, filters and exports. |
| Artifacts | Retained availability and lifecycle history. |
| Report | The finalized text report, including sessions and attempts, with an export action. |
| Activity | Retained lifecycle events in recorded order. |

Switching tabs preserves the graph selection and selected iteration. A saved
page is read-only evidence: it does not connect to an Engine or offer execution
controls. Missing or pruned evidence stays identified as unavailable.

## Follow a conditional execution

The [conditional declaration](../graphs/resolutions.md#conditional-routing-and-convergence) contains two possible routes. The captured run below chose the left route. Route and the left Consume step finished; the right Consume step was skipped because its connected input received None.

```{raw} html
<iframe class="graph-viewer" data-kind="run" src="../../_static/conditional_run.html" title="The left route ran and the right route was skipped" loading="lazy" allowfullscreen></iframe>
```


The graph structure still contains both declared routes. The run view adds what happened during this execution. Select the skipped step and inspect its available detail. Use the report's `skip_reason` when diagnosing absence; a gray or missing payload preview alone is not enough to infer why a step did not run.

The field compatibility markers still describe declarations. They answer a different question from the FINISHED/SKIPPED labels. Similarly, an artifact may have been produced successfully but no longer retain its payload under the chosen policy.

## Read time and progress carefully

A saved view contains the evidence retained when it was built. It does not
continue observing the Engine. The header's elapsed wall time runs from
submission to the terminal state and excludes later cleanup. A terminal progress
fraction of 1 means the run ended; read its outcome to distinguish success,
failure and cancellation.

Graph bars compare recorded **active session durations** within the selected
iteration. They are neither completion percentages nor a timeline. Active time
can differ from wall time. Short durations display in milliseconds or
microseconds. Select another iteration to inspect its recorded outcomes and
durations; final progress is not applied retrospectively to earlier iterations.

The live dashboard can also show learned estimates. Measured time and estimates
have different meanings; an unavailable estimate remains unavailable. The
[progress guide](../evidence/progress.md) explains those fields.

The [conditional-routing example](../graphs/resolutions.md#conditional-routing-and-convergence) runs both branch choices. For a continuously updating view, use the [dashboard](dashboard.md).
