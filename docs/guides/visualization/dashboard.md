```{eval-rst}
.. meta::
   :description: Observe Jayrun execution in the live dashboard. Inspect runs, artifacts, records and reports, and understand the scope of lifecycle controls.
```

# Run a live dashboard

Use the dashboard when you want an application service that observes running work. Unlike saving a graph plot, preparing a dashboard does not immediately start a listener. The application explicitly submits its graph with Controller authority.

```python
from jayrun import Controller, Engine
from jayrun.dashboard import prepare_dashboard

prepared = prepare_dashboard(host="127.0.0.1", port=8765)
with Engine() as engine:
    dashboard = engine.submit(prepared.graph, authority=Controller())
    input("Open http://127.0.0.1:8765, then press Enter to close. ")
```

The Engine remains alive while the input prompt waits. Submit your application's work to that same Engine to see it in the dashboard. On exit, graceful shutdown lets ordinary work drain and then ends the dashboard's Controller service. In async applications, use the [async lifecycle](../runs/async.md) instead of blocking input.

The listener may take a moment to start. Its actual URL is recorded under `dashboard_url` on the dashboard ContextRun, which is useful with `port=0` to select an available port. If your Engine has a GraphRegistry, register `prepared.graph` before submitting it.

## Read a run in the dashboard

Select a context to open its execution workspace. The **Graph**, **Summary**, **Failure**, **Configuration**, **Settings**, **Records**, **Artifacts**, **Report** and **Activity** panels share their presentation with [saved completed runs](runs.md). Use Records to chart a retained numeric value or pin it to Summary; use Report for the formatted execution account.

The preview below shows a completed two-iteration run in the dashboard. Explore the captured Overview, Engines, Contexts, Graphs and History pages using the sidebar. In Contexts, choose **Open captured run** to browse all nine run tabs, including its graph, summary, records and report. The preview does not update. Its sidebar and run tabs are interactive; other controls, including filters and the theme switch, are disabled. History shows the availability captured from this example session. Start the dashboard above to observe and control your own runs.

```{raw} html
<iframe class="graph-viewer" data-kind="dashboard" src="../../_static/dashboard_preview.html" title="Static dashboard preview showing a completed run and its execution timings" loading="lazy"></iframe>
```

The running dashboard continues observing live work. A saved run is a fixed, read-only snapshot. **Graphs** in the dashboard browses captured declarations; selecting a definition does not select an execution result. Use the context workspace for outcomes, timing and run reports.

In the running dashboard, the Light/Dark control changes the whole page, including the graph and panels. Missing capture or history remains visibly unavailable.

## Grant historical access explicitly

An Engine with persistence does not automatically grant its dashboard access to every stored session. Create a reader with the desired session scope and submit with `Controller(history=reader)`. [Runtime history](../runtime/history.md) explains the reader's lifetime and permissions.

Live runs can be controlled under the dashboard's authority. Historical rows are read-only evidence, even when they contain a familiar context ID. A plot can be unavailable if its layout or detail was not captured; the stored ID alone cannot recreate it.

## Hosting

The host and port identify this listener, not a remote Engine. The dashboard observes the runtime executing it. Keep loopback hosting for a local application; provide application authentication and disclosure policy before exposing it remotely. Application transport must explicitly supply any remote observations.

Exact options: [dashboard reference](../../reference/visualization.md).
