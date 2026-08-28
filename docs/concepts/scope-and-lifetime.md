(scope-and-lifetime)=
# Scope and Lifetime Model

Jayrun separates reusable declarations from three nested execution scopes. A scope answers three questions: **who owns a value, who can see it, and when may it be cleaned up?**

```text
Engine runtime
└── Context
    └── Execution
```

An engine runtime may host many contexts concurrently, and each context may perform many executions.

## Declaration layer

The declaration layer describes work without running it. It contains artifacts, operators, resources, their fields, `ArtifactFlow` connections, and the resulting `GraphDefinition`.

Declarations can be created before an engine starts, inspected and validated without execution, and reused across submissions. They carry structure, types, requirements, and relationships—not the mutable values of a particular run.

{py:class}`jayrun.ArtifactContext` and {py:class}`jayrun.ConfigContext` bridge declaration and execution. They are created against a graph and provide values for one submission. The submitted context receives captured input state while the graph declaration remains reusable.

The declaration layer is the plan; it is not an execution scope.

## Runtime scope

The runtime scope begins when an `Engine` starts and ends when it shuts down. It owns or manages:

- registered contexts and their lifecycle;
- synchronous and asynchronous execution capacity;
- loaded, cached, shared, and pinned resources;
- runtime-scoped values and records;
- coordination, scheduling, failure handling, and cleanup.

Resources belong here because loaded data may be reused by multiple contexts. A resource declaration is reusable metadata; its loaded instance is runtime-managed state.

## Context scope

A context is one submitted graph run. It begins at submission and progresses independently through validation, scheduling, execution, pausing, iteration, and finalization.

The context owns:

- its combined settings and configuration values;
- its artifact values and their state transitions;
- its iterations and executions;
- context-scoped values and records;
- lifecycle state, history, report, failure, and retained results.

Artifacts are context-owned flowing data. An artifact declaration belongs to the graph, while each submitted context holds its own value for that artifact. Operators consume available artifact values and produce new ones; Jayrun uses those transitions to determine readiness, repetition, iteration, clearing, and completion.

Finalization ends the context's execution, but does not immediately remove it from the engine. A finalized context remains inspectable until it is deleted, pruned, or removed during shutdown.

## Execution scope

An execution scope is the live step session for an operator or resource setup within one context iteration. It can contain retry attempts and, for an operator, repeated executions.

This scope contains:

- execution-scoped values and records;
- logs, metrics, and timers;
- the current step, iteration, and execution number;
- session-local requests and attempt state;
- its results, attempts, or failure.

It is a logical lifecycle, not a promise that work runs on a particular thread, task, process, or device.

## Scope nesting

- One runtime contains zero or more contexts.
- One context contains zero or more executions across its steps, repeats, and iterations.
- An execution cannot exist independently of its context or runtime.

The nesting defines containment, not execution order. Contexts may run concurrently within one runtime, and several independent executions may run concurrently within one context when graph dependencies permit.

## Ownership versus lifetime

Ownership determines who controls state and cleanup. Lifetime describes how long a particular object remains usable. They are related but not identical.

| Item | Owner | Lifetime rule |
|---|---|---|
| Graph declarations | Application | Independent of engine execution and reusable across submissions |
| Config values | Context | Fixed for the submitted context |
| Artifact values | Context | Flow through executions; cleared or retained according to use and policy |
| Loaded resource data | Runtime resource manager | Reused while managed; torn down when safely evicted or during shutdown |
| Runtime records | Runtime | Shared across contexts for the runtime's lifetime |
| Context-scoped stored values | Context | Available while the execution context is active; released at context finalization |
| Execution records | Execution | Local to the step session, including its retry attempts and repetitions |
| {py:class}`ContextSnapshot` | Caller | Structurally immutable observation that may outlive registry deletion |

## Data visibility

- **Runtime-scoped values** are shared across contexts in one engine runtime.
- **Context values** are visible to executions in the same context.
- **Execution values** are local to the current step session.
- **Configuration values** belong to one context and appear through declared config fields.
- **Artifact values** belong to one context and become available according to artifact-flow dependencies.
- **Resource data** is runtime-managed and exposed through bound resource fields.
- **Records** remain associated with the scope in which they were created.

## Cleanup and retention

Cleanup follows ownership from the innermost scope outward.

### Execution cleanup

As a step session retries or repeats, Jayrun separates diagnostic attempt and execution records while preserving session-scoped values. When the session finalizes or is cancelled, Jayrun finalizes its report and clears request bookkeeping. Resource use is reconciled with the runtime resource manager.

### Context cleanup

Artifact values that are no longer needed may be cleared during execution. On successful finalization, the artifact policy determines which exit artifacts remain inspectable. Jayrun retains all exit artifacts by default; callers may select a smaller set. Intermediate artifacts are cleared as their flow permits.

An output-free terminal operator can consume the last active artifacts without creating an exit payload. The context and execution reports remain context-owned, while any file, database row, message, or remote request created by the operator follows the external system's lifetime.

Failed or aborted contexts do not retain result payloads, but their state, failure, history, and reports remain inspectable while registered.

Context-scoped stored values coordinate active executions but are not copied into the finalized snapshot. Finalization retains lifecycle history, diagnostic reports, and selected artifact results instead.

`Engine.delete(context_id)` removes one finalized context. `Engine.prune(...)` removes finalized contexts in bulk. Persist durable results explicitly before deletion or shutdown.

### Runtime cleanup

Runtime shutdown stops admission, settles or terminates context work according to the shutdown procedure, tears down managed resources, releases allocator state, and closes runtime services. Application-owned declarations and snapshots already obtained by the caller are outside runtime ownership.

## Scope comparison

| Layer or scope | Created by | Primary contents | Visibility | Ends when |
|---|---|---|---|---|
| Declaration layer | Application code | Graph structure, fields, requirements, metadata | Wherever declarations are referenced | Application releases them |
| Runtime scope | `Engine.start()` | Context registry, records, resources, devices, capacity | Engine API and runtime handles | Engine shutdown completes |
| Context scope | `Engine.submit(...)` | Settings, config, artifacts, lifecycle, report | Engine snapshots and executions in that context | Work finalizes; registration remains until delete, prune, or shutdown |
| Execution scope | Context scheduler | One step session, its attempts, repetitions, diagnostics, and requests | The running step session | Session finalizes or is cancelled |

## Common misconceptions

### “The graph owns the data”

The graph owns declarations and relationships. Each context owns its own configuration and artifact values.

### “A resource belongs to the first context that loads it”

Loaded resources are runtime-managed so they can be safely cached and shared across contexts.

### “An execution is a worker thread”

An execution scope is a logical step session. Scheduling determines where and when its executions run.

### “Finishing a context removes it”

Finalization freezes its result state. The engine retains it until deletion, pruning, or shutdown.

### “All produced artifacts remain available”

Artifact values may be cleared after consumption. Successful contexts retain exit artifacts by default, not every intermediate value.

### “A snapshot is the live context”

A `ContextSnapshot` is structurally immutable and does not update in place. Fetch another snapshot to observe a later revision. Artifact payload objects are not deep-copied.

Continue with {doc}`Data Model <data-model>` to distinguish declarations, graph-local definitions, and runtime values before examining individual data types.
