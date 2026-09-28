# Route and synchronize remote work

Jayrun provides context ownership and synchronization primitives; it does not provide a network transport, discovery service, authentication system or heartbeat protocol. Integrate those in the application.

## Routing sequence

1. Register compatible graph identities and complete artifact boundary serializers on participating engines.
2. Submit ordinary work. With `RoutingMode.CONTROLLED`, it remains in `ROUTING` until an authorized owner/controller selects an exact engine incarnation.
3. Call `run.transfer(target_engine_id)` according to the authority policy.
4. Deliver the resulting request/committed snapshots through application transport and apply them on the relevant engines.
5. Observe committed owner/generation/state evidence; a request being sent is not proof that transfer completed.

`Engine.apply` and authorized `self.runtime.apply` accept `ContextSnapshot` or `PressureSnapshot`. Context snapshots synchronize committed records, reports, artifacts and state, or carry a control request for the current owner. An assigned queued snapshot can admit work on its owner. Duplicate/stale revisions and obsolete generations do not authorize execution by an old owner.

## Scope and liveness

A scoped Supervisor may apply only authorized context targets; applying remote pressure requires unrestricted supervision or Controller authority. Pressure samples represent received evidence. Applications must handle sample age, network failure, peer trust and re-delivery policy.

During shutdown, committed updates for known contexts can still settle while new work/control requests are rejected. Do not treat every apply failure as retryable network loss; inspect type, identity, authority, capacity and lifecycle errors first.

A remote shadow is an observation of logical work, not a second worker executing it. See [recovery](recovery.md) for iteration boundaries and the limits of resume/replay claims.
