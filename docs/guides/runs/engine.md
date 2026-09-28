# Manage an Engine

The application owns `Engine`: construction chooses settings, an optional graph registry and optional database; `start()` admits work. A synchronous `with Engine() as engine:` starts an owned event loop and shuts down on exit.

Submit a confirmed graph with graph-independent builders:

```python
run = engine.submit(graph, artifacts, configs, settings=context_settings)
engine.wait(run, timeout=10)
```

This fragment assumes a running engine, confirmed graph and its builders. [Your first graph](../../start/first-graph.md) is the complete version. A registry-backed Engine also accepts the graph's registered `(key, version)` identity.

## Live work and diagnostics

`unfinished_contexts` returns non-terminal runs; `active_contexts` includes active/draining states, including paused work. Neither is a permanent completed-run archive. Hold a returned `ContextRun` for its results or use the bounded terminal/history facilities. `state` describes engine lifecycle and `activity` describes work activity; `failure`, `secondary_failures` and `cleanup_failures` help distinguish the primary failure from later drainage errors.

An Engine incarnation has a human name and a unique `engine_id`. Use the latter for ownership transfer. Starting an engine is a lifecycle operation, not a way to reset an old run's ownership or reuse a closed store arbitrarily.

## Application and component operations

Application code can submit authority-bearing contexts with `authority=Supervisor(...)` or `Controller(...)`. Component code uses `self.runtime` and the scope granted to its context. The methods have related vocabulary but different capabilities. See the [Engine/runtime correspondence](../runtime/correspondence.md) and the separate [Engine reference](../../reference/engine.md).

Choose [async integration](async.md) for event-loop applications and [failure/shutdown](failures.md) for timeout and drainage behavior. An Engine with `database=...` owns database admission and lifecycle while managed; do not close it underneath the runtime.
