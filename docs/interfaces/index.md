(operational-interfaces)=
# Operational Interfaces

Jayrun injects four operational interfaces into a running operator or resource setup:

```python
self.execution
self.context
self.runtime
self.placement
```

They give executable code controlled access to the current execution, its context, the engine runtime, and placement capacity. Declarations describe what the graph is; interfaces let a running step participate in its lifecycle without exposing engine internals.

## Why interfaces are injected

An operator or resource declaration may be reused by many contexts and may execute concurrently. Storing runtime state directly on that declaration would mix independent runs.

Jayrun instead keeps declarations immutable. For each step session, the engine creates an execution proxy, binds artifact, config, and resource values, and injects interfaces associated with that session.

This keeps:

- scope ownership explicit;
- runtime capabilities controlled;
- declarations safe to reuse;
- engine internals outside user components.

Interfaces exist only while the component method is running. Do not access them from `__init__`, save them for later, return them as results, or pass them to work that may outlive the invocation.

:::{warning}
Retaining an operational interface or using it from background work after the component returns violates its invocation lifetime and may act on finalized runtime state.
:::

## Interface map

| Interface | Scope or role | Primary uses |
|---|---|---|
| {doc}`self.execution <execution>` | Current step session | Local values, logs, metrics, timers, execution number, repetition |
| {doc}`self.context <context>` | Current graph submission | Context values, identity, pause, abort, stop iteration |
| {doc}`self.runtime <runtime>` | Engine runtime | Shared records and supervising inspection or control |
| {doc}`self.placement <placement>` | Runtime capacity capability | Single-device and placement-group leases |

The first three correspond to the scope hierarchy. `self.placement` is not a fourth scope; it is an execution-facing capability that requests leases from runtime capacity.

## Common scoped storage API

`self.execution`, `self.context`, and `self.runtime` share this API:

| Method | Result |
|---|---|
| `store(key, value)` | Appends a value in the selected scope |
| `has_value(key)` | Whether that scope has at least one record for the key |
| `get_value(key)` | Latest value, or `None` |
| `get_values(key)` | All values in recording order |
| `get_record(key)` | Latest {py:class}`ValueRecord`, or `None` |
| `get_records(key)` | All {py:class}`ValueRecord` objects for the key |

Keys must be hashable. Each {py:class}`ValueRecord` contains the stored key and value together with the execution metadata captured when the value was recorded.

“Latest” always means the last record in that scope's recording order:

| Interface | Records considered for one key | Meaning of latest | Storage ends |
|---|---|---|---|
| `self.execution` | Records from the current step session, including its retries and operator repetitions | Last value stored by that session | When the step session finalizes or is cancelled |
| `self.context` | Records created by any execution in the active context, across its iterations | Last value appended within that context | When the context finalizes and its execution context is released |
| `self.runtime` | Records created by any context in the current engine runtime | Last value appended to runtime storage | When the engine runtime shuts down |

For concurrently running components, runtime “latest” follows the order in which the runtime store accepts records. It is not selected by the largest `recorded_at` timestamp, context ID, iteration number, or execution number. Use `get_records()` and record provenance when application logic must reconcile concurrent writers explicitly.

```python
def execute(self) -> object:
    self.execution.store("batch_size", len(self.batch.value))
    self.context.store("latest_score", 0.91)
    self.runtime.store("completed_batches", 1)
    return self.batch.value
```

These calls write to three separate stores. Equal keys do not make the values shared across scopes.

`get_value()` cannot distinguish a missing key from a stored value of `None`. Use `has_value()` or `get_record()` when the distinction matters.

### Storage signatures

```{py:class} ScopeInterface
Common storage behavior provided by `self.execution`, `self.context`, and `self.runtime`.
```

```{py:method} ScopeInterface.store(key, value) -> None
Append `value` under `key` in the interface's scope.

:param key: Hashable record key.
:type key: collections.abc.Hashable
:param value: Value to retain. Jayrun stores the object by reference.
:type value: object
:raises TypeError: If `key` is not hashable.
```

```{py:method} ScopeInterface.has_value(key) -> bool
Return whether at least one record exists for `key` in this scope.

:raises TypeError: If `key` is not hashable.
```

```{py:method} ScopeInterface.get_value(key) -> object | None
Return the latest value for `key`, or `None` when no record exists.

Use {py:meth}`ScopeInterface.has_value` when a stored `None` must be distinguished from a missing key.

:raises TypeError: If `key` is not hashable.
```

```{py:method} ScopeInterface.get_values(key) -> tuple[object, ...]
Return all values for `key` in recording order. An unknown key returns an empty tuple.

:raises TypeError: If `key` is not hashable.
```

```{py:method} ScopeInterface.get_record(key) -> ValueRecord | None
Return the latest {py:class}`ValueRecord` for `key`, or `None` when no record exists.

:raises TypeError: If `key` is not hashable.
```

```{py:method} ScopeInterface.get_records(key) -> tuple[ValueRecord, ...]
Return all {py:class}`ValueRecord` objects for `key` in recording order. An unknown key returns an empty tuple.

:raises TypeError: If `key` is not hashable.
```

:::{versionadded} 0.1.0
Scoped storage and record retrieval were introduced with Jayrun's operational interfaces.
:::

(value-record)=
## `ValueRecord`

```{py:class} ValueRecord(step_name, execution, iteration, context_id, key, value, recorded_at)
A frozen record produced by one call to {py:meth}`ScopeInterface.store`.

Applications normally obtain records through {py:meth}`ScopeInterface.get_record` or {py:meth}`ScopeInterface.get_records`; they do not need to construct them.
```

A {py:class}`ValueRecord` combines the stored key and value with provenance from the execution that created it.

```{py:attribute} ValueRecord.step_name
:type: str

Name of the operator or resource step that stored the value.
```

```{py:attribute} ValueRecord.execution
:type: int

Execution number within the current iteration.
```

```{py:attribute} ValueRecord.iteration
:type: int

Graph iteration in which the value was stored.
```

```{py:attribute} ValueRecord.context_id
:type: int

Identifier of the originating context.
```

```{py:attribute} ValueRecord.key
:type: collections.abc.Hashable

Key supplied to {py:meth}`ScopeInterface.store`.
```

```{py:attribute} ValueRecord.value
:type: object

Stored payload.
```

```{py:attribute} ValueRecord.recorded_at
:type: datetime.datetime

UTC time at which the record was created.
```

The record container is immutable. Its `value` may still refer to a mutable object, and Jayrun does not copy or freeze that payload.

The owning storage scope is determined by the interface used to create and retrieve the record. It is therefore not duplicated as an attribute: a record returned by `self.context.get_record()` belongs to context storage, while one returned by `self.runtime.get_record()` belongs to runtime storage.

:::{versionadded} 0.1.0
`ValueRecord` was introduced as the immutable record returned by scoped storage queries.
:::

## Capability restrictions

Having an interface does not imply having every capability on it:

- Every operator execution and resource setup may use scoped storage.
- Only operator executions expose an execution number and repetition.
- A context may request pause, abort, or stop iteration for itself.
- Only a context submitted with {py:attr}`jayrun.settings.ContextSettings.supervising` enabled may inspect or control other contexts through `self.runtime`.
- Placement requests are valid only during the active invocation.

Unauthorized cross-context actions raise `RuntimeCapabilityError`. Supervising capability is granted through {py:attr}`jayrun.settings.ContextSettings.supervising`; naming an operator “supervisor” does not grant it.

## Availability by component

| Component phase | `self.execution` | `self.context` | `self.runtime` | `self.placement` |
|---|---|---|---|---|
| Operator `__init__` | No | No | No | No |
| Operator `execute()` | Yes; includes `number` and `repeat()` | Yes | Yes | Yes |
| Resource `__init__` | No | No | No | No |
| Resource `setup()` | Yes; records and diagnostics only | Yes | Yes | Yes |
| Resource `teardown(data)` | No | No | No | No |

Resource teardown receives the loaded `Data` directly. It should release that data without initiating new context, runtime, or placement work during eviction or shutdown.

The interface attribute names are reserved. Component classes must not declare or assign `execution`, `context`, `runtime`, or `placement` themselves.

(interface-safety)=
## Safe use from synchronous and asynchronous components

Synchronous components run through the configured thread executor. Asynchronous components run on the runtime event loop and may use `await` normally. The operational interface methods themselves are synchronous and do not require `await`.

Context and runtime lifecycle methods enqueue coordinator requests; they do not wait for a transition or interrupt the current Python instruction. Placement calls are also synchronous in syntax, while the engine handles temporary capacity unavailability by suspending and rescheduling the step session.

Treat every operational interface as a runtime-owned handle:

- use it only while the component method is running;
- do not retain it or pass it to background work;
- do not call the same interface concurrently from user-created threads or tasks;
- join or await application-created work before returning;
- do not perform blocking I/O directly in an asynchronous component.

Jayrun protects its own record stores and coordinator messaging. It does not make arbitrary objects passed to `store()` thread-safe.

Start with {doc}`Execution Interface <execution>`, then move outward through context and runtime scope.
