# Read terminal and durable history

Terminal summaries and database history are different stores with different authority and lifetime.

## Terminal summaries

An Engine owner or Controller can call `terminal_history(after=cursor, limit=256)`. A plain Supervisor is denied, including `Supervisor()` with unrestricted live scope. The page contains immutable payload-free summaries, a next cursor, sequence bounds, `has_more` and `gap`.

Start without a cursor, then use `page.next_cursor` for continuation. Check `gap` on every page: count/byte retention, disabled capture or oversized summaries can leave missing sequences. A gap-free interval establishes summary coverage only, not complete records, reports or events. A cursor from another Engine incarnation is rejected; cursor possession never grants authority.

## Granted database history

The owner can pass an explicit `DatabaseReader` scope:

```python
from jayrun import Controller

# engine owns an open managed database; dashboard_graph is registered if needed.
reader = engine.database.reader(session_ids=(chosen_session_id,))
run = engine.submit(dashboard_graph, authority=Controller(history=reader))
```

Inside that Controller, `self.runtime.history` returns a borrowed reader. `Controller()` without a reader returns `None` even when its Engine records to a database. Ordinary contexts and Supervisors are denied.

The borrowed reader cannot close or flush the store. It expires with its Controller or source database lifecycle, and reads recheck authority before admission and before returning results. The hosting application decides which session IDs may be disclosed and protects its transport/UI. An all-session reader is an explicit owner grant, not the default authority of a runtime component.

Use [persistence](../evidence/persistence.md) for query pagination, gaps and flush behavior; see [the runtime reference](../../interfaces/runtime.md) for exact signatures.
