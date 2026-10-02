```{eval-rst}
.. meta::
   :description: Explore Jayrun’s Python workflow model: explicit artifact flow, reusable resources, iterative execution, lifecycle control and graph-based supervision.
```

# What Jayrun does

Jayrun is a Python execution framework for computations with explicit data flow, repeated work and reusable resources. You describe what operators consume and produce, then an Engine manages their execution and lifetime. The same graph model can describe both application work and the services that observe or coordinate it.

Use it for workloads such as inference services, iterative training, document pipelines and scientific campaigns. Its main capabilities work together: artifact flow identifies when data is needed, resources keep expensive setup reusable, and graph-based controllers let applications supply their own operating policies.

Explore the [Jayrun source on GitHub](https://github.com/jayrun-project/jayrun) for the framework code and runnable tutorials.

## Release intermediate data as work progresses

An artifact identifies a position in the data flow; each run supplies or produces its actual value. Jayrun releases its references to consumed values when the execution rules no longer require them, and clears invocation bindings after use. A pipeline therefore does not need to retain every intermediate until the entire run finishes. This can reduce the amount of intermediate data kept alive, especially for large arrays, images or tensors.

Retention is deliberate. Submitted inputs follow `release_entry_artifacts` (off by default), while values needed for another graph iteration and results selected by artifact policy can remain available. Application references can also keep a payload alive after Jayrun releases it, and Python or a backend allocator may retain the underlying memory. Automatic artifact cleanup is ownership management, not a fixed process-memory bound. See [artifact lifetimes and retained results](../model/lifetime.md).

## Reuse resources across compatible work

A resource separates preparation from computation. Load a model, prepare a calibration table or open a reusable client once, then acquire it from compatible operator executions. The Engine can retain the prepared value after a run ends, avoiding repeated setup for every request.

Reuse depends on resource type, effective configuration and sharing policy. Resources still have a managed end: idle placed resources may be unloaded to make capacity available, and Engine shutdown cleans up its managed cache. Shared values must support the concurrency you permit. The [lifetime walkthrough](data-and-lifetimes.md) shows how artifact data, stable configuration and reusable resources differ; [resource authoring](../guides/graphs/resources.md) explains setup and teardown.

## Build observers and controllers as graphs

Observation and control can be application graphs, not just external code around an Engine. Submit a graph with **Supervisor** authority to observe and control work in its allowed scope, or **Controller** authority when it also needs to submit registered work or request Engine shutdown. Components use `self.runtime` for those operations; authority is explicitly granted by the application.

The supplied [dashboard](../guides/visualization/dashboard.md) uses this model: a graph combines an observing operator with a service resource. Preparing it starts no listener; submitting it starts the service through the normal execution lifecycle. It is an optional application built on the framework's interfaces, rather than a mandatory part of the Engine.

The same primitives let you build application-specific services, for example:

- A monitoring graph that filters events and publishes metrics to your own UI or telemetry service.
- A controller that submits parameter sweeps, watches results and decides which experiment to run next.
- A dispatcher that chooses an execution owner using observed capacity and application policy.
- A coordination graph that exchanges snapshots through your transport to synchronize distributed work.

These services use Jayrun's existing scheduling, thread-execution, async-execution, resource and shutdown machinery. Supervision has separate executor capacity so a waiting controller does not consume the ordinary work's executor slots. It shares the Engine's managed execution infrastructure, not necessarily the same worker pool. Custom policies still need to cooperate with cancellation and yield during async waits.

Start with [runtime authority and capabilities](../guides/runtime/index.md), the [working Controller example](../guides/runtime/controller.md) and [Engine/runtime correspondence](../guides/runtime/correspondence.md). For distributed applications, Jayrun supplies ownership and synchronization primitives; you provide transport, discovery, authentication and failure detection. See [remote coordination](../guides/integration/remote.md).

## Declare once, validate and execute separately

A GraphDefinition describes operators, fields, resource bindings and artifact flows. It is separate from the values and execution state of a particular submission. Confirm a declaration, then submit it repeatedly with different artifact values and configuration without rebuilding the computation each time.

This separation lets you catch declared-property mismatches before execution, inspect or visualize the graph without running a workload, and register a graph identity for controllers and application tools. Each submission has its own ContextRun for results and lifecycle control, while compatible resources may be reused by the Engine. Validation checks the declaration; it does not prove that arbitrary application code or actual payloads are correct.

Follow [from declaration to execution](../guides/workflow/index.md) for the complete path. Graph declarations are acyclic; supported repetition and graph iteration provide repeated work without introducing arbitrary dependency cycles. Conditional routing uses absent (`None`) inputs to skip a branch and its resource setup; [explicit split/join patterns](../guides/graphs/resolutions.md) make those routes inspectable.

## Combine execution, capacity and evidence

Operators can use synchronous or asynchronous hooks. Placement requests account for declared capacity, letting work wait for available resources instead of relying only on a worker count. The application or its backend still performs the actual device allocation. See [async execution](../guides/runs/async.md) and [placement](../guides/components/placement.md).

Records, progress, reports and bounded event/history views make execution observable through public interfaces. Optional `Engine(database=...)` stores execution history and timing profiles across Engine lifetimes. This supports inspection and application decisions without turning diagnostic history into an automatic checkpoint of live Python objects. See [visualization and reporting](../guides/evidence/plots.md) and [Persistence and Database](../guides/evidence/persistence.md).

## Keep the runtime dependency set small

The package declares one required third-party runtime dependency: `packaging`. YAML support is optional through the `yaml` extra, which adds PyYAML. The built-in HTML visualization has no additional Python plotting dependency. Application libraries such as PyTorch or an HTTP framework are needed only when your workload or integration uses them; documentation and development tools are separate from runtime requirements. See [installation](installation.md).

## Responsibilities

| Jayrun owns | Your application owns |
| --- | --- |
| Graph structure, field binding and declared-property validation | Whether a computation's mathematics and actual payloads are correct |
| Execution, lifecycle requests, resources and capacity reservations | Model loading, device allocation and thread safety of shared objects |
| Scoped observation/control and ownership of context execution | Transport, discovery, authentication and authorization of application users |
| Bounded records, reports and optional execution-history storage | Domain checkpoints, business transactions, blob storage and idempotent effects |

Continue with [data and lifetimes](data-and-lifetimes.md), [installation](installation.md) and [a complete first graph](first-graph.md). Read [supported behavior and limitations](../reference/limits.md) before relying on recovery or observation guarantees.
