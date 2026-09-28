# Resolve graph definition problems

Jayrun requires explicit artifact ownership and consumer order. When a declaration fails, identify the artifact relationship that is ambiguous, then choose a supported shape. This guide pairs the restrictions with practical resolutions; [diagnostics](../problems/graphs.md) lists recognizable error messages.

## Fan-out: split into distinct artifacts

**Invalid intent:** two independent consumers read the same active artifact through separate flows. A duplicate flow is rejected; other shapes can fail with unavailable-artifact or alignment diagnostics. Passing the same artifact to two input fields is also invalid.

This intentionally invalid function uses `Consumer` from [the complete diagnostic example](../../_examples/graph_errors.py). Calling it raises `ValueError` with unavailable-artifact evidence:

```{literalinclude} ../../_examples/graph_errors.py
:language: python
:pyobject: invalid_fan_out
```

**Resolution:** use a splitter operator that consumes the source once and produces distinct artifacts. Give each branch its own flow. `Splitter` below is an application operator, not a special built-in class.

Distinct artifacts do not imply independent Python objects. Returning `(payload, payload)` aliases the same object and is appropriate only with an explicit safe-sharing policy. This example copies the list before either branch mutates it. A shallow copy is sufficient for this list of integers; nested mutable data may need a domain-specific deeper copy.

## Fan-in: separate producers and join explicitly

**Invalid intent:** two producers compete to write one active artifact. Jayrun does not choose a winner or concatenate their values.

This intentionally invalid function uses `Producer` from the same diagnostic example. Calling it raises `ValueError` describing fan-in:

```{literalinclude} ../../_examples/graph_errors.py
:language: python
:pyobject: invalid_fan_in
```

**Resolution:** produce separate artifacts and bind them to separate fields of a join operator. Put the same join declaration at the corresponding consumer position of both input flows. The join waits for its declared dependencies. This is supported synchronization, not implicit fan-in to a single artifact.

## Complete split–process–join graph

The source `[1, 2]` is copied into `left` and `right`. One branch appends `3`, the other `7`; they produce sums `6` and `10`. The explicit join returns `16`. The original input remains `[1, 2]`.

```{literalinclude} ../../_examples/split_join.py
:language: python
```

[Download the example](../../_examples/split_join.py). The interactive graph below shows the resulting structure. In the graph, artifact edges show data dependencies; the two input edges converge at the explicit `Join` operator.

```{raw} html
<iframe class="graph-viewer" src="../../_static/split_join.html" title="Separate branches joined explicitly" loading="lazy" allowfullscreen></iframe>
```

## Consumption, regeneration and conflicting flows

| Problem | Cause | Resolution |
| --- | --- | --- |
| A later consumer needs an already consumed value | Consumption ended the active value | Regenerate it by consuming/outputting that artifact, or split it earlier |
| A producer overwrites an available value | Two active producers claim one identity | Consume/regenerate in sequence, or produce a new identity |
| One artifact has multiple flow definitions | Consumer order is declared more than once | Consolidate consumers in one flow |
| An input has no flow or no origin | Neither entry data nor a producer establishes it | Add a flow and the appropriate entry or producer |
| Join occurrences cannot align | Input flows disagree about dependency order | Align the join occurrence and preceding dependencies across flows |
| A root needs no input data | A dummy input complicates origin rules | Declare no input fields and use a supported input-free root |

A structural exception may occur before `graph` exists. Correct construction first; do not try to plot an object that was never returned. A constructed graph with a property mismatch can be inspected and plotted before successful confirmation.

## Conditional routing and convergence

Publish `None` on an inactive **connected** output. Consumers of that route and their resource setup are skipped with `missing_input`. Any connected input with a `None` value causes a skip, including an input declared `required=False`. `0`, `False` and empty containers remain present values.

```{literalinclude} ../../_examples/conditional.py
:language: python
```

The example prints `(11, None)` and `(None, 11)`, with exactly one consumer executing per submission. The declaration below shows both possible routes. During each submission, only the route with a non-None input executes.

```{raw} html
<iframe class="graph-viewer" src="../../_static/conditional_routes.html" title="Two declared conditional routes" loading="lazy" allowfullscreen></iframe>
```


An all-input join across mutually exclusive branches is **not an OR-join**: one input is absent, so the join is skipped. Choose one of these designs:

- Keep branch results independently terminal and select the available result in the application.
- Put the conditional computation and convergence inside one operator.
- Represent presence/absence as an explicit non-None application value, such as `Data(value=(False, None))`, so downstream code receives both inputs and implements selection itself. This admits both consumers/resources and has different execution cost from skipping.

Do not label an optional connected field as an OR-join. Optional disconnection and missing connected values have different meanings. A returned `None` also clears a previously published value, including one produced before an operator repeat.

### Explicit convergence with tagged values

This complete alternative keeps both artifact values non-None. The `Select` operator always executes and checks the application's presence tag. It prints `10` for either choice. Consumers/resources on these tagged routes are admitted; use this only when that behavior is intended.

```{literalinclude} ../../_examples/conditional_join.py
:language: python
```

## Repetition and external effects

Fixed occurrences in flows, `self.execution.repeat()` and `max_iterations` affect different scopes. Use [repeat and iterate](../runs/iteration.md) to choose. Finish external writes with a zero-output operator and explicit retry policy; a graph declaration does not provide transaction rollback.
