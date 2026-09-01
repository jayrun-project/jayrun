# Jayrun

Jayrun is an artifact-centric execution framework for computational graphs that need iteration, shared resources, hardware placement, supervision, and reliable lifecycle management.

Artifacts make data flow explicit. Operators transform artifacts or terminate a flow with an external side effect, while Jayrun coordinates concurrent execution, automatic clearing and retention, reusable resources, placement capacity, failure containment, and shutdown.

## Start here

Follow the documentation in this order:

1. {doc}`Introduction <introduction>` — decide whether Jayrun fits your workload.
2. {doc}`Getting Started <getting-started>` — build and execute one complete graph.
3. {doc}`Scope and Lifetime Model <concepts/scope-and-lifetime>` — understand declaration, runtime, context, and execution ownership.
4. {doc}`Data Model <concepts/data-model>` — distinguish declarations, graph-local definitions, IDs, and runtime values.
5. {doc}`Data <concepts/data>` — understand the common runtime value container.
6. {doc}`Artifacts and Data Flow <concepts/artifacts-and-data-flow>` — declare flowing data and manage artifact lifetime.
7. {doc}`Configuration <concepts/configuration>` — provide graph-scoped computational values.
8. {doc}`Resources <concepts/resources>` — declare and share runtime-managed data and capabilities.
9. {doc}`Operators and Executions <components/operators-and-executions>` — define reusable transformations and terminal side-effect operators, then understand invocation behavior.
10. {doc}`Graph Construction <components/graph-construction>` — combine flows, derive layout, express routing patterns, bind resources, inspect declarations, and understand compilation.
11. {doc}`Graph Validation <components/graph-validation>` — validate artifact contracts and interpret text, programmatic, and plotted diagnostics.
12. {doc}`Operational Interfaces <interfaces/index>` — use execution, context, runtime, and capacity capabilities safely from components.
13. {doc}`Placement and Capacity <runtime/placement-and-capacity>` — understand device leases, contention, and admission.
14. {doc}`Engine and Context Lifecycle <runtime/engine-and-context-lifecycle>` — submit, wait for, control, and inspect context runs safely.
15. {doc}`Execution Settings <settings/execution-settings>` — distinguish engine-wide policy from per-context policy and understand override rules.
16. {doc}`Failure and Reliability Model <reliability/failure-and-reliability>` — understand failure containment, escalation, rollback, and cleanup guarantees.
17. {doc}`Observability and Inspection <observability/observability-and-inspection>` — interpret context runs, reports, diagnostics, and external telemetry boundaries.

After the conceptual path, use the task-oriented tutorials:

- {doc}`Build and Validate a Graph <tutorials/build-and-validate-graph>`
- {doc}`Denoise Images with FastAPI <tutorials/denoise-images-with-fastapi>`
- {doc}`Run MNIST Inference and Supervised Training on CUDA <tutorials/mnist-inference-and-training>`

Use the {doc}`API Reference <reference/api>` for object-level lookup and {doc}`Troubleshooting <troubleshooting>` for operational diagnostics.

```{toctree}
:hidden:
:caption: Start Here
:maxdepth: 1

introduction
getting-started
```

```{toctree}
:hidden:
:caption: Core Concepts
:maxdepth: 1

concepts/scope-and-lifetime
```

```{toctree}
:hidden:
:caption: Data Model
:maxdepth: 1

concepts/data-model
concepts/data
concepts/artifacts-and-data-flow
concepts/configuration
concepts/resources
```

```{toctree}
:hidden:
:caption: Components
:maxdepth: 1

components/operators-and-executions
components/graph-construction
components/graph-validation
```

```{toctree}
:hidden:
:caption: Operational Interfaces
:maxdepth: 1

interfaces/index
interfaces/execution
interfaces/context
interfaces/runtime
interfaces/placement
```

```{toctree}
:hidden:
:caption: Capacity Management
:maxdepth: 1

runtime/placement-and-capacity
```

```{toctree}
:hidden:
:caption: Runtime Management
:maxdepth: 1

runtime/engine-and-context-lifecycle
settings/execution-settings
```

```{toctree}
:hidden:
:caption: Reliability
:maxdepth: 1

reliability/failure-and-reliability
```

```{toctree}
:hidden:
:caption: Observability
:maxdepth: 1

observability/observability-and-inspection
```

```{toctree}
:hidden:
:caption: Tutorials
:maxdepth: 1

tutorials/build-and-validate-graph
tutorials/denoise-images-with-fastapi
tutorials/mnist-inference-and-training
```

```{toctree}
:hidden:
:caption: Reference
:maxdepth: 1

reference/api
troubleshooting
```

## Installation

```bash
python -m pip install jayrun
```

Jayrun requires Python 3.11 or later.
