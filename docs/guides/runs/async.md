# Use async applications and notebooks

An Engine can own a background loop or adopt the application's running loop. Use async waits and shutdown from an event-loop thread; blocking there can prevent the work you are waiting for from progressing.

This complete example adopts the application loop, executes an async operator and prints `ready`:

```{literalinclude} ../../_examples/async_execution.py
:language: python
```

In a notebook, execute the declarations and use `await main()` instead of the final `asyncio.run(main())`. Each example creates a fresh engine and closes it in `finally`.

## Persistence-enabled calls

When persistence is enabled, synchronous `start`, `submit` and `apply` must not run in an event-loop thread. Offload those synchronous entry points with `asyncio.to_thread`. Keep waits and shutdown asynchronous. For example, with a configured `database` and confirmed `graph`:

```python
engine = Engine(database=database)
await asyncio.to_thread(engine.start)
try:
    run = await asyncio.to_thread(engine.submit, graph)
    await run.wait_async(timeout=10)
finally:
    await engine.shutdown_async(timeout=10)
```

This variant lets the engine own its loop. A standalone Database exposes explicit async counterparts for its I/O operations; use those rather than blocking its caller loop.

## Cancellation and ownership

Cancelling the application's waiter does not establish that a context was aborted or its resources released. If application policy requires cancellation of the work, request `run.abort()` and await finalization, then shut down the Engine at its owning scope. A timeout is likewise a waiting outcome, not a lifecycle request.

Do not call blocking `run.wait()` from an operator's async body. Use `await self.runtime.wait_async(...)` for authorized visible runs. A Controller's `self.runtime.shutdown()` only requests shutdown; it cannot await the Engine that is executing it.
