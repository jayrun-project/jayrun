# Execution, ownership and lifetime

An Engine hosts context runs. Each iteration executes the declared graph. A step session may execute an operator more than once, and each execution may need several attempts.

| Scope | Changes within it | Relevant limit |
| --- | --- | --- |
| Engine incarnation | Contexts, services, shared resources, observers | Engine capacity and history settings |
| Context | Submitted values, records, graph iterations | `max_iterations` |
| Step session | Bound resources and operator repetitions | `max_repeats` |
| Execution | One result to publish | Retry policy |
| Attempt | One invocation attempt, possibly failing | `max_attempts`, including the first |

A placement wait may restart the invocation from its beginning. Make stable placement requests before side effects. A retry also cannot undo an external write or in-place mutation performed by application code. See [failure handling](../guides/runs/failures.md).

Artifact lifetime follows flow consumption and regeneration. Exit retention is configured by `ArtifactPolicy`; it is not a promise to preserve all intermediates. `release_entry_artifacts=True` releases the framework's entry ownership and clears the submitted builder at finalization; external Python references can keep the same payload alive.

A resource can outlive the context that first acquired it. Runtime reuse and eviction are separate from artifact retention. Conversely, a `ContextRun` held by an application can keep finalized evidence and retained outputs reachable after execution stops. Bound histories and release application handles when they are no longer needed.

A lifecycle request is not finalization. Waiting without a target state waits until the run's terminal evidence and retained results are available. It does not flush persistence. See [ContextRun](../guides/runs/context-run.md) and [history storage](../guides/evidence/persistence.md).

## Compare three submissions

This is the runnable version of [the early lifetime example](../start/data-and-lifetimes.md). Adjust adds an offset from a calibration resource; Scale multiplies the adjusted artifact by its own factor. All three submissions use the same confirmed graph, with fresh input/configuration builders.

| Submission | Sample artifact | Resource offset | Operator factor | Result | Resource setup |
| --- | --- | --- | --- | --- | --- |
| First | 3 | 10 | 2 | 26 | Loads offset 10 |
| Second | 5 | 10 | 3 | 45 | Reuses the loaded offset-10 resource |
| Third | 5 | 20 | 2 | 50 | Loads the different offset-20 configuration |

The fields declare integer properties for the diagram’s compatibility checks. Those declarations do not replace runtime payload validation by your application.

Only the sample and intermediate values travel through the flows. Each run's factor is fixed for that run. The second run changes its factor without changing resource configuration, so Calibration is reused. The third requests a different Calibration configuration. That does not modify the already cached offset-10 value.

```{literalinclude} ../_examples/lifetimes.py
:language: python
```

[Download the example](../_examples/lifetimes.py). It prints `26`, `45`, then `50`. Setup emits a `calibration_loaded` context record; the assertions check that it appears in the first and third runs, but not in the second. The Engine context manager owns final cleanup.

## Inspect the first run

The embedded view below is the **first execution**, not its declaration. **Graph** shows the two operator outcomes and active durations; select the Calibration resource for its captured setup details. **Configuration** lists offset `10` and factor `2`. **Records** contains `calibration_loaded` and `result`. **Artifacts** shows the recorded lifecycle, while **Report** provides the finalized account.

```{raw} html
<iframe class="graph-viewer" data-kind="run" src="../_static/lifetimes_run.html" title="Completed calibration run: resource setup, configuration, artifact history and result 26" loading="lazy" allowfullscreen></iframe>
```

Artifact history does not imply the payload of every consumed value is retained. Run evidence also does not keep the resource loaded: its cache and placement lifetime belong to the Engine. The [completed-run guide](../guides/visualization/runs.md) explains all nine tabs and the difference between wall time, active durations and progress.
