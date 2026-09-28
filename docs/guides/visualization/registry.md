# Visualize a registry

A registry view is useful when an application hosts several graphs and you want to compare their declarations without running them.

```python
from jayrun import GraphRegistry

# graph_a and graph_b are confirmed GraphDefinitions.
registry = GraphRegistry()
registry.register("preprocess", graph_a)
registry.register("predict", graph_b)
registry.plot.save("registered-graphs.html")
```

The exported viewer contains a selector for the registered graph definitions. Choose a graph to inspect its operators, fields and bindings. The file includes the graphs present when saved; later registrations do not update an already-open export.

## Browse two registered graphs

This registry contains the **scale** graph from the [first workflow](../../start/first-graph.md) and the **split-and-join** graph from [graph-definition resolutions](../graphs/resolutions.md#complete-splitprocessjoin-graph). Both are confirmed declarations; generating this view does not execute either graph.

```{raw} html
<iframe class="graph-viewer" src="../../_static/registry.html" title="GraphRegistry containing scale and split-and-join declarations" loading="lazy" allowfullscreen></iframe>
```

Use the graph selector to switch between **scale** and **split-and-join**. The latter reveals Splitter, both branches and Join. Select an operator to inspect its fields, use **Fit** to restore the view, and try **Light** or **Dark** to change the whole viewer's theme. These are declaration views; completed-run timings belong to the [execution visualization](runs.md).

To reproduce this registry, run the following alongside `first_graph.py` and `split_join.py` from `docs/_examples`:

```python
from jayrun import GraphRegistry
from first_graph import build_graph as build_scale
from split_join import build_graph as build_split_join

registry = GraphRegistry()
registry.register("scale", build_scale()[0])
registry.register("split-and-join", build_split_join()[0])
registry.plot.save("registered-graphs.html")
```

## Inspect sharing and requirements

`registry.inspect.resources` exposes shared resource bindings across graphs. `registry.inspect.conflicts` lists conflicting package requirements; `registry.report.format()` combines the registry overview with the graph reports. A shared binding means the same resource declaration is used; actual runtime reuse still depends on its configuration and managed lifetime.

Registry identity combines your key with `graph.version`. It lets application tools choose a graph without relying on its display name. [Registration and serializers](../graphs/registration.md) explains that identity and preparation order.

Next: [execution results and reports](execution.md), or [export and notebook display](exports.md) when you only need to share a declaration. Full signatures: [GraphRegistry reference](../../reference/graphs.md).
