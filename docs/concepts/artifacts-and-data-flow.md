(artifacts-and-data-flow)=
# Artifacts and Data Flow

An {py:class}`jayrun.Artifact` identifies data that flows through a graph. Operators declare artifact ports, and an {py:class}`jayrun.ArtifactFlow` orders the consumers of one artifact. Runtime payloads remain separate in {py:class}`jayrun.Data` containers.

This page introduces the artifact objects independently. Their operator-binding rules are completed in {doc}`Operators and Executions <../components/operators-and-executions>`, and their graph relationships are completed in {doc}`Graph Construction <../components/graph-construction>`.

## `Artifact`

Create one artifact declaration for each distinct unit of flowing data:

```python
from jayrun import Artifact

input_data = Artifact(
    name="input_data",
    description="Data supplied to the graph",
)
```

An artifact is a reusable declaration. It does not contain a value and does not imply a file, durable output, or storage location. Its optional `name` and `description` are descriptive metadata.

Artifact identity is object identity. Names are not unique identifiers:

```python
first = Artifact(name="data")
second = Artifact(name="data")

assert first is not second
```

Reuse the same `Artifact` instance when binding operator fields, constructing its flow, supplying its entry value, selecting retention, and retrieving its result.

(artifact-field)=
## `ArtifactField`

An {py:class}`jayrun.ArtifactField` is an operator input or output port. It is not an artifact and does not hold a declaration-time value.

```python
from jayrun import ArtifactField, BaseOperator


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
        self.outputs = (ArtifactField(),)

    def execute(self) -> object:
        return transform(self.input_data.value)
```

Constructing the operator binds artifacts to its fields:

```python
output_data = Artifact(name="output_data")

operation = Transform(
    input_data=input_data,
    outputs=(output_data,),
)
```

`input_data` and `output_data` are graph-level artifact declarations. `operation.input_data` and `operation.outputs[0]` are operator fields bound to those declarations. During execution, the corresponding attributes on the runtime proxy contain {py:class}`jayrun.Data`.

### Optional and connected fields

For input fields, `required` controls whether the operator constructor may bind the field to `None`:

- `required=True` rejects `None`;
- `required=False` allows the field to be bound to either an `Artifact` or `None`.

An optional input is not automatically bound to `None`; the constructor argument chooses the binding.

For output fields, construction does not enforce the field's `required` flag. An output position may therefore be bound to an `Artifact` or `None`, regardless of whether its `ArtifactField` declares `required=True` or `False`.

The operator-level connectivity rule applies only to inputs: every operator must have at least one input bound to an artifact. Outputs follow a separate contract:

- `self.outputs = ()` declares an intrinsically terminal operator and requires no `outputs` constructor argument;
- a non-empty output group requires an `outputs` tuple of the same length;
- any output position may be bound to an `Artifact` or `None`; and
- every output position may be unbound.

Within the input group or output group, two connected fields cannot bind the same artifact. An input and output may bind the same artifact, which regenerates that artifact.

(artifact-output-bindings)=
### Unbound outputs and unavailable values

These two uses of `None` have different meanings:

| Location | Meaning | Graph effect |
|---|---|---|
| `outputs=(artifact, None)` during construction | The second output field is unbound | No artifact definition, producer edge, result, or route exists for that position |
| A bound output returns `None` from `execute()` | The artifact exists but has no runtime value for this execution | Downstream operators requiring that artifact are skipped |

When no output field is connected—whether `self.outputs` is empty or every field is bound to `None`—`execute()` returns `None`. With mixed connected and unbound fields, the return tuple follows the complete declared field order; values at unbound positions are ignored and should conventionally be `None`.

See {ref}`terminal-operators` for sink declarations and {ref}`conditional-routing` for runtime route selection.

(artifact-properties)=
## Artifact properties

Artifact properties are declarations on `ArtifactField` objects. An input field states what it accepts; an output field states what it provides:

```python
from jayrun.properties import ShapeProperty, TypeProperty

self.input_data = ArtifactField(
    properties=(
        TypeProperty(bytes),
        ShapeProperty((None, 4)),
    ),
)
```

Jayrun provides `TypeProperty`, `DTypeProperty`, `ShapeProperty`, `DeviceProperty`, and `BackendProperty`.

Properties are used only for **pre-runtime graph compatibility validation**. They do not inspect or validate a runtime `Data.value`, convert values, move data, select placement, or alter operator execution. A graph edge may therefore be declaratively compatible while user code still returns an invalid runtime payload.

This page establishes where properties are declared. See {ref}`artifact-property-validation` for matching rules, unknown compatibility, validation reports, and property-level diagnostics.

(artifact-definition)=
## `ArtifactDefinition`

When an artifact is registered in a graph, Jayrun creates an immutable {py:class}`jayrun.core.graph.definition.ArtifactDefinition` for it. The definition contains:

| Attribute | Meaning |
|---|---|
| `artifact_id` | Integer identifier local to this graph |
| `name` | Name copied from the artifact declaration |
| `description` | Description copied from the artifact declaration |
| `role` | `ENTRY`, `INTERMEDIATE`, or `UNUSED` |
| `is_exit` | Whether the final graph layout exposes the artifact as an exit |

Definitions come from graph inspection:

```python
entry_definitions = graph.inspect.artifacts.entry
exit_definitions = graph.inspect.artifacts.exit
all_definitions = graph.inspect.artifacts.all
```

Applications do not construct artifact definitions. At this point, it is enough to treat one as the graph's immutable description of an artifact; {ref}`graph-inspection` explains how and when the graph exposes it.

The source `Artifact`, its `ArtifactDefinition`, and its `artifact_id` are three references to the same registered artifact. The definition and ID are graph-local; neither can be used with another graph.

Use the artifact declaration in normal Python code. Use a definition when code is already working with {ref}`graph-inspection`, and use its integer ID when a graph-local reference must be serialized or passed through an external interface.

(artifact-flow)=
## Building an `ArtifactFlow`

An {py:class}`jayrun.ArtifactFlow` is the ordered series of operators that consume one artifact:

```python
from jayrun import ArtifactFlow

data_flow = ArtifactFlow(
    first_step,
    second_step,
    final_step,
    artifact=input_data,
)
```

Build a flow with one simple mental model:

1. Start at the artifact's origin: an application entry or an operator output.
2. Follow that artifact toward the end of the graph.
3. Write down, in order, only the operators that consume that artifact.
4. Give that series to `ArtifactFlow`.

Every listed operator must have one and only one input field bound to the flow artifact. It may also consume other artifacts and therefore appear in their flows.

Do not list an operator merely because it produces the artifact. A flow describes consumers.

### Flow discontinuity

A flow may be discontinuous in the complete graph because it includes only consumers of its own artifact. Suppose the complete path is:

```text
source → prepare → work → transform → source → finish
```

The flows are:

```python
source_flow = ArtifactFlow(
    prepare,
    finish,
    artifact=source,
)

work_flow = ArtifactFlow(
    transform,
    artifact=work,
)
```

`transform` may execute between the two `source` consumers, but it does not belong to `source_flow` because it consumes `work`. {py:class}`jayrun.GraphDefinition` combines the separate artifact series through shared operators and produced artifacts.

See {ref}`graph-construction` for entry flows, cross-flow dependencies, layout construction, and larger graph patterns.

## Entry, intermediate, and exit artifacts

These classifications belong to a graph, not to the standalone `Artifact` declaration:

- an **entry artifact** originates in the application because its flow is listed in `entry_flows`;
- an **intermediate artifact** is produced inside the graph and has a declared flow; and
- an **exit artifact** remains active at the end of the derived graph layout.

An artifact may have the `INTERMEDIATE` origin role and also be an exit. Conversely, a **bound** operator output with no flow is `UNUSED`, not automatically an exit. Empty or unbound output positions do not register artifacts and therefore have no artifact role.

The graph derives these facts during construction and exposes them through {py:class}`jayrun.core.graph.definition.ArtifactDefinition`. See {ref}`graph-entry-exit` for the layout rules.

(artifact-context)=
## Providing and retrieving artifact values

An {py:class}`jayrun.ArtifactContext` stores entry values for one confirmed graph:

```python
from jayrun import ArtifactContext

artifacts = ArtifactContext(graph=graph)
artifacts.set({input_data: initial_value})
```

In `ArtifactContext.set(artifacts)`, the parameter named `artifacts` is a mapping from artifact references to **raw payload values**. It is not one artifact and it is not a mapping of `ArtifactField` objects.

Accepted keys are:

| Key | Best use |
|---|---|
| {py:class}`jayrun.Artifact` | Normal Python application code |
| {py:class}`jayrun.core.graph.definition.ArtifactDefinition` | Code driven by graph inspection |
| `int` artifact ID | Serialized or external graph-local references |

All three resolve through the context's graph registry:

```python
definition = graph.inspect.artifacts.entry[0]

artifacts.set({input_data: initial_value})
# Equivalent reference forms:
artifacts.set({definition: replacement_value})
artifacts.set({definition.artifact_id: replacement_value})
```

`set()` updates the selected entries and wraps each raw payload in CPU {py:class}`jayrun.Data`. Do not use an operator's `ArtifactField` as the key, and do not pass `Data` as the payload.

`get()` accepts the same three reference forms and returns `Data | None`:

```python
data = artifacts.get(input_data)
if data is not None:
    print(data.value)
```

Unknown IDs, foreign definitions, and artifact declarations that do not belong to the graph are rejected. Supplying two aliases that resolve to the same artifact in one `set()` call is also rejected.

(artifact-retention)=
## Artifact retention policy

Contexts retain every exit artifact after successful finalization by default. Retention can be disabled or limited to selected exit artifacts through {ref}`artifact-policy-settings`:

```python
from jayrun.settings import ArtifactPolicy, ContextSettings

settings = ContextSettings(
    artifact_policy=ArtifactPolicy(
        retain_all=False,
        retained_artifacts=(result_artifact,),
    ),
)
```

`retained_artifacts` accepts an `Artifact`, its graph-local `ArtifactDefinition`, or its graph-local integer ID. Only exit artifacts may be selected.

The same policy controls whether the submitted context releases its accepted entry mapping after loading entry values. See {py:class}`jayrun.settings.ArtifactPolicy` for `retain_all`, `retained_artifacts`, and `release_entry_artifacts`.

## Artifact clearing

Jayrun clears artifact payloads when they are no longer required by the active execution path:

- a consumed artifact is cleared after the operator completes unless the operator regenerates it;
- non-retained payloads are cleared during context finalization;
- failed and aborted contexts do not publish partial artifact payloads; and
- retained exit payloads remain reachable until their completed context is deleted or pruned.

Clearing removes the runtime payload, not its artifact declaration or lifecycle report. It only releases Jayrun's reference; payloads retained by application code remain reachable.

(artifact-result)=
## Inspecting `ArtifactResult`

A finalized {py:class}`ContextSnapshot` exposes one {py:class}`ArtifactResult` per graph artifact:

```python
artifact_result = snapshot.artifact(result_artifact)

value = artifact_result.value
placement = artifact_result.placement
data = artifact_result.data
report = artifact_result.report
```

`snapshot.artifact()` accepts the artifact declaration, its graph-local definition, or its graph-local integer ID. `snapshot.artifacts` maps the original artifact declarations to results.

| Attribute | Meaning |
|---|---|
| `data` | Final `Data`; its payload may be `None` after clearing |
| `value` | Convenience access to `data.value` |
| `placement` | Convenience access to `data.placement` |
| `report` | Ordered artifact lifecycle records |

See {doc}`Observability and Inspection <../observability/observability-and-inspection>` for artifact reports and recorder modes.

## API reference

```{py:class} jayrun.Artifact(*, name=None, description=None)
Declare one unit of graph data.

:param name: Optional display name; it does not define artifact identity.
:type name: str | None
:param description: Optional human-readable description.
:type description: str | None
:raises TypeError: If `name` or `description` is neither a string nor `None`.
```

```{py:class} jayrun.ArtifactField(*, name=None, description=None, required=True, properties=None)
Declare an operator artifact port.

:param name: Optional field name.
:type name: str | None
:param description: Optional field description.
:type description: str | None
:param bool required: Whether input binding permits `None`. Output binding does not enforce this flag.
:param properties: Distinct artifact-property declarations, or `None`.
:type properties: tuple[ArtifactProperty, ...] | None
:raises TypeError: If field metadata or properties have invalid types.
:raises ValueError: If a concrete property type appears more than once.
```

```{py:method} jayrun.ArtifactField.bind(artifact) -> None
Bind an input field once to an artifact or, when optional, to `None`.

:param artifact: Artifact declaration or `None`.
:type artifact: jayrun.Artifact | None
:raises TypeError: If `artifact` has an invalid type.
:raises ValueError: If a required input field is bound to `None`.
:raises RuntimeError: If the field is already bound.
```

```{py:class} jayrun.core.graph.definition.ArtifactDefinition(*, artifact_id, role, is_exit, name, description)
Immutable graph-local description of one registered artifact.

:param int artifact_id: Integer identifier local to the owning graph.
:param jayrun.core.graph.definition.ArtifactRole role: Artifact origin classification.
:param bool is_exit: Whether the artifact is an exit of the derived layout.
```

```{py:class} jayrun.core.graph.definition.ArtifactRole
Artifact origin enumeration containing `ENTRY`, `INTERMEDIATE`, and `UNUSED`.
```

```{py:class} jayrun.ArtifactFlow(*components, artifact, name=None, description=None)
Declare the ordered consumers of one artifact.

:param components: One or more operators or nested flows consuming the same artifact.
:type components: BaseOperator | jayrun.ArtifactFlow
:param jayrun.Artifact artifact: Flow artifact.
:param name: Optional flow name.
:type name: str | None
:param description: Optional flow description.
:type description: str | None
:raises TypeError: If the artifact or a component has an invalid type.
:raises ValueError: If the flow is empty or a component does not consume the flow artifact exactly once.
```

```{py:class} jayrun.ArtifactContext(*, graph, name=None, description=None)
Hold entry artifact values for one confirmed graph.

:param jayrun.GraphDefinition graph: Confirmed graph whose artifacts may be referenced.
:raises TypeError: If `graph` is not a `GraphDefinition`.
:raises RuntimeError: If `graph` is not confirmed.
```

```{py:method} jayrun.ArtifactContext.set(artifacts) -> None
Set or replace selected artifact payloads.

:param collections.abc.Mapping artifacts: `Artifact`, `ArtifactDefinition`, or integer artifact ID keys mapped to raw payloads.
:raises TypeError: If `artifacts` is not a mapping or a key has an invalid type.
:raises KeyError: If a reference does not belong to the context's graph.
:raises ValueError: If multiple keys resolve to the same artifact.
```

```{py:method} jayrun.ArtifactContext.get(artifact) -> jayrun.Data | None
Return the current runtime data for one artifact.

:param artifact: Artifact declaration, graph-local definition, or graph-local integer ID.
:type artifact: int | jayrun.Artifact | jayrun.core.graph.definition.ArtifactDefinition
:raises TypeError: If the reference has an invalid type.
:raises KeyError: If the reference does not belong to the context's graph.
```

```{py:method} jayrun.ArtifactContext.clear() -> None
Remove every value from this artifact context.
```

```{py:method} jayrun.ArtifactContext.clear_entries() -> None
Remove entry values from this context and its linked submission source, when applicable.
```

```{py:method} jayrun.ArtifactContext.validate() -> bool
Return whether every entry artifact has a value.
```

```{py:class} ArtifactResult(data, report)
Immutable finalized view of one artifact's data and lifecycle report.
```

```{py:attribute} ArtifactResult.data
:type: jayrun.Data

Final data container. Its payload may be `None` after clearing.
```

```{py:attribute} ArtifactResult.value
Convenience access to `data.value`.
```

```{py:attribute} ArtifactResult.placement
Convenience access to `data.placement`.
```

```{py:attribute} ArtifactResult.report
Ordered artifact lifecycle records.
```

```{py:class} ArtifactRecord(state, actor, step_index, iteration)
Immutable record of one artifact lifecycle transition.
```

```{py:attribute} ArtifactRecord.state
:type: ArtifactState

Artifact lifecycle state at this transition.
```

```{py:attribute} ArtifactRecord.actor
Runtime actor responsible for the transition, or `None`.
```

```{py:attribute} ArtifactRecord.step_index
:type: int | None

Associated graph step index, or `None`.
```

```{py:attribute} ArtifactRecord.iteration
:type: int

Associated graph iteration.
```

```{py:class} ArtifactState
Artifact lifecycle enumeration containing `UNREGISTERED`, `REGISTERED`, `UPDATED`, and `CLEARED`.
```

:::{versionadded} 0.1.0
Artifact declarations, fields, graph-local definitions, flows, contexts, and retention were introduced.
:::

## Common patterns

### Transform one artifact repeatedly

```python
data_flow = ArtifactFlow(normalize, transform, finalize, artifact=data)
```

### Synchronize several inputs

```python
left_flow = ArtifactFlow(combine, artifact=left)
right_flow = ArtifactFlow(combine, artifact=right)
```

`combine` has exactly one input bound to `left` in the first flow and one input bound to `right` in the second.

### Regenerate after a discontinuity

```python
source_flow = ArtifactFlow(prepare, finish, artifact=source)
work_flow = ArtifactFlow(transform, artifact=work)
```

### End a flow with a sink

```python
result_flow = ArtifactFlow(save_result, artifact=result)
```

`save_result` consumes `result` and may declare `self.outputs = ()`. The flow ends at that operator without creating an artificial output artifact. See {ref}`terminal-operators`.

### Branch explicitly

One artifact value has one consumer. To branch, use an explicit split operator that produces distinct artifacts, then give each output artifact its own flow. This preserves deterministic ownership and clearing.

### Route conditionally

Declare a distinct artifact for every possible route. A bound output that receives `None` is unavailable at runtime, so dependent operators on that route are skipped. See {ref}`conditional-routing` for the complete graph pattern and the distinction between an unbound output field and a bound output with no runtime value.

Next, read {doc}`Configuration <configuration>` for stable context-scoped values that do not flow between operators.
