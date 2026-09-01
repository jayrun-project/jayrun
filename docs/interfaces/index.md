(operational-interfaces)=
# Operational Interfaces

Jayrun injects four focused interfaces while an operator or resource setup is running:

```python
self.execution
self.context
self.runtime
self.placement
```

Declarations describe reusable work. The interfaces let one invocation report diagnostics, interact with its context, supervise authorized runs, and reserve capacity without exposing engine internals.

## Why they are injected

Operator and resource declarations may be reused concurrently by many contexts. Runtime state stored on those declarations would mix independent runs. Jayrun instead keeps declarations immutable and injects invocation-bound capabilities.

Interfaces exist only while the component method is running. Do not access them from `__init__`, retain them after returning, or pass them to background work that may outlive the invocation.

## Interface map

| Interface | Purpose |
| --- | --- |
| {doc}`self.execution <execution>` | Logs, metrics, timers, execution number, and operator repetition |
| {doc}`self.context <context>` | Current context ID, stored values, pause, abort, and stop iteration |
| {doc}`self.runtime <runtime>` | Authorized `ContextRun`s for graph-scoped supervision and waiting |
| {doc}`self.placement <placement>` | Single-device and placement-group reservations |

`self.placement` is a capacity capability, not another data scope.

## One stored-value path

Values needed across executions or iterations of the same context use `self.context`:

```python
self.context.store("validation_accuracy", 0.94)
latest = self.context.get_value("validation_accuracy")
history = self.context.get_values("validation_accuracy")
```

Every call to `store()` appends an immutable {py:class}`jayrun.context.ValueRecord` with the originating step, execution number, iteration, context ID, key, value, and timestamp.

The same records are available from the `ContextRun` returned by `Engine.submit()` or exposed to a supervisor:

```python
accuracy = run.get_value("validation_accuracy")
records = run.get_value_records("validation_accuracy")
```

This avoids parallel execution-, context-, and runtime-storage authorities. Use artifacts for declared data flow, context records for observation and coordination, and application-owned persistence for durable data.

`get_value()` cannot distinguish an unknown key from a stored value of `None`; use `has_value()` or `get_value_record()` when that matters.

(value-record)=
## `ValueRecord`

```{py:class} jayrun.context.ValueRecord(step_name, execution, iteration, context_id, key, value, recorded_at)
Immutable record created by `self.context.store(key, value)`.
```

The container is frozen, but its `value` is kept by reference and may itself be mutable.

| Attribute | Meaning |
| --- | --- |
| `step_name` | Operator or resource step that stored the value |
| `execution` | Execution number within the step session |
| `iteration` | Graph iteration that stored the value |
| `context_id` | Originating context |
| `key` | Caller-provided hashable key |
| `value` | Caller-provided payload |
| `recorded_at` | UTC recording time |

## Capability boundaries

- `self.execution` observes only the current step session.
- `self.context` can control and store values only for itself.
- `self.runtime` exposes only live contexts whose exact graph objects were included in the supervisor submission's `supervises` argument.
- A supervisor acts on another context through the returned `ContextRun`; raw context IDs do not grant authority.
- Placement requests are valid only during the active invocation.

Identity checks and coordinator messages are internal. User code works with the same `ContextRun` methods inside and outside a supervising graph.

## Availability

| Component phase | `self.execution` | `self.context` | `self.runtime` | `self.placement` |
| --- | --- | --- | --- | --- |
| Operator `__init__` | No | No | No | No |
| Operator `execute()` | Yes | Yes | Yes | Yes |
| Resource `__init__` | No | No | No | No |
| Resource `setup()` | Yes | Yes | Yes | Yes |
| Resource `teardown(data)` | No | No | No | No |

Resource teardown receives the loaded `Data` directly and should only release it. The four interface names are reserved on component classes.

(interface-safety)=
## Synchronous and asynchronous safety

Synchronous components run through Jayrun's thread executor. Asynchronous components run on the runtime event loop and may use `await` normally.

Lifecycle methods enqueue coordinator messages. They do not interrupt the current Python instruction or wait for the requested transition. Placement calls are synchronous in syntax; when capacity is temporarily unavailable, Jayrun reconciles and reschedules the step session.

Treat each injected interface as invocation-owned:

- do not retain it or use it after the method returns;
- do not call it concurrently from user-created threads or tasks;
- join or await application-created work before returning;
- do not perform blocking I/O directly in an asynchronous component.

Start with {doc}`Execution Interface <execution>`, then move outward through context and runtime control.
