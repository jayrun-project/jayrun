(runtime-interface)=
# Runtime Interface

`self.runtime` lets a supervising graph observe and control selected live contexts through `ContextRun` objects.

## Grant supervision at submission

Submit a supervisor like any other graph and name the exact graph objects it may supervise:

```python
supervisor_run = engine.submit(
    supervisor_artifacts,
    supervisor_configs,
    supervises=(training_graph,),
)
```

There is no global supervising flag and no list of context IDs in the supervisor configuration. Graph-object identity defines the scope. The runtime exposes only currently registered contexts whose `run.graph is training_graph`.

## Observe authorized runs

```python
candidates = self.runtime.contexts
active = self.runtime.active_contexts
paused = self.runtime.paused_contexts
```

All three properties return tuples of stable {py:class}`jayrun.context.ContextRun` objects in submission order:

- `contexts` contains every visible non-terminal run;
- `active_contexts` contains visible active or draining runs;
- `paused_contexts` contains visible runs currently paused.

A supervisor does not see itself and does not see contexts from graph objects outside its `supervises` scope.

## Wait without polling

```python
await self.runtime.wait_async(
    candidates,
    ContextState.PAUSED,
    timeout=120,
)
```

The asynchronous form suspends the supervising coroutine until every run reaches the requested non-terminal state or terminates. The synchronous `wait()` form has the same behavior, but must not be used to block the event-loop thread.

Omit the state to wait for terminal finalization:

```python
await self.runtime.wait_async(candidates, timeout=120)
```

## Read progress and control a run

Workers publish progress into their own context:

```python
self.context.store("validation_accuracy", accuracy)
self.context.pause()
```

The supervisor reads that record and acts on the same run object:

```python
ranking = sorted(
    candidates,
    key=lambda run: run.get_value("validation_accuracy"),
    reverse=True,
)

winner, *discarded = ranking
for run in discarded:
    run.abort()

winner.stop()
winner.resume()
```

The operations are symmetrical with application-held runs:

- `run.pause()` requests a finite or indefinite pause;
- `run.resume()` continues a paused context;
- `run.stop()` prevents another graph iteration;
- `run.abort()` prevents further dispatch and begins abortion cleanup.

Control requests cross the coordinator message boundary and return immediately. Await the run or a state transition when confirmation matters.

## Authority and lifetime

Each runtime-provided run carries an internal supervisor identity. Control is authorized again when the message is processed. User code never handles identities directly.

When the supervising context terminates, its cross-context authority is detached. A retained supervisor-side run can still be inspected, but attempting to control an active target through it raises `RuntimeError`.

Supervisors intentionally cannot submit new contexts. Application code remains responsible for originating replacement work; the supervisor reports a decision as its output artifact, and the application submits the next cohort.

## API summary

```{py:attribute} RuntimeInterface.contexts
:type: tuple[jayrun.context.ContextRun, ...]

Visible non-terminal runs in submission order.
```

```{py:attribute} RuntimeInterface.active_contexts
:type: tuple[jayrun.context.ContextRun, ...]

Visible active or draining runs.
```

```{py:attribute} RuntimeInterface.paused_contexts
:type: tuple[jayrun.context.ContextRun, ...]

Visible paused runs.
```

```{py:method} RuntimeInterface.wait(runs, state=None, *, timeout=None)
Synchronously wait for visible runs and return the supplied run or tuple.
```

```{py:method} RuntimeInterface.wait_async(runs, state=None, *, timeout=None)
Asynchronously wait for visible runs and return the supplied run or tuple.
```

Continue with {doc}`Placement Interface <placement>`. For a complete selection procedure, see {doc}`MNIST Inference and Supervised Training <../tutorials/mnist-inference-and-training>`.
