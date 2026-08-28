(operators-and-executions)=
# Operators and Executions

Operators declare reusable transformations over artifacts. At runtime, Jayrun executes each operator through an invocation-specific proxy that supplies artifact data, configuration, resources, and the four {doc}`operational interfaces <../interfaces/index>` without mutating the operator declaration.

This chapter defines the construction and execution contract for {py:class}`jayrun.BaseOperator`, including synchronous and asynchronous execution, multiple outputs, repetition, immutability, and operator-local failure behavior. Context lifecycle operations are documented separately under {doc}`Context Interface <../interfaces/context>`.

## `BaseOperator`

Every operator subclasses {py:class}`jayrun.BaseOperator`, declares its fields in `__init__()`, and implements {py:meth}`jayrun.BaseOperator.execute`:

```python
from jayrun import Artifact, ArtifactField, BaseOperator


class Transform(BaseOperator):
    def __init__(
        self,
        *,
        input_data: Artifact,
        outputs: tuple[Artifact | None, ...],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.input_data = ArtifactField(required=True)
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> object:
        return self.input_data.value * 2
```

The constructed object is a declaration. Jayrun does not call `execute()` on that object directly. It compiles the method and fields into the graph, then creates a fresh execution proxy for each step session.

## Constructor contract

An operator constructor must:

1. Accept declaration arguments by keyword.
2. Call `super().__init__(name=name, description=description)`.
3. Assign every input {py:class}`jayrun.ArtifactField`, {py:class}`jayrun.ConfigField`, and {py:class}`jayrun.ResourceField` directly to `self`.
4. Assign exactly one tuple of output fields to `self.outputs`.
5. When `self.outputs` is non-empty, expose an `outputs` constructor argument containing the artifacts or `None` bindings for those fields.

Input artifact arguments are matched to field attribute names. If the declaration assigns `self.input_data`, the constructor must accept `input_data`. For a non-empty output group, the `outputs` argument must have the same length and order as `self.outputs`. A class that declares `self.outputs = ()` does not need an `outputs` constructor argument.

```python
source = Artifact(name="source")
result = Artifact(name="result")

operator = Transform(
    input_data=source,
    outputs=(result,),
    name="transform",
)
```

:::{important}
Constructor attributes describe the declaration only. Runtime computation may rely on declared fields and injected operational interfaces; arbitrary instance state is not copied to the execution proxy.
:::

Invalid declarations fail during construction. Typical failures include a missing `outputs` argument for a non-empty output group, a non-tuple `self.outputs`, mismatched output counts, missing artifact arguments, repeated use of one artifact within an input or output group, or an operator with no connected input. An operator does not need a connected output.

The field types are part of Jayrun's data model, not operator-specific value containers:

- {ref}`artifact-field` defines artifact input and output ports;
- {ref}`config-field` defines context-scoped configuration requirements;
- {ref}`resource-field` defines runtime-managed dependencies; and
- {doc}`Data <../concepts/data>` defines the runtime object injected for every resolved field.

## Declaring inputs and outputs

Declare each input as a direct {py:class}`jayrun.ArtifactField` attribute. Declare outputs only inside `self.outputs`:

```python
class Combine(BaseOperator):
    def __init__(
        self,
        *,
        left: Artifact,
        right: Artifact,
        outputs: tuple[Artifact | None, ...],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.left = ArtifactField(required=True)
        self.right = ArtifactField(required=True)
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> object:
        return self.left.value + self.right.value
```

At runtime, an artifact field becomes {py:class}`jayrun.Data`. Read its payload through `.value` and its location through `.placement`. See {doc}`Data <../concepts/data>` for automatic wrapping, placement metadata, and ownership-specific lifetime.

An operator must have at least one input bound to an artifact. Outputs are optional: `self.outputs` may be empty, individual output fields may be bound to `None`, and a non-empty output group may be entirely unbound. Within the input group and within the output group, one artifact cannot be bound to several fields. An input and an output may use the same artifact; this regenerates that artifact.

For the exact `required` behavior of input and output fields, see {ref}`artifact-field`. In particular, `ArtifactField.required` controls input binding only and is ignored for outputs.

(terminal-operators)=
### Terminal and side-effect operators

An operator that writes to a file, database, API, message broker, or another external sink can declare no outputs:

```python
class SaveResult(BaseOperator):
    def __init__(
        self,
        *,
        result: Artifact,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.result = ArtifactField(required=True)
        self.outputs = ()

    def execute(self) -> None:
        save_to_disk(self.result.value)
```

Construct it without an `outputs` argument:

```python
save = SaveResult(result=result)
```

For a reusable operator class with a fixed output schema, keep the declared fields and bind any or all positions to `None`:

```python
operation = OptionalExport(
    input_data=data,
    outputs=(exported, None),
)

sink = OptionalExport(
    input_data=data,
    outputs=(None, None),
)
```

An empty output group is clearest for an intrinsically terminal operator. An all-unbound group is useful when the same operator class is sometimes connected to graph artifacts and sometimes used only for side effects. See {ref}`artifact-output-bindings` for the declaration-level distinction.

Artifact-field properties describe compatibility at graph-validation time. See {ref}`artifact-properties` for where properties are declared and {ref}`artifact-property-validation` for their complete matching rules.

## Declaring configuration fields

Configuration is context-scoped. Declare each value as a direct {py:class}`jayrun.ConfigField` attribute:

```python
from jayrun import ConfigField


self.factor = ConfigField(
    value_type=float,
    required=False,
    default=1.0,
)
```

Provide values through {py:meth}`jayrun.ConfigContext.set`. During execution, a configured field is injected as {py:class}`jayrun.Data`:

```python
def execute(self) -> object:
    return self.input_data.value * self.factor.value
```

An optional field with neither a supplied value nor a default is injected as `None`. Test the field itself before accessing `.value` in that case.

See {ref}`config-field` for field declaration, {ref}`config-definition` for graph-local identity, and {py:meth}`jayrun.ConfigContext.set` for supplying values.

Configuration must describe the run, not accumulate mutable execution state. Use artifacts for declared data flow and the appropriate {py:class}`ScopeInterface` store for observational state.

## Declaring resource fields

Declare a runtime-managed dependency with {py:class}`jayrun.ResourceField`:

```python
from jayrun import ResourceField


self.service = ResourceField(
    required=True,
    parallel_safe=True,
)
```

The graph binds the field to a resource declaration. When the resource is available, Jayrun injects its loaded {py:class}`jayrun.Data` into the execution proxy:

```python
def execute(self) -> object:
    return self.service.value.process(self.input_data.value)
```

`parallel_safe=True` declares that the same loaded resource may be acquired by concurrent executions. Set it to `False` when access to that resource instance must be serialized.

Only bound resource fields are injected. See {ref}`resource-field` for the field contract, {ref}`resource-definition` for graph-local identity, and {doc}`Resources <../concepts/resources>` for setup, caching, eviction, teardown, and binding.

## Synchronous execution

Define a normal method for synchronous work:

```python
def execute(self) -> object:
    return self.input_data.value * 2
```

Jayrun detects the method during graph compilation and dispatches it through the configured thread executor. The operator may call the synchronous operational-interface methods directly.

Synchronous execution is appropriate for blocking libraries and ordinary Python callables. Thread execution does not make application payloads thread-safe; shared objects and parallel-safe resources must provide their own synchronization where necessary.

## Asynchronous execution

Define `execute()` with `async def` for cooperative asynchronous work:

```python
async def execute(self) -> object:
    response = await client.fetch(self.input_data.value)
    return response
```

Jayrun dispatches coroutine functions on the runtime event loop. Await application coroutines normally; do not block the event-loop thread with synchronous I/O or long CPU-bound work.

See {doc}`Denoise Images with FastAPI <../tutorials/denoise-images-with-fastapi>` for one graph that combines an asynchronous HTTP operator with a synchronous NumPy operator.

Operational-interface calls such as {py:meth}`ScopeInterface.store`, {py:meth}`OperatorExecutionInterface.repeat`, and {py:meth}`ContextInterface.stop` remain synchronous and must not be awaited.

:::{warning}
Returning a coroutine from a synchronous `def execute()` does not make the operator asynchronous. Declare the method with `async def` so graph compilation selects event-loop execution.
:::

## Output return contract

Declare one output field per returned value and preserve the same order:

```python
class Split(BaseOperator):
    def __init__(
        self,
        *,
        input_data: Artifact,
        outputs: tuple[Artifact | None, ...],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.input_data = ArtifactField(required=True)
        self.outputs = (
            ArtifactField(required=True),
            ArtifactField(required=True),
        )

    def execute(self) -> tuple[object, object]:
        midpoint = len(self.input_data.value) // 2
        left = self.input_data.value[:midpoint]
        right = self.input_data.value[midpoint:]
        return left, right
```

The return contract depends on connected outputs:

- When no output field is connected, `execute()` must return `None`. This covers both `self.outputs = ()` and a non-empty group bound entirely to `None`.
- With at least one connected output and one declared output field, return one non-tuple value.
- With at least one connected output and several declared output fields, return a tuple with one position per declared field. Values at unbound positions are ignored and should conventionally be `None`.
- Every raw output is wrapped in {py:class}`jayrun.Data` with CPU placement.
- Return `Data` explicitly to preserve non-default placement metadata.

A bound output that returns `None` publishes an unavailable value for its declared artifact and can disable its downstream route; see {ref}`conditional-routing`. An output field bound to `None` has no graph artifact and produces no result, validation edge, or route.

:::{important}
A tuple returned by `execute()` is interpreted as multiple outputs. To return a tuple as the payload of one output, return `Data(value=payload_tuple)`.
:::

Returning a value when no output is connected, or returning the wrong number of positions for a connected multi-output declaration, raises a `ValueError` inside the execution. It then follows the normal retry and failure policy.

(operator-repetition)=
## Repeat semantics

An operator requests another execution through {py:meth}`OperatorExecutionInterface.repeat`:

```python
def execute(self) -> object:
    result = refine(self.input_data.value)

    if not converged(result):
        self.execution.repeat()

    return result
```

The request takes effect after `execute()` returns successfully. Jayrun stores the returned output, refreshes the operator's bound artifact fields from that output, increments {py:attr}`OperatorExecutionInterface.number`, and schedules the same step session again. Downstream steps remain blocked until repetition ends.

{py:attr}`jayrun.settings.ContextSettings.max_repeats` counts additional executions after the initial one. For example, `max_repeats=2` permits at most three total executions. `None` permits unbounded repetition, so the operator must eventually stop requesting it.

When the repeat limit has been reached, a further request is ignored and the latest result becomes the operator's final output. Execution-scoped stored values remain available across repetitions, while each repetition receives its own execution number and retry attempts.

(operator-reserved-names)=
## Reserved runtime names

The following attributes are reserved for operational interfaces injected only on runtime proxies:

| Name | Capability |
|---|---|
| `self.execution` | Execution-local records, diagnostics, numbering, and repetition |
| `self.context` | Context identity, records, and lifecycle requests |
| `self.runtime` | Runtime records, inspection, and permitted supervision |
| `self.placement` | Accelerator-capacity requests |

Operator subclasses must not declare or assign these names. Names beginning with `_runtime_` are also reserved for framework execution state. Declaring a reserved name on a subclass raises `TypeError`; assigning one to a declaration raises `AttributeError`.

See {doc}`Operational Interfaces <../interfaces/index>` for availability and capability restrictions.

## Operator immutability

After construction, operator declarations are immutable. Assigning or deleting an attribute raises `AttributeError`. Declarative fields and `self.outputs` also cannot be reassigned during construction after their first assignment.

Immutability protects one declaration from cross-context mutation. Runtime values are attached to a separate execution proxy, not to the reusable operator object.

## Reusable operator design

A reusable operator should make all execution dependencies explicit:

- Artifact fields carry graph data.
- Config fields carry context-specific parameters.
- Resource fields carry runtime-managed services or state.
- Operational interfaces provide scoped records, lifecycle requests, and placement.
- Module-level pure functions may contain reusable computation helpers.
- `requirements` may declare external package requirements for graph validation.

Do not use constructor attributes as hidden runtime inputs, cache results on `self`, or depend on one submission having executed before another. The execution proxy exposes declared fields and injected interfaces, not arbitrary declaration state or helper methods attached to the operator instance.

Keep `execute()` independent of application-owned threads and background tasks. If it creates temporary work, join or await that work before returning so the execution interfaces and acquired resources remain within their invocation lifetime.

## Operator failures and retries

Exceptions raised by synchronous or asynchronous `execute()` are captured as execution failures. Jayrun retries a failure only when it matches the effective {py:class}`jayrun.settings.RetryPolicy` and the attempt count remains below `max_attempts`.

The per-context retry policy overrides the engine retry policy when supplied. `max_attempts` includes the initial attempt. If `max_attempts` is greater than one and `retry_on` is empty, Jayrun retries ordinary `Exception` subclasses. Each repeated execution receives a fresh retry budget.

Retries preserve execution-scoped stored values but discard the failed attempt's outputs and placement requests. Execution reports retain the separate attempts and their failure records.

:::{warning}
Retries can repeat external side effects. Operators that write to external systems should use idempotent operations, transactional boundaries, or application-level deduplication.
:::

When the retry policy does not match or the attempt limit is exhausted, the context fails and records the operator as the failed step.

This local section is necessary because retries affect the design of `execute()`. The complete failure categories, context policy, fail-fast behavior, and runtime escalation belong to {doc}`Failure and Reliability Model <../reliability/failure-and-reliability>`.

## API reference

```{py:class} jayrun.BaseOperator(*, name=None, description=None)
Abstract base class for immutable operator declarations.

:param name: Optional operator name used in graph inspection and execution reports.
:type name: str | None
:param description: Optional human-readable description.
:type description: str | None
:raises TypeError: If `name` or `description` is neither a string nor `None`.
```

```{py:attribute} jayrun.BaseOperator.requirements
:type: tuple[str, ...]

Class-level external requirements declared by the operator.
```

```{py:attribute} jayrun.BaseOperator.outputs
:type: tuple[jayrun.ArtifactField, ...]

Ordered output-field declarations. Subclasses must assign this tuple in `__init__()`; it may be empty.
```

```{py:method} jayrun.BaseOperator.execute() -> object | tuple[object, ...] | None
Execute one operator invocation.

Subclasses must implement either a synchronous method or an asynchronous coroutine method. Return `None` when no output is connected; otherwise follow the declared output-field order.
```

```{py:attribute} jayrun.BaseOperator.config_fields
:type: tuple[jayrun.ConfigField, ...]

Configuration fields in declaration order.
```

```{py:attribute} jayrun.BaseOperator.resource_fields
:type: tuple[jayrun.ResourceField, ...]

Resource fields in declaration order.
```

```{py:attribute} jayrun.BaseOperator.declared_artifact_fields
:type: tuple[jayrun.ArtifactField, ...]

Input artifact fields in declaration order, including optional unbound fields.
```

```{py:attribute} jayrun.BaseOperator.bound_artifact_fields
:type: tuple[jayrun.ArtifactField, ...]

Input artifact fields bound to artifact declarations.
```

```{py:attribute} jayrun.BaseOperator.input_artifacts
:type: tuple[jayrun.Artifact, ...]

Artifacts bound to operator inputs.
```

```{py:attribute} jayrun.BaseOperator.output_artifacts
:type: tuple[jayrun.Artifact, ...]

Artifacts bound to active operator outputs.
```

```{py:attribute} jayrun.BaseOperator.display_name
:type: str

Explicit operator name, or the subclass name when no name was supplied.
```

{py:class}`jayrun.ResourceField` and its acquisition behavior are documented in {doc}`Resources <../concepts/resources>`.

{py:class}`jayrun.settings.RetryPolicy` is documented in {doc}`Execution Settings <../settings/execution-settings>`.

:::{versionadded} 0.1.0
Operator declarations, synchronous and asynchronous execution, optional and multiple outputs, terminal operators, repetition, and retry policies were introduced.
:::

See {doc}`Execution Interface <../interfaces/execution>` for execution-scoped storage and diagnostics, and {doc}`Context Interface <../interfaces/context>` for lifecycle requests.

Next, read {doc}`Graph Construction <graph-construction>` to combine operator declarations, followed by {doc}`Graph Validation <graph-validation>` for artifact-contract diagnostics.
