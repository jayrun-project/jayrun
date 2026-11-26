```{eval-rst}
.. meta::
   :description: Follow a Jayrun graph run from submission to finalization. Learn when an iteration, operator execution or retry begins, and which artifacts and resources survive.
```

(execution-ownership-and-lifetime)=
# Execution lifetime of a graph run

A graph run's execution lifetime starts with submission to an `Engine` and ends at finalization. The application can keep the `ContextRun` handle after that point to read its report and retained outputs. The engine can also reuse a compatible resource in a later run.

Within one run, a graph iteration is one pass through its steps. An operator can request another execution in the same step, and a failed invocation can have another attempt under its retry policy. Read `self.context.iteration` for the current graph pass and `self.execution.number` for the operator's execution within that step. Both start at 1.

| Scope | Changes within it | Relevant limit |
| --- | --- | --- |
| Engine incarnation | Contexts, services, shared resources, observers | Engine capacity and history settings |
| Context | Submitted values, native execution history, application records, retained exits | `execution_history_limit` for native history, `record_policy.history_per_key` per application key |
| Graph iteration | One pass through the graph, including the steps eligible to run | `max_iterations` counts passes that start |
| Step session | Bound resources and operator repetitions | `max_repeats` |
| Execution | One result to publish | Retry policy |
| Attempt | One invocation attempt, possibly failing | `max_attempts`, including the first |

A placement wait may restart the invocation from its beginning. Make stable placement requests before side effects. A retry also cannot undo an external write or in-place mutation performed by application code. See [failure handling](../guides/runs/failures.md).

After a successful `submit()`, Jayrun removes the entry bindings from the caller's `ArtifactContext`. Refill the builder or make a fresh one for the next run. The run holds its own sealed artifact context. With the default policy, you can still read its submitted entries through `run.artifact_context` after finalization. With `release_entry_artifacts=True`, Jayrun releases its entry references as execution permits and clears any remaining submitted entries and recovery checkpoint at finalization.

`ArtifactPolicy.retained_artifacts` separately selects the exit values available through `run.artifact(...)`. An application that still holds the input or output object keeps its own reference.

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
