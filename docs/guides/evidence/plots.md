# Visualization and reporting

Start with the object you want to understand. A GraphDefinition or GraphRegistry describes computation that can be run. A ContextRun describes one submitted execution and its results. The dashboard observes executing work and any history the application grants it.

| Object | Inspect in code | Read or visualize | Question it answers |
| --- | --- | --- | --- |
| GraphDefinition | `graph.inspect`, `graph.validate()` | `graph.report`, `graph.plot` | What is declared, and are its declared properties compatible? |
| GraphRegistry | `registry.inspect` | `registry.report`, `registry.plot` | Which declarations are registered, and what do they share? |
| Finalized ContextRun | `run.state`, `run.artifact(...)`, `run.report.data` | `run.report`, `run.plot` | What happened in this execution, and which results remain? |
| Live application | Engine or authorized runtime observations | Explicitly submitted dashboard | What is running now, and what captured history is available? |

## Declaration

Inspect graph fields and validation findings, print definition reports, and browse registered graphs. These views need no execution. A compatibility marker says something about declared properties, not whether an operator ran.

```{toctree}
:maxdepth: 1

../visualization/declarations
```

## Execution results

After submission, use the ContextRun's state and retained evidence. Read its report, inspect its saved run workspace, or use the dashboard for live work. Completed, skipped and failed outcomes belong here; they do not change the reusable declaration.

```{toctree}
:maxdepth: 1

../visualization/execution
```

## Share a view

The examples throughout this chapter are embedded interactive viewers. Use **Fit** to center the graph, select an operator or artifact for detail, and switch Light/Dark for the whole viewer. The surrounding text explains the result without requiring every control to be used.

```{toctree}
:maxdepth: 1

../visualization/exports
```

Saved files contain captured data and do not poll an Engine. Regenerate an export for a later snapshot; use the dashboard for ongoing observation. Continue with [records, observation and persistence](index.md) to choose what your application records and retains. Exact methods live in the [inspection](../../reference/inspection.md), [reports](../../reference/records.md) and [visualization](../../reference/visualization.md) references.
