# Artifacts, configuration and resource lifetimes

A graph describes a computation once. Each submission supplies values and creates a run. Three kinds of state support that execution: values that flow through artifacts, configuration that stays fixed for the run, and resources managed for reuse by the Engine.

## Three roles, three lifetimes

| Kind | Example | During execution | After a run ends |
| --- | --- | --- | --- |
| Artifact value | An input sample, intermediate array or final prediction | Operators consume values and publish outputs along declared flows | Selected exits can remain available through the run; intermediates are not automatically retained |
| Configuration | A scale factor or the identifier of a model to load | Operators and resources read the submitted value or declared default; the accepted configuration stays fixed | A later submission can choose other values for the same fields |
| Resource | A prepared model, calibration table or client | Setup produces a managed value that compatible executions can acquire | The Engine can keep it for later runs; unloading or shutdown calls teardown |

An **Artifact** is the reusable identity of a data position, not the value itself. An **ArtifactField**, **ConfigField** or **ResourceField** declares what a component needs. At execution, Jayrun supplies those values through `Data` wrappers; the hook reads their `.value`. The [first program](first-graph.md) introduces artifact and configuration bindings in code; [resource authoring](../guides/graphs/resources.md) adds the resource binding.

## Follow one sample

Consider a two-step calculation. **Adjust** reads a sample and adds an offset from a calibration resource. **Scale** multiplies the adjusted value by a configured factor. For sample `3`, offset `10` and factor `2`, the result is `26`.

```{raw} html
<iframe class="graph-viewer" src="../_static/lifetimes_graph.html" title="Declaration: sample flows through Adjust and Scale, with a calibration resource" loading="lazy" allowfullscreen></iframe>
```

Follow the artifact connections from sample to adjusted value to result. Select **Adjust** to inspect its resource binding, and **Scale** to inspect its factor field. This diagram shows the declaration; it contains no run timings or outcomes.

The values follow `3 → 13 → 26`. Adjust consumes the sample and publishes a different artifact for Scale. Scale consumes that intermediate and publishes the result. To let independent consumers use the same source, introduce a [splitter with distinct outputs](../guides/graphs/resolutions.md#fan-out-split-into-distinct-artifacts). To continue using one artifact in sequence, an operator can consume and regenerate it.

A connected input whose value is `None` skips its consumer. That is how a declared branch can be inactive during one run. `0`, `False` and empty containers are still present values. [Conditional routing](../guides/graphs/resolutions.md#conditional-routing-and-convergence) shows the full behavior.

## Configuration does not travel along the artifact flow

Scale reads its factor each time it executes; consuming an artifact does not consume the factor. The submitted configuration remains the same across that run's repeats and graph iterations. Another submission can use factor `3` without rebuilding the graph or altering the earlier run. Resource setup also reads declared configuration: here, the calibration offset is a resource configuration field.

Submission creates a separate, sealed configuration view. Editing a caller's builder afterward does not change accepted work. Put evolving computation state in artifacts, and use application storage for durable checkpoints.

[Execution settings](../guides/runs/settings.md) are a fourth, separate concern: they tell Jayrun how to manage work, such as iteration limits and retries. They are not fields that Scale reads as part of its calculation.

## Resources are acquired, reused and eventually unloaded

The first execution needing Calibration calls its `setup()` and acquires the returned value. Releasing that acquisition does not normally unload the cached resource. A later run with compatible resource configuration can reuse it, even if that run supplies a different sample or Scale factor. Changing Calibration's own offset selects a different resource configuration.

Reuse depends on resource type, effective configuration and sharing policy. A reusable value must be safe for the concurrency its bindings permit; `parallel_safe=True` does not add locking.

A placed resource can keep its capacity reservation while cached. When other work needs that capacity, the runtime may unload an idle, unpinned resource and call `teardown(data)`. A future acquisition may then need setup again. Engine shutdown also cleans up managed resources after their users drain. See [resource authoring](../guides/graphs/resources.md) for cleanup and [placement](../guides/components/placement.md) for capacity ownership.

## What a completed run keeps

The graph declaration can serve the next submission. The completed run keeps its outcome, retained evidence and the artifact results selected by policy. Those results are separate from the Engine's resource cache. Keeping an application reference to a payload can keep that Python object alive even after Jayrun releases its own reference.

Continue with [installation](installation.md) and the [complete first program](first-graph.md). Later, [the runnable lifetime example](../model/lifetime.md#compare-three-submissions) demonstrates these distinctions and shows an actual completed run.
