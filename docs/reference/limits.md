# Supported behavior and known limitations

Use these boundaries when designing an application and interpreting evidence. They describe the current contracts, not universal guarantees for arbitrary application code.

- **Graphs:** acyclic declarations, explicit split/join, input-free roots and artifact-free single-operator flows are supported. Implicit fan-out/fan-in and an automatic OR-join are not. Connected None inputs skip execution and associated resource setup.
- **Validation:** checks declarations and known property compatibility. It cannot prove actual tensor shapes, backend behavior or correctness of an arbitrary payload at runtime.
- **Retries and shutdown:** cooperative lifecycle management does not roll back external effects or forcibly terminate arbitrary blocking native calls. No general exactly-once, sandboxing or deterministic-scheduling claim is made.
- **Placement:** leases account for declared capacity; application/backend code performs real allocations. A CPU fixture or one GPU run does not qualify every backend, platform or multi-device workload.
- **Observation:** events and terminal summaries are bounded. Overflow, capture timing, downtime and pruning can create explicit gaps. Timing profiles are estimates, not calibrated forecasts or a complete historical timeline.
- **Persistence:** captured diagnostic history is separate from artifact/checkpoint storage. A finalized run does not imply flush completion. Continued computation may coexist with explicit history gaps.
- **Authority:** runtime handles are scope- and lifetime-bound. Historic IDs and cursors do not grant control. The application owns authentication, transport and per-user disclosure policy.
- **Remote recovery:** ownership generations/revisions fence synchronization. Applications still define transport, failure detection, checkpoint contents and idempotency of repeated effects.
- **Retention:** framework release does not remove application-owned references. Counts and accounted-byte limits are not a global heap-memory bound.

See [model](../model/evidence.md), [failure handling](../guides/runs/failures.md) and [recovery](../guides/integration/recovery.md) for practical designs within these limits.
