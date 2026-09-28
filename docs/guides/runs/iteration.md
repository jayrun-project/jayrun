# Repeat and iterate computation

Choose the repetition scope explicitly. A declared graph is acyclic even when its execution repeats.

| Mechanism | Scope | Control |
| --- | --- | --- |
| Repeated operator occurrence in flows | Fixed graph structure | Consumer-order alignment at construction |
| `self.execution.repeat()` | Current operator step session | `max_repeats`, counting additional executions |
| Graph iteration | Entire graph | `max_iterations`, counting total iterations |
| Retry | Failed invocation attempt | `RetryPolicy.max_attempts`, including the first |

`repeat()` requests another execution after the current invocation returns; it does not loop inside the method. Repeated publication refreshes connected inputs where the graph regenerates their artifacts. This feedback example increments twice in each of two graph iterations and prints `4`:

```{literalinclude} ../../_examples/repetition.py
:language: python
```

A feedback artifact is both consumed and regenerated. An invariant entry needed by later iterations has a different retention role; do not accidentally clear it by retaining only a downstream result. Use [artifact policy](capacity.md) to choose ownership and final results.

`max_iterations=None` permits unbounded graph iteration under external or component control. `max_repeats=None` removes the context-level repeat cap; `0` permits no additional execution. An explicit `stop()` prevents a next iteration while draining accepted work. `abort()` has a different outcome and cancellation policy.

A bound output published as `None` clears its earlier value. Downstream work is skipped if that connected input remains absent when it becomes ready. This remains true after an operator repeat; stale earlier values must not keep a conditional route active.
