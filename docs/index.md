```{eval-rst}
.. meta::
   :google-site-verification: julLJhIROJAKIjHCJgjEUqCs0_UsFPXVik8WIhs6bHU
```

# Jayrun

Jayrun lets you describe a computation through the data it consumes and produces. You define its operators and artifact flows; an Engine runs the graph and gives you a handle for its results, progress and lifecycle.

Start with [what Jayrun does](start/overview.md) and [artifacts, configuration and resource lifetimes](start/data-and-lifetimes.md). Then [install Jayrun](start/installation.md) and follow [from artifacts to a completed run](start/first-graph.md). That guided example develops one program from declarations through validation, submission and results. Continue with the chapters below for the full model and practical usage.

## Reading path

1. [Getting started](start/index.md) — the data model, lifetimes, setup and a complete first program.
2. [From declaration to execution](guides/workflow/index.md) — artifacts, components, flows, validation, submission and ContextRun.
3. [Component interfaces](guides/components/index.md) — use the handles supplied to operators and resources, including self.runtime.
4. [Visualization and reporting](guides/evidence/plots.md) — inspect declarations, then read execution results and observe work in the dashboard.
5. [Records, observation and persistence](guides/evidence/index.md) — publish values, observe changes and persist execution history with `Engine(database=...)`.
6. [Application integration](guides/integration/index.md) — registration, serialization, services, remote work and checkpoints.
7. [Tutorials](tutorials/index.md) — complete application examples.
8. [Troubleshooting](guides/problems/index.md) — symptoms, causes and corrections.
9. [Reference](reference/index.md) — exact APIs, defaults and supported behavior.

For a specific task, go directly to [graph-definition resolutions](guides/graphs/resolutions.md), [execution settings](guides/runs/settings.md), or [Engine/runtime correspondence](guides/runtime/correspondence.md). Configuration and execution settings have separate guides; Engine and injected interfaces have separate references.

[Public source repository](https://github.com/jayrun-project/jayrun) · [Report an issue](https://github.com/jayrun-project/jayrun/issues)

```{toctree}
:hidden:
:maxdepth: 4

start/index
guides/workflow/index
guides/components/index
guides/evidence/plots
guides/evidence/index
guides/integration/index
tutorials/index
guides/problems/index
reference/index
```
