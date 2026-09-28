# Manage capacity and retention

There is no single setting that bounds all memory and work. Choose limits by their owner and what they count. Exact defaults are in the [settings reference](../../reference/settings.md).

| Owner | Controls | On exhaustion or release |
| --- | --- | --- |
| Engine dispatch | `max_workers`, `max_tasks` | Work waits for execution capacity |
| Managed devices | `RuntimeDevice`, placement requests | Admission waits or rejects an impossible request |
| Context artifact policy | `retained_artifacts`, `release_entry_artifacts` | Values may be cleared; external references remain external |
| Context records | History per key, keys, accounted value/total bytes | A request exceeding capacity fails before queueing |
| Context history admission | `context_history_admission_limit` | Further history-producing admission raises `ContextHistoryLimitError` |
| Distributed identities | `remote_context_id_limit` | Cumulative new identity admission is rejected at capacity |
| Terminal summaries | Entry count and byte window | Older summaries expire; readers see gaps |
| Database | Pending items/bytes, pages, stored retention | Explicit pressure, pruning or storage errors |

## Artifact retention

`ArtifactPolicy(retained_artifacts=None)` retains exits; `()` retains none; an explicit tuple selects supported exit references. It does not turn an intermediate into an exit. `release_entry_artifacts=True` releases submitted entry ownership when execution no longer needs it and empties remaining submitted entry/checkpoint ownership at finalization. Holding the original object or a run result in application code can still keep memory alive.

## Placement

A `RuntimeDevice` describes reservable capacity, not observed free CUDA memory. Use `self.placement.cuda(memory_gb)` or a group reservation before allocation. Group requests express aggregate and per-device budgets, minimum/maximum device counts and optional exclusivity. A temporarily unavailable request can restart invocation after reconciliation; an impossible one cannot be solved by waiting longer.

## Diagnose growth

Check retained run handles, entry builders, record policies, cached resources, observers and persistence queues separately. A zero live-context count is not proof that application references or cached resources are gone. Avoid disabling every limit to hide a pressure error; reduce workload concurrency or retained evidence according to the relevant owner.
