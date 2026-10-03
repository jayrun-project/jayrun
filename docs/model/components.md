# Operators and resources

An operator transforms artifacts within a context. A resource prepares reusable data or a capability managed by the runtime. Both have declarations, but their execution ownership differs.

| Concern | Operator | Resource |
| --- | --- | --- |
| Main hook | `execute()` | `setup()` returning `Data` |
| Main inputs | Artifact fields, config fields, bound resources | Declared configuration |
| Lifetime | Context step session, including repetition/retry | Runtime-managed cached instance and acquisitions |
| Result | One return position per declared output | One managed `Data` value |
| Cleanup | Release context-owned values and application-owned temporary work | `teardown(data)` when the managed instance is released |

Constructors declare fields and defaults. Runtime invocation uses proxies, not the original declaration objects. An application attribute such as `self.client` or `self.counter` assigned during construction is not an implicit runtime field. Use configuration for portable immutable parameters, artifacts for flowing data, and resources for managed clients/models.

Directly subclass `BaseOperator` or `BaseResource`; do not build an operator inheritance hierarchy or mix declaration bases. Put reusable implementation logic in ordinary helper functions or application classes. See [operator declaration rules](../guides/graphs/operators.md).

A resource's setup is separate from each operator invocation. Once loaded, its value can remain cached after an acquisition is released and after the loading context ends. Idle, unpinned placed resources may be unloaded to free capacity; Engine shutdown also performs teardown. A later acquisition after unloading requires setup again. See [the early lifetime guide](../start/data-and-lifetimes.md#resources-are-acquired-reused-and-eventually-unloaded) for the full sequence.

A shared resource must be safe for the concurrency admitted by its bindings. `parallel_safe=True` is a declaration by the application, not automatic locking of the underlying object. Separate mutable training state from read-only shared inference models. Resource setup/teardown and partial-failure responsibilities are covered in [resource authoring](../guides/graphs/resources.md).
