# Component interfaces

Application code creates an Engine and submits a graph. Component code runs inside that Engine. Jayrun gives it four interfaces through `self`, so the computation can describe its execution, control its current run, reserve capacity or supervise other work.

You do not import or construct these interface classes. Declare a direct subclass of `BaseOperator` or `BaseResource`; Jayrun supplies the appropriate handles when it invokes the hook.

## Declaration time and execution time

Consider the operator from the [guided workflow](../../start/first-graph.md):

```{literalinclude} ../../_examples/first_graph.py
:language: python
:pyobject: Scale
```

The constructor declares `source`, `factor` and `outputs`. At graph construction, `Scale(source=source, outputs=(result,))` binds artifact identities to the fields. It does not yet know the input value of a future run.

At execution, Jayrun calls the class's `execute()` implementation with an execution object as `self`. That object contains Data wrappers for the declared inputs, configurations and resources, plus the interfaces below. This object is often called a *proxy*. It lets the same declaration serve different runs without storing their values on the declaration.

| Handle | Use it for | Example |
| --- | --- | --- |
| `self.execution` | Logs, numeric metrics and timers for this invocation; operator repetition | `self.execution.log("loaded")` |
| `self.context` | The current run's records and lifecycle requests | `self.context.record("loss", loss)` |
| `self.placement` | Reserving accelerator capacity | `self.placement.cuda(memory_gb=0.5)` |
| `self.runtime` | Engine identity and authorized operations on other runs | `self.runtime.engine_id` |

The proxy does not inherit arbitrary application attributes or helper methods from your declaration. For example, `self.client = make_client()` in the constructor does not make a runtime client available in execute. Declare a ResourceField and bind a resource instead. Put reusable calculation logic in an ordinary function and call it from the hook.

## Which hooks receive what?

| Hook | Values available | Interfaces |
| --- | --- | --- |
| Operator `__init__` | Declaration arguments and fields you create | No executing context yet |
| Operator `execute()` / async execute | Declared input/config/resource values | All four; cross-context operations still require authority |
| Resource `setup()` / async setup | Declared configuration values | All four, but no execution `repeat()` or `number` |
| Resource `teardown(data)` / async teardown | The returned Data and declared configuration values | No injected execution/context/runtime/placement handles |

Resource setup runs for an acquisition that needs a resource loaded. Later users may reuse its cached value without invoking setup. Therefore a record emitted by setup belongs to the context that performed that setup; it is not a record emitted once for every user of the resource.

Teardown may occur after the original context has finished. Clean the object passed as `data`, such as `data.value.close()`, rather than trying to control that old context. [Resource authoring](../graphs/resources.md) shows setup and cleanup together.

## Learn each interface

```{toctree}
:maxdepth: 1

execution
context
placement
../runtime/index
```

Continue with [runtime supervision](../runtime/index.md) for `self.runtime`, including its authority requirements and correspondence with Engine operations. The [interface reference](../../interfaces/index.md) provides the complete member lists after these usage chapters.
