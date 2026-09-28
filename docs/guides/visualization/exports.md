# Export views and use notebooks

A definition, registry or completed-run export is a standalone HTML file containing its viewer assets and captured data. You can send that file to another reader or embed it in a page without running an Engine on their computer.

## Save or open a definition

```python
graph.plot.save("graph.html")  # Write a file.
graph.plot.show()              # Open the definition using its viewer helper.
```

In a notebook, the graph definition plotter can return an inline iframe:

```python
graph.plot.show(notebook=True)
```

The notebook option belongs to the definition GraphPlotter. For a completed run or registry, save its HTML and display that saved file using your notebook's HTML/iframe display tools. Check paths relative to the notebook server's working directory.

## Embed an export in a web page

The manual uses the same standalone viewer inside an iframe:

```html
<iframe src="graph.html" title="Processing graph"
        style="width:100%; height:760px; border:1px solid #ddd"
        loading="lazy" allowfullscreen></iframe>
```

The graph remains interactive within the surrounding explanation. Give each embedded view a descriptive title and enough height for its controls and graph. On a small screen, use Fit and then zoom into the portion being inspected.

For a custom web application, `graph.plot.build()` returns viewer data and `jayrun.visualization.render_html()` renders a portable payload. More direct embedding through the `jayrun-graph` element is described by [GraphPlotter](../../reference/inspection.md); it requires loading the viewer script, rather than merely assigning a script-containing HTML fragment to innerHTML.

## What the export contains

Inspect the data and metadata before sharing a file outside your application. A run export may contain retained diagnostic information. Regenerate the file for a later state; saved HTML does not poll a live runtime.

For ongoing observation instead of a saved snapshot, [run a live dashboard](dashboard.md). Full rendering options: [visualization reference](../../reference/visualization.md).
