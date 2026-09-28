# Observation, persistence and recovery

Choose evidence according to the question you need to answer. These views have different owners, limits and completion boundaries.

| Evidence | Useful for | Does not promise |
| --- | --- | --- |
| `run.state`, snapshot and progress | Current committed view of a run | A complete event log or calibrated ETA |
| `run.records(key)` | Retained structured application values | Every value ever recorded or acknowledgment of an external effect |
| `run.report.data` | Final execution, lifecycle and failure evidence | Arbitrary payload serialization |
| Context events | Reacting to changes | Replay or lossless delivery through overflow |
| Terminal history | Bounded finalized summaries with cursor/gap information | Full reports or unlimited history |
| Database history | Explicitly captured durable headers/details | Unseen live events or exactly-once computation |
| Application checkpoint | Domain-specific recoverable state | Automatic capture by Jayrun |

A record call validates and queues a detached value. An immediate read may still see the previous committed view. A completed run may precede database publication; explicit flush reports persistence completion or failure.

Learned timing profiles describe observed workloads and bounded sample support. Estimates can change as work, waiting and evidence change. Unavailable fields and explicit gaps are meaningful; do not replace them with fabricated zeroes.

## Persistence and Database

Persistence is an optional Engine facility for keeping execution history and learned timing profiles in a database across Engine lifetimes. Enable it explicitly by passing a `Database` instance to `Engine(database=...)`; `Engine()` alone does not create a durable store. The default file backend is SQLite.

```python
from jayrun import Engine
from jayrun.persistence import Database

# graph is confirmed and has no required entry values or configuration.
with Engine(database=Database("execution.sqlite")) as engine:
    run = engine.submit(graph)
    run.wait(timeout=10)
    engine.database.flush(timeout=10)
```

The Engine opens and owns the database while it runs. `run.wait()` waits for execution finalization; `flush()` checks settlement of registered storage handoffs. After shutdown, reopen the same path for read-only inspection of stored sessions and contexts. A completed execution and a successfully persisted account are separate outcomes.

The dedicated [Persistence and Database guide](../guides/evidence/persistence.md) covers a complete write–close–read example, stored content, reader lifetimes, failure handling and retention settings. Database history does not keep resource instances alive or automatically save application checkpoints; [checkpoint recovery](../guides/integration/recovery.md) remains an application concern.

For implementation tasks, see [records](../guides/evidence/records.md), [progress/events](../guides/evidence/progress.md), [persistence](../guides/evidence/persistence.md) and [checkpoints/recovery](../guides/integration/recovery.md).
