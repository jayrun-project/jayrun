(introduction)=
# Introduction

**Jayrun is an artifact-centric execution framework for computational DAGs that need more than one-pass task scheduling.**

An **artifact** is a first-class declaration that identifies data flowing through a graph. It is not the runtime value itself, and it does not imply that the data is a file or persisted output.

Operators declare the artifacts they consume and may produce. They can transform graph data or terminate a flow with an external side effect. These connections define the graph, while artifact fields describe requirements imposed on the data. Dependencies, validation, placement, clearing, and retention therefore remain explicit instead of being hidden inside task implementations.

The declared graph remains acyclic. At runtime, however, it can execute through controlled iterations, and individual operator executions can repeat without introducing structural cycles.

## What Jayrun provides

- Artifact-driven data flow, validation, retention, and automatic clearing
- Concurrent synchronous and asynchronous execution
- Controlled graph iteration and bounded execution repetition
- Shared resources that can be loaded once, reused, evicted, and safely torn down
- CPU, GPU, and multi-device placement with capacity-aware scheduling
- Context inspection, lifecycle control, and in-workflow supervision
- Context-scoped values, logs, metrics, timers, and execution reports
- Retry policies, failure containment, and coordinated shutdown

## When Jayrun fits

Jayrun is useful when a computational DAG must coordinate iterative execution, shared stateful resources, constrained hardware, or autonomous supervision—not merely run independent tasks once.

It is intended for workflows whose data flow, concurrency, resource ownership, hardware requirements, and lifecycle behavior must remain understandable as the system grows.

## Declaration and execution

Jayrun separates the reusable description of computation from its runtime state:

- **Declarations** describe artifacts, operators, resources, configuration, and graph structure.
- **Execution** manages actual values, concurrency, resources, placements, failures, and lifecycle state.

A graph can therefore be inspected once and submitted many times with different data and configuration.

## Synchronous and asynchronous operation

Jayrun supports synchronous and asynchronous components in the same graph. Synchronous operators and resource setup run through the runtime's thread executor. Coroutine implementations declared with `async def` run as tasks on the runtime event loop.

The engine can own that event loop or integrate with one already running in an asynchronous application:

- In a synchronous application, Jayrun creates and runs its own event loop in a background thread. The application can use blocking lifecycle methods such as `wait()` and `shutdown()`.
- In an asynchronous application, Jayrun can use the application's running event loop. The application can await `wait_async()` and `shutdown_async()` without creating a nested loop or blocking other tasks.

This lets blocking libraries and asynchronous clients participate in one execution model while preserving a natural lifecycle API for both scripts and event-loop-based services. An application-owned loop remains owned by the application; Jayrun does not close it during shutdown.

See {doc}`Engine and Context Lifecycle <runtime/engine-and-context-lifecycle>` for loop integration and {doc}`Operators and Executions <components/operators-and-executions>` for synchronous and asynchronous component contracts.

Whether Jayrun owns the event loop or joins an application's loop changes how the application starts and waits for work, but it does not change where execution state belongs. Every running value, lifecycle action, and diagnostic is organized into three nested scopes:

```text
Engine runtime
└── Context
    └── Execution
```

Components interact with these scopes through focused operational interfaces. Configuration is context-scoped, artifacts are context-owned flowing data, resources are runtime-managed, and placements are capacity leases.

Durable persistence remains explicit. Data that must outlive the engine should be saved by an operator to application-owned storage.

Continue with {doc}`Getting Started <getting-started>` to run a complete graph before studying the model in detail.
