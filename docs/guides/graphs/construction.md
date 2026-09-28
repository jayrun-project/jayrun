# Build and confirm a graph

Create artifacts and component declarations, order consumers with `ArtifactFlow`, then prepare a `GraphDefinition`. Use [graph-definition resolutions](resolutions.md) when the intended shape is rejected.

```{literalinclude} ../../_examples/first_graph.py
:language: python
:pyobject: build_graph
```

`entry_flows` identifies flows initialized by submission values. Other consumed artifacts need a producer origin. A produced exit need not have a consumer flow. Each artifact has one flow definition; place its ordered consumers in that flow rather than duplicating the flow for another consumer.

## Input-free and artifact-free work

An input-free producer may head a flow for the artifact it produces. A single operator with no artifact inputs can also stand alone as `ArtifactFlow(operator)`. This is useful for a Controller or a terminal side effect. Do not put an artifact-free flow in `entry_flows`.

The [Controller example](../runtime/controller.md) contains an artifact-free service graph and an input-free producer graph. They do not need a dummy input.

## Preparation order

1. Construct the graph. Structural contradictions can fail here, before a graph object is returned.
2. Bind resources with `graph.bind_resources(mapping)` when needed.
3. Bind any artifact boundary serializers with `graph.bind_serializers(mapping)` and select timing configuration with `graph.select_timing_configs(...)`.
4. Inspect or validate declared properties. `graph.validate()` returns a report without executing code.
5. Call `graph.confirm()` explicitly. Confirmation checks the prepared declaration and seals the graph, including serializer bindings.
6. Optionally register the confirmed graph. Submit fresh input/configuration builders for each run.

For an ordinary local graph without resources or serializers, construction → validation → confirmation is sufficient. A serializer cannot be added after confirmation; prepare the complete boundary first.

Confirmed declarations are reusable. Avoid changing component metadata or configuration defaults after construction. Per-run values belong in builders and settings. Repeated graph occurrences, execution repeats and graph iterations are different tools; see [repeat and iterate](../runs/iteration.md).

Reference: [GraphDefinition and GraphRegistry](../../reference/graphs.md).
