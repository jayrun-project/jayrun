# Create and share resources

Use a resource for a runtime-managed model, lookup table or client whose setup is shared across executions. Bind `ResourceField`s before confirming the graph. Return exactly one `Data` from setup; teardown receives that managed value.

```{literalinclude} ../../_examples/resources.py
:language: python
```

The example submits twice and prints `42`. The operator reads the shared dictionary; it does not mutate it. The Engine manages reuse and releases the resource during shutdown.

## Reuse and concurrency

Reuse is keyed by resource type, effective configuration and the binding’s parallel-safety mode. Display names and graph identity do not define the cache key. Acquisition and placement lifetimes are managed by the runtime. `parallel_safe` states whether the binding permits concurrent use; it does not make a client or model thread-safe. Use separate resources or application synchronization for unsafe mutable state.

An ordinary context finishing does not necessarily tear down a cached resource. An idle, unpinned placed resource can be unloaded when placement reconciliation needs its capacity. Engine shutdown also unloads managed resources after users drain. Setup can run again after unloading; keep durable application state elsewhere. A skipped operator with a missing connected input does not need its resources set up. See [conditional routing](resolutions.md#conditional-routing-and-convergence) for that boundary.

[Compare three submissions](../../model/lifetime.md#compare-three-submissions) for a complete example with flowing artifacts, an operator parameter and a configured resource. It shows reuse with unchanged resource configuration and a new setup when that configuration changes.

## Setup failure and teardown

If setup allocates several application objects and then fails before returning `Data`, release those partial allocations in setup's own exception handling. Teardown cannot clean up an object that was never successfully returned. Keep teardown bounded and idempotent where appropriate; cleanup failures remain visible and should not replace the primary execution failure in your diagnosis.

Resources can reserve placement during setup; a lease can outlive the operator session while the resource remains retained. Make placement calls before allocating application state because admission may restart setup. See [placement usage](../components/placement.md) and [failure handling](../runs/failures.md).
