# Read a graph visualization

For any successfully constructed GraphDefinition, save its current declaration with:

```python
graph.plot.save("graph.html")
```

You can do this before confirmation, which is useful when validation identifies a mismatch. A graph-construction exception is different: if construction never returned a graph, correct the declaration before attempting to plot it.

## Read the split-and-join graph

The [split-and-join example](../graphs/resolutions.md#complete-splitprocessjoin-graph) copies one list into two separate branch artifacts. Each branch produces a sum, and Join consumes both sums.

```{raw} html
<iframe class="graph-viewer" src="../../_static/split_join.html" title="Split a list into separate branches and join their sums" loading="lazy" allowfullscreen></iframe>
```


Operator boxes show declared input and output fields. Colored connections identify artifacts passed between them. Select **Splitter** to inspect its ports; follow each branch to **Join**. The two connections entering Join represent two distinct inputs, so they do not violate the restriction against competing producers for one active artifact.

Use **Fit** after panning or zooming. Select an entity to make its focus/details controls available. Compatibility markers describe declared properties; a check mark does not mean the operator has executed.

## Inspect a validation issue

The next graph deliberately sends a declared string output into a field requiring an integer. Open **Issues** to read the mismatch, then inspect the connected fields.

```{raw} html
<iframe class="graph-viewer" src="../../_static/plot_property_mismatch.html" title="Declared type mismatch between producer and consumer" loading="lazy" allowfullscreen></iframe>
```


Correct the producer or insert a conversion operator with accurate properties. Missing declarations can produce unknown compatibility instead of a mismatch; they do not establish a successful conversion. [Graph validation](../graphs/validation.md) includes the code used for this example.

Next: [inspect a GraphRegistry](registry.md). For outcomes after submission, move to [execution results](execution.md).
