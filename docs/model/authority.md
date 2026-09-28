# Authority and runtime ownership

The application that owns an Engine can submit and control its work. A running component receives `self.runtime`, but cross-context operations depend on the authority granted when its context was submitted.

- An ordinary context has no cross-context run visibility.
- `Supervisor(graph_a, graph_b)` observes and controls its declared graph scope.
- `Supervisor()` covers all live graph contexts but does not gain Controller-only operations.
- `Controller()` can also submit ordinary registered work, request engine shutdown and read bounded terminal summaries.
- `Controller(history=reader)` additionally borrows the explicitly supplied durable-history scope.

The caller's own context is excluded from its visible-run lists. An exact graph object defines local scope without a registry; registered identities participate in normalization when an Engine uses a registry. Names and context IDs alone do not grant control. Historical cursors do not grant access.

Authority has a lifetime. New operations through expired handles are denied; revocation does not promise to undo requests already admitted. A borrowed reader expires with its Controller or source database and cannot close or flush the store.

Execution ownership is separate. A remote shadow may display state committed by another engine; transport must deliver that evidence. The current owner executes control requests, and generations fence obsolete owners. See [runtime capabilities](../guides/runtime/capabilities.md) and [remote work](../guides/integration/remote.md).
