# Submit and shut down from a Controller

A Controller can submit a confirmed GraphDefinition or registered `(key, version)` identity through `self.runtime.submit(graph, artifacts, configs, settings=..., authority=...)`. The arguments follow `Engine.submit()`. Without a registry, newly constructed and confirmed graphs can be submitted directly. When the Engine has a registry, direct graph objects must also be registered.

This complete CPU example registers a work graph and a Controller graph. The Controller submits the work and records its final state; the program prints `finished`.

```{literalinclude} ../../_examples/runtime_control.py
:language: python
```

The application owns the registry and grants `Controller()` when submitting the controller graph. `self.runtime.submit((key, version), artifacts, configs, settings=...)` follows the Engine's routing policy. Under controlled routing, the returned ordinary run needs an explicit authorized `transfer(engine_id)` assignment before it executes. Authority contexts themselves execute locally through supervision capacity.

## Delegate Controller and Supervisor creation

The host chooses the policy when constructing the Engine:

```python
from jayrun import Engine
from jayrun.settings import ControllerPolicy, EngineSettings

engine = Engine(EngineSettings(controller_policy=ControllerPolicy.DELEGATED))
```

`HOST_ONLY` is the default. Controllers can submit ordinary work, but any non-None
`authority` passed to runtime submission raises `PermissionError` before child
admission. Host calls to `engine.submit(..., authority=...)` remain allowed.
`DELEGATED` permits live Controllers to submit Controller or Supervisor children:

```python
# Inside a Controller operator, with a confirmed agent_graph:
from jayrun import Controller
from jayrun.settings import ContextSettings

child = self.runtime.submit(
    agent_graph,
    settings=ContextSettings(max_iterations=1),
    authority=Controller(),
)
```

A child Controller can in turn submit newly constructed engineering graphs or
further authority-bearing work. Supervisors and ordinary contexts still cannot
submit. `Supervisor(work_graph)` retains its existing graph-wide scope; it is not
restricted to work submitted by its parent. A history reader must be granted
explicitly with `Controller(history=reader)`; it is never inherited automatically.

Children belong to the Engine. Parent completion or abortion does not automatically
cancel them or revoke their own authority. Handles issued to the parent retain
that parent's authority lifetime. Explicitly wait for or control children while
that grant is alive. Authority-bearing children execute locally even under
controlled routing. During Engine shutdown, new child submissions are rejected.

Parent and child Controllers share supervision capacity. A parent waiting for a
child still occupies its execution slot, including during an async wait. Configure
sufficient `max_workers` / `max_tasks` for the nesting you permit; otherwise queued
children may be unable to start. This policy does not add a process sandbox or
change the trust placed in application Python code.

## Cooperative service loops

Use `while self.runtime.alive:` with bounded application waits, or iterate `self.runtime.events` and return after closure. Keep waits bounded and yield in async service loops so other supervising work can progress.

`self.runtime.shutdown(forced=False)` requests engine shutdown and returns. It does not accept a timeout or provide a waitable shutdown handle. An executing Controller cannot wait for its own runtime to close. Let the operator return/cooperate; the application owner can wait with `engine.shutdown()` or `await engine.shutdown_async()`.

A graceful shutdown settles ordinary work before the authority stage ends. `forced=True` requests abortion instead of graceful iteration drainage; it still cannot kill arbitrary application code safely. See [failure/shutdown](../runs/failures.md).
