# Inspect a graph and print its report

Use inspection when application code needs graph metadata; use a textual report when a person needs to read it. Neither runs the graph.

With the graph from the [guided workflow](../../start/first-graph.md):

```python
for artifact in graph.inspect.artifacts.all:
    print(artifact.artifact_id, artifact.name, artifact.is_exit)

print(graph.report.format(compact=True))
graph.report.save("graph-report.txt")
```

The inspected artifacts include `source` and `result`. `result` is an exit because its final value has no consumer. Their numeric IDs are local to this graph; use the declarations as submission keys unless you are building a generic tool.

The full report adds component field declarations and contracts. The compact report keeps the structure, bindings and validation findings while reducing field detail. `graph.report.print()` writes directly to standard output.

## Find required values and missing resources

After confirmation, `graph.inspect.configs.required` lists required configurations. Before confirmation, `graph.inspect.resources.missing` identifies required resource fields without bindings. `graph.inspect.resources.shared` groups fields bound to the same resource declaration; runtime reuse also depends on effective configuration.

For example, a generic submission form can show a configuration field's `attribute_name`, `value_type` and `default`. Keep the inspected definition itself as the key rather than attempting to recreate identity from its display name.

## Inspect validation separately

```python
validation = graph.validate()
for edge in validation.mismatched_edges:
    print(edge.edge_id, edge.validation)
```

A mismatch describes a known incompatibility between declared producer and consumer properties. `unknown_edges` contains relationships where available declarations do not establish compatibility. Read [validation](../graphs/validation.md) for an executable mismatch example and its correction.

Next: [visualize a declaration](graphs.md). Full returned types: [inspection reference](../../reference/inspection.md).
