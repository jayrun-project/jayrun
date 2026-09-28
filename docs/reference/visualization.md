# Plotting and dashboard helpers

Use graph.plot, run.plot and registry.plot facades for common saves. [Visualization and reporting](../guides/evidence/plots.md) shows current HTML examples and explicit dashboard submission. A prepared graph is not an already-running service.

```{eval-rst}
.. autofunction:: jayrun.visualization.validate_payload
```

```{eval-rst}
.. autofunction:: jayrun.visualization.render_html
```

```{eval-rst}
.. autofunction:: jayrun.visualization.save
```

```{eval-rst}
.. autofunction:: jayrun.visualization.show
```

```{eval-rst}
.. autofunction:: jayrun.visualization.viewer_script
```

```{eval-rst}
.. autoclass:: jayrun.dashboard.DashboardSubmission
   :members:
```

```{eval-rst}
.. autofunction:: jayrun.dashboard.dashboard_graph
```

```{eval-rst}
.. autofunction:: jayrun.dashboard.prepare_dashboard
```

## Plot facade

```{py:class} Plot

Obtain this facade through `graph.plot`, `registry.plot` or `run.plot`; it is not an application import/constructor.
```

```{py:method} Plot.build()

Return a fresh portable visualization snapshot.
```

```{py:method} Plot.to_html()

Render the snapshot as a standalone HTML string with bundled viewer assets.
```

```{py:method} Plot.save(path)

Write standalone HTML to a path and return that path.
```

```{py:method} Plot.show()

Save/open a view using the current rendering environment and return its path.
```

[Plot facade source](https://github.com/jayrun-project/jayrun/blob/main/jayrun/visualization/_facade.py).
