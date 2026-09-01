(scope-and-lifetime)=
# Scope and Lifetime Model

Jayrun separates reusable declarations from three nested runtime scopes. A scope answers: who owns a value, who can see it, and when can it be released?

```text
Engine runtime
└── Context
    └── Execution
```

## Declarations

Artifacts, operators, resources, fields, flows, and `GraphDefinition` objects describe work without running it. They can be inspected before an engine starts and reused across submissions.

`ArtifactContext` and `ConfigContext` bridge declarations and runtime work. They are created for one confirmed graph and supplied to `Engine.submit()`. The engine captures sealed submission views for the resulting `ContextRun`; the caller's original contexts remain separate objects.

## Runtime scope

The runtime begins when an `Engine` starts and ends when shutdown completes. It owns:

- scheduling and synchronous or asynchronous execution capacity;
- live context registration and coordinator messaging;
- loaded and cached shared resources;
- device-capacity accounting and placement leases;
- failure coordination and cleanup.

Resources belong here because one loaded value may serve several contexts. Their declarations are reusable, while their loaded `Data` is runtime-managed.

## Context scope

A context is one graph submission. It owns:

- the captured artifact and configuration inputs;
- graph iterations and step sessions;
- flowing artifact values and their placement;
- values stored through `self.context.store()`;
- lifecycle state, terminal report, and retained artifact results.

Each call to `Engine.submit()` returns a stable {py:class}`jayrun.context.ContextRun`. It observes the context while active and keeps the terminal information after Jayrun releases the context from the live registry.

`ContextRun.artifact_context` and `ContextRun.config_context` are sealed submission views. Final outputs are not another `ArtifactContext`; they are {py:class}`jayrun.context.ArtifactResult` objects returned by `ContextRun.artifact(...)`.

## Execution scope

An execution is one live operator or resource step session within a context iteration. It owns:

- attempts, retries, and operator repetitions;
- logs, metrics, and timers;
- the current step, iteration, and execution numbers;
- temporary placement requests and step results.

An execution is a logical lifecycle, not a promise that work uses one particular thread, task, process, or device.

## Ownership and lifetime

| Item | Owner | Lifetime rule |
| --- | --- | --- |
| Graph declarations | Application | Reusable independently of an engine |
| Submission contexts | Application, then captured by a run | Caller copies remain mutable; captured run views are sealed |
| Artifact values | Context | Cleared after consumption or retained by artifact policy |
| Context-stored values | Context run | Available during execution and through the completed run |
| Loaded resource data | Runtime resource manager | Shared while cached; torn down safely during eviction or shutdown |
| Placement lease | The placed `Data` value | Capacity remains reserved while the lease is live |
| Execution diagnostics | Execution report | Collected into the terminal context report |
| `ContextRun` | Caller | Remains usable after terminal finalization and engine deregistration |

## Visibility

- Configuration fields expose one context's configured values.
- Artifact fields expose values made available by graph dependencies.
- Resource fields expose runtime-managed shared values.
- `self.context` stores values and controls the currently executing context.
- `self.runtime` exposes only live `ContextRun`s whose exact graph objects were included in the supervisor's `supervises` scope.
- Application code receives the same run operations from `Engine.submit()`.

Supervision does not create a second authority model. Both application code and supervising operators control a target through its authorized `ContextRun`; identities and message routing remain internal.

## Cleanup and retention

### Execution cleanup

Jayrun finalizes attempt and execution records, clears request bookkeeping, and reconciles resources and placement after each step session.

### Context cleanup

Intermediate artifacts are cleared when their flows no longer need them. On successful termination, `ArtifactPolicy` selects retained graph exits. Failed and aborted runs retain reports but do not expose successful output payloads.

Once finalization is complete, the live registry releases the context. The caller's `ContextRun` keeps its report, stored values, sealed submission views, and retained results. There is therefore no public delete or prune lifecycle.

### Runtime cleanup

Graceful shutdown rejects new submissions, prevents additional iterations, resumes paused contexts so accepted work can drain, tears down resources, releases capacity, and closes runtime services. Forced shutdown requests abort for live contexts before the same cleanup sequence.

Application-owned graph declarations and completed runs remain usable after shutdown.

## Common misconceptions

### “The graph owns runtime data”

The graph owns declarations. Each submitted context owns its own configured and flowing values.

### “A resource belongs to the first context that loads it”

Loaded resources are runtime-managed and can be shared safely across matching contexts.

### “A completed context stays in the engine”

Jayrun releases terminal contexts from the live registry. A `ContextRun` already returned to the caller retains the terminal information.

### “Stop and abort mean the same thing”

`stop()` prevents another graph iteration after accepted work drains. `abort()` prevents further dispatch and moves the context through abortion cleanup.

Continue with {doc}`Data Model <data-model>` to distinguish declarations, graph-local definitions, and runtime values.
