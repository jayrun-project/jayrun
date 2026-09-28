# Submit and shut down from a Controller

A Controller can create ordinary work from a registered graph identity. It cannot create new Supervisor or Controller authority through `self.runtime.submit`: that method intentionally has no `authority` argument.

This complete CPU example registers a work graph and a Controller graph. The Controller submits the work and records its final state; the program prints `finished`.

```{literalinclude} ../../_examples/runtime_control.py
:language: python
```

The application owns the registry and grants `Controller()` when submitting the controller graph. `self.runtime.submit((key, version), artifacts, configs, settings=...)` follows the Engine's routing policy. Under controlled routing, the returned ordinary run needs an explicit authorized `transfer(engine_id)` assignment before it executes. Authority contexts themselves execute locally through supervision capacity.

## Cooperative service loops

Use `while self.runtime.alive:` with bounded application waits, or iterate `self.runtime.events` and return after closure. Keep waits bounded and yield in async service loops so other supervising work can progress.

`self.runtime.shutdown(forced=False)` requests engine shutdown and returns. It does not accept a timeout or provide a waitable shutdown handle. An executing Controller cannot wait for its own runtime to close. Let the operator return/cooperate; the application owner can wait with `engine.shutdown()` or `await engine.shutdown_async()`.

A graceful shutdown settles ordinary work before the authority stage ends. `forced=True` requests abortion instead of graceful iteration drainage; it still cannot kill arbitrary application code safely. See [failure/shutdown](../runs/failures.md).
