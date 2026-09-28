# Persistence and Database

Use `Engine(database=...)` when execution history must remain available after the Engine shuts down. Jayrun's `Database` stores bounded accounts of Engine sessions and completed contexts, together with learned timing profiles. The default backend uses a local SQLite file. Without a database, live run handles, events and terminal summaries do not become a durable archive.

## What the database stores

| Stored information | How it is used |
| --- | --- |
| Engine-session headers and details | Identify the Engine incarnation that owned the work and inspect its captured session account. |
| Context headers and retained details | Query outcomes and inspect captured configuration, settings, records, failures and execution evidence. Detail availability depends on capture and retention. |
| Captured graph layouts | Present a stored declaration alongside execution evidence when its layout is available. |
| Learned timing profiles | Retain bounded timing observations for compatible workloads; these are estimates, not execution guarantees. |

Artifact objects and live resource instances are not automatically serialized into a resumable computation. Captured diagnostic values are bounded representations, not general-purpose object storage. For model weights, optimizer state or other application state, use an [application checkpoint](../integration/recovery.md).

## Attach a database with Engine(database=...)

Create a database configuration and pass it to the Engine before starting it. Construction performs no storage I/O. The Engine opens the store, manages capture and closes its owned database during shutdown. Do not open the same `Database` instance in a separate context manager while handing it to an Engine.

```python
from jayrun import Engine
from jayrun.persistence import Database

# graph is confirmed and needs no entry artifacts or required configuration.
# Otherwise, supply ArtifactContext and ConfigContext to submit as usual.
database = Database("execution.sqlite")
with Engine(database=database) as engine:
    run = engine.submit(graph)
    run.wait(timeout=10)
    engine.database.flush(timeout=10)
```

Choose an application-owned writable path and keep the file if history should survive process exit. Reusing the path retains history subject to the database's retention policy; it does not resume previously completed work. Graph submission still follows the [ordinary workflow](../workflow/index.md).

## Execution completion and storage completion

`run.wait()` waits for computation to finalize. `database.flush()` waits for already registered persistence handoffs and reports gaps or failures; it does not wait for unfinished or future contexts. When a particular result must be stored before proceeding, wait for that run first and then flush.

The Engine's `EngineSettings.failure_mode` governs managed persistence as well as execution. With the default `FailureMode.CONTINUE`, computation can succeed while its stored account is missing or incomplete. Explicit flush and standalone Database operations remain strict. Inspect `database.status` for storage state, admitted/settled/failed work, gaps and recent errors. A successful operator result alone does not establish successful history capture.

## Read history after shutdown

This complete example reuses `build_graph` from the [workflow program](../../start/first-graph.md). Save both Python files in the same directory, or run it from the documentation examples directory. It prints `finished`. The example uses a temporary directory so it cleans up after itself; use a persistent application path in your program.

```{literalinclude} ../../_examples/history.py
:language: python
```

The Engine first captures a completed run and flushes its registered history writes. After shutdown, `with Database(path)` opens the store for read-only inspection. The session page identifies a stored engine session. A reader restricted to that session then walks context headers using `HistoryQuery` and `next_cursor`.

`get_context()` retrieves a header's detailed account. In this small example it is available; in a long-lived store, retention or capture pressure may leave only a header. Check the returned detail and its coverage before displaying a complete report. History pages carry headers in publication order, not a reconstructed event stream.

## Read while the Engine is running

Use `engine.database.reader(session_ids=(session_id,))` to borrow a reader restricted to chosen stored sessions. Obtain session identifiers from `query_sessions()`; they identify stored Engine incarnations, not arbitrary display names. Omitting `session_ids` grants all-session visibility, so choose that deliberately.

A reader cannot flush or close the store, and it expires when its source database lifecycle ends. Keep reads within the owning Engine or Database scope. An attached database does not automatically grant operators access to history: a Controller receives it explicitly through `Controller(history=reader)`, then uses `self.runtime.history`. See [runtime history access](../runtime/history.md) and [dashboard history access](../visualization/dashboard.md#grant-historical-access-explicitly).

## Configure limits, retention and captured values

`DatabaseLimits` bounds pending admission, batches, readers, pages and operation timeouts. `RetentionPolicy` bounds stored contexts, sessions, profiles, ages and file budget. `ValueLimits`, redaction paths and optional diagnostic codecs constrain captured values. These diagnostic encodings do not persist arbitrary artifact objects or restore a computation checkpoint.

These options belong to `Database`, separately from operator `ConfigContext` values and Engine execution settings:

```python
from jayrun.persistence import Database, DatabaseLimits, RetentionPolicy

database = Database(
    "execution.sqlite",
    limits=DatabaseLimits(page_items=50),
    retention=RetentionPolicy(),  # Default bounded retention; choose for your workload.
)
```

Database retention controls stored evidence; it does not increase the live record/event buffers described in [record retention](records.md). Configure both when you need both kinds of history.

## Maintenance and async applications

Use the current schema `upgrade`/`upgrade_async` operations deliberately, with application backups and ownership of the store. Do not open a second owner to mutate a database while an Engine owns it. An incompatible schema or value error needs an explicit correction, not blind retries.

Async applications must avoid synchronous persistence-enabled Engine calls on their event-loop thread; see [async use](../runs/async.md). All defaults and query types are in the [persistence reference](../../reference/persistence.md).
