# Manage capacity and retention

There is no single setting that bounds all memory and work. Choose limits by their owner and what they count. Exact defaults are in the [settings reference](../../reference/settings.md).

| Owner | Controls | On exhaustion or release |
| --- | --- | --- |
| Engine dispatch | `max_workers`, `max_tasks` | Work waits for execution capacity |
| Managed devices | `RuntimeDevice`, placement requests | Admission waits or rejects an impossible request |
| Context artifact policy | `retained_artifacts`, `release_entry_artifacts` | Values may be cleared; external references remain external |
| Context records | `record_policy` bounds history per key, keys, and accounted bytes | A request exceeding capacity fails before queueing |
| Native execution history | `ContextSettings.execution_history_limit` | Evicts older step reports, lifecycle entries and diagnostic artifact transitions |
| Context history admission | `context_history_admission_limit` | Further history-producing admission raises `ContextHistoryLimitError` |
| Distributed identities | `remote_context_id_limit` | Cumulative new identity admission is rejected at capacity |
| Terminal summaries | Engine `terminal_history_policy` bounds entries and bytes | Older summaries expire; readers see gaps |
| Database | Pending items/bytes, pages, stored retention | Explicit pressure, pruning or storage errors |

## Keep a rolling execution history

A feedback graph can run until it receives Stop and still keep a fixed amount of native history. The following settings apply to an existing graph and its usual inputs.

```python
from jayrun.settings import ContextSettings

settings = ContextSettings(
    max_iterations=None,
    execution_history_limit=8,
)
run = engine.submit(graph, artifacts, settings=settings)
```

Here a snapshot keeps step reports from the last eight **reported graph iterations**. Each iteration can contribute one report per compiled step, including resource and skipped steps. A failed or aborted final iteration takes one place in the window as soon as its partial reports are committed. A running iteration keeps its active sessions until they finish. Repeats and retries remain inside their step report.

The same setting keeps the latest eight lifecycle entries and, in diagnostic mode, eight transitions per artifact. Standard and minimal modes already keep the latest artifact transition. A small lifecycle checkpoint preserves the evicted entry count, iteration, ownership and original stop acceptance. The current artifact values, recovery inputs and resource pins follow their usual lifetimes.

The default `execution_history_limit=None` keeps full native history. The engine’s independent `context_history_admission_limit` charges lifetime admissions and can stop a run when its budget is exhausted.

This is a count limit. Memory also depends on graph size, the number and size of records produced within a single step session, live payloads, cached resources, and snapshots retained by the application. See [reports and artifact history](../evidence/reports.md) for lifetime counters and detail coverage.

## Application records and terminal summaries

Each context gets a default `RecordPolicy` for values written with `self.context.record()`. Each engine gets a default `TerminalHistoryPolicy` for its recent finalized summaries. Set only the limits you need.

```python
from jayrun.settings import ContextSettings, EngineSettings, RecordPolicy, TerminalHistoryPolicy

context_settings = ContextSettings(
    max_iterations=None,
    execution_history_limit=8,
    record_policy=RecordPolicy(history_per_key=4, max_keys=100),
)
engine_settings = EngineSettings(
    terminal_history_policy=TerminalHistoryPolicy(max_entries=128, max_bytes=512 * 1024),
)
```

A fifth committed value for one key evicts its oldest value. New requests exceeding the key or byte budgets fail before queueing. The terminal summary window spans all contexts finalized on the engine. Set `max_entries=0` to disable it. Readers can detect evictions and disabled retention through cursor gaps.

## Artifact retention

`ArtifactPolicy(retained_artifacts=None)` retains all exits. An empty tuple retains none, and an explicit tuple selects individual exits. Successful submission removes entry bindings from the caller's builder even with the default policy. `release_entry_artifacts=True` controls the run's own entry references. It releases them when execution permits and clears the remaining submitted entries and recovery checkpoint at finalization. An application reference can still keep the underlying object alive. See [execution and artifact lifetimes](../../model/lifetime.md).

## Placement

A `RuntimeDevice` describes reservable capacity, not observed free CUDA memory. Use `self.placement.cuda(memory_gb)` or a group reservation before allocation. Group requests express aggregate and per-device budgets, minimum/maximum device counts and optional exclusivity. A temporarily unavailable request can restart invocation after reconciliation; an impossible one cannot be solved by waiting longer.

## Diagnose growth

Check retained run handles, entry builders, record policies, cached resources, observers and persistence queues separately. A zero live-context count is not proof that application references or cached resources are gone. Avoid disabling every limit to hide a pressure error; reduce workload concurrency or retained evidence according to the relevant owner.
