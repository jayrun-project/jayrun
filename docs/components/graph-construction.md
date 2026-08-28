(graph-construction)=
# Graph Construction

A Jayrun graph combines artifact flows into one reusable declaration. Each flow gives the ordered consumers of one artifact; {py:class}`jayrun.GraphDefinition` resolves the relationships between those flows, derives an execution layout, registers graph-local definitions, and prepares the declaration for repeated submission.

This chapter assumes only the declaration-level meanings of {py:class}`jayrun.Artifact`, {py:class}`jayrun.ArtifactFlow`, and {py:class}`jayrun.BaseOperator`. Return to {doc}`Artifacts and Data Flow <../concepts/artifacts-and-data-flow>` or {doc}`Operators and Executions <operators-and-executions>` for their standalone contracts.

## `ArtifactFlow`

An {py:class}`jayrun.ArtifactFlow` follows exactly one artifact:

```python
data_flow = ArtifactFlow(
    normalize,
    transform,
    finalize,
    artifact=data,
)
```

Read this as: “`data` is consumed by `normalize`, then `transform`, then `finalize`.” Each listed operator has one and only one input bound to `data`, but may consume other artifacts as well.

Build flows artifact by artifact:

1. Start at one artifact's origin.
2. Follow that artifact toward the graph's end.
3. List only its consumers, in order.
4. Repeat for every other consumed artifact.

The consumers in one flow need not be adjacent in the complete graph. Dependencies from other flows may place other operators between them. See {ref}`artifact-flow` for this mental model and discontinuity examples.

### Composing flows

An `ArtifactFlow` may contain operators, previously constructed flows, or both. A nested flow must follow the same artifact as its parent:

```python
preparation_flow = ArtifactFlow(
    validate,
    normalize,
    artifact=data,
)

data_flow = ArtifactFlow(
    preparation_flow,
    enrich,
    finalize,
    artifact=data,
)
```

The outer flow preserves the declared composition while exposing the flattened operator order needed for graph construction. This makes a reusable flow segment convenient when several larger declarations share the same ordered consumers. A flow for a different artifact cannot be nested here; cross-artifact relationships are combined by {py:class}`jayrun.GraphDefinition`.

Flows are ordinary Python declarations, so their component sequence may also be generated programmatically:

```python
refinement_pass = (normalize, refine)
components = refinement_pass * 10 + (finalize,)

data_flow = ArtifactFlow(
    *components,
    artifact=data,
)
```

This creates ten fixed `normalize`–`refine` passes followed by `finalize`; it does not copy the operator declarations or request runtime repetition. Every generated component is validated normally, and every occurrence must consume the flow artifact. The complete graph must also satisfy the regeneration and ordering rules described under {ref}`valid-graphs`.

### Reusing an operator in a flow

The same operator declaration may appear more than once:

```python
refinement_flow = ArtifactFlow(
    refine,
    refine,
    finalize,
    artifact=data,
)
```

Each occurrence becomes a distinct graph step at a distinct layout position. The operator must consume the flow artifact at every occurrence, and earlier occurrences must regenerate the artifacts needed by later ones.

This is graph-declared repetition: the number and order of occurrences are fixed before execution. It is different from runtime {ref}`operator-repetition`, where one compiled step requests another execution dynamically through `self.execution.repeat()`.

## `GraphDefinition`

Pass every flow to {py:class}`jayrun.GraphDefinition` and identify which flows originate in the application:

```python
graph = GraphDefinition(
    data_flow,
    metadata_flow,
    entry_flows=(data_flow, metadata_flow),
)
```

`entry_flows` accepts one flow or a tuple. Every entry flow must also appear among the positional flows.

Graph construction resolves relationships that do not belong to any standalone artifact or operator:

- artifact origin and final exit status;
- cross-flow synchronization;
- legal consumption and production order;
- operator layout position;
- registered artifact, config, and resource definitions; and
- the data required for later compilation.

Construction performs structural checks immediately. Artifact-property compatibility is a separate validation layer documented in {doc}`Graph Validation <graph-validation>`.

:::{important}
A graph declaration is reusable. Construct and confirm it once, then create new {py:class}`jayrun.ArtifactContext` and {py:class}`jayrun.ConfigContext` instances for each submission.
:::

(valid-graphs)=
## Valid graph structure

Jayrun derives an acyclic execution layout from the flows. A valid graph satisfies these rules:

- every consumed artifact has exactly one `ArtifactFlow`;
- every non-entry flow artifact is produced before its first consumer;
- every operator has at least one connected input, while outputs may be empty or unbound;
- the flow orders allow the layout builder to make progress;
- one active artifact value is consumed by at most one operator before regeneration;
- one artifact is produced by at most one operator in an execution stage;
- an operator cannot overwrite an active artifact value unless it consumes that value in the same step; and
- a multi-input operator reaches the same stage in every input artifact's flow.

These rules prohibit implicit fan-out and fan-in. They make artifact ownership and clearing deterministic: one active value has one next consumer, and one new value has one producer.

The graph may still express terminal sinks, branching, merging, repeated operator declarations, and conditional routes. Those structures must be explicit, as shown under {ref}`graph-patterns`.

(graph-layout)=
## Graph layout

{py:attr}`jayrun.GraphDefinition.layout` is the dependency-derived matrix used by validation and compilation:

```python
rows, columns = graph.layout.shape
first_stage = graph.layout.col(0)
first_flow = graph.layout.row(0)
```

The coordinates are zero-based:

- a **row** corresponds to an artifact flow in the order supplied to `GraphDefinition`;
- a **column** is an execution stage derived from artifact availability and cross-flow synchronization; and
- a cell contains the operator occurrence that consumes that row's artifact at that stage, or `None`.

A multi-input operator occupies one cell in each input flow's row at the same column, but compiles to one operator step. Independent operators may share a column and become eligible concurrently.

Every compiled operator occurrence has a `layout_position=(row, column)`. For a multi-input occurrence, Jayrun uses its first occupied row as the canonical step row. Resource-setup steps associated with that occurrence use the same position. Execution reports, failed-step references, graph-validation nodes, and field definitions use layout positions to connect runtime information back to the declaration.

:::{note}
Layout position expresses graph structure, not worker assignment or execution start time. Operators in one column may start at different times because resources, placement, executor capacity, or context state still affect dispatch.
:::

(graph-entry-exit)=
## Entry flows and exit artifacts

An entry flow identifies an artifact supplied by the application:

```python
graph = GraphDefinition(
    request_flow,
    state_flow,
    entry_flows=request_flow,
)
```

Here, `request_flow.artifact` is an entry. `state_flow.artifact` must be produced by an operator before its first consumer runs.

Jayrun derives exit artifacts from the finished layout. An exit artifact belongs to a declared flow, is produced by an operator, and remains active after the last execution stage. A bound output artifact with no flow is classified as unused rather than exit data.

A terminal operator may consume the last active artifacts without producing replacements. Such a graph can finish successfully with no exit artifacts. Empty output groups and fields bound to `None` do not create artifact definitions and therefore cannot become intermediate, unused, or exit artifacts.

Inspect the result through graph-local {ref}`artifact-definition` objects:

```python
for definition in graph.inspect.artifacts.exit:
    print(definition.artifact_id, definition.name)
```

Exit status affects runtime retention. The default {ref}`artifact-policy-settings` retains all exit artifacts after successful finalization.

## Graph specification

Construction derives a stable specification of operators, artifacts, resource fields, config fields, and package requirements. It develops in two phases:

1. Operators, artifacts, operator requirements, and resource-field definitions are available immediately.
2. Resource requirements and config-field definitions become complete after resource selection is finalized.

Applications use this information through {py:attr}`jayrun.GraphDefinition.inspect`. The underlying combined specification is framework machinery and is not part of the normal construction workflow.

(graph-resource-binding)=
## Resource binding

Graphs without resource fields confirm automatically. A graph with resource fields must associate them with {py:class}`jayrun.BaseResource` declarations:

```python
graph.bind_resources({operator.service: service})
```

The mapping accepts three graph-local reference forms:

| Key | Best use |
|---|---|
| {py:class}`jayrun.ResourceField` | Normal Python graph construction |
| {py:class}`jayrun.core.graph.definition.ResourceDefinition` | Inspection-driven tooling |
| `int` resource ID | Serialized or external graph-local input |

Each value must be a `BaseResource` declaration. All required resource fields must be bound. If optional fields remain unbound, explicitly confirm that choice:

```python
graph.bind_resources({required_field: service})
graph.confirm()
```

If every registered resource field is bound, `bind_resources()` confirms the graph automatically.

Definitions and IDs must belong to this graph. Multiple aliases resolving to one resource field in the same mapping are rejected. See {ref}`resource-definition` for the distinction between a field definition and the bound resource declaration.

:::{warning}
Resource selection is final. A confirmed graph cannot be rebound, and a graph in the resource-bound state cannot accept a second binding call.
:::

(graph-inspection)=
## Graph inspection

{py:attr}`jayrun.GraphDefinition.inspect` exposes immutable, graph-local descriptions without exposing engine state:

```python
inspection = graph.inspect

entry_artifacts = inspection.artifacts.entry
required_resources = inspection.resources.required
all_configs = inspection.configs.all
requirements = inspection.requirements.all
```

| Area | Views | Definition type |
|---|---|---|
| Artifacts | `entry`, `intermediate`, `exit`, `all` | {py:class}`jayrun.core.graph.definition.ArtifactDefinition` |
| Resources | `required`, `optional`, `all` | {py:class}`jayrun.core.graph.definition.ResourceDefinition` |
| Configs | `required`, `optional`, `all` | {py:class}`jayrun.core.graph.definition.ConfigDefinition` |
| Requirements | `operators`, `resources`, `all` | Requirement definitions |

Artifact and resource definitions are available after construction. Config definitions and resource-derived requirements become available after resource selection is finalized. `graph.inspect.complete` reports whether inspection is complete.

Definitions contain stable metadata and integer IDs local to their graph. They are useful for documentation tools, forms, serialized values, and context lookup. The original declarations remain the clearest references in ordinary Python code. See {ref}`data-model` for the declaration → definition → runtime-data progression.

## Compilation model

Compilation is lazy and cached. It begins when `graph.compiled_graph` is first requested, normally while creating a graph-bound context or submitting work.

Before compilation, the graph must be confirmed and artifact-property validation must contain no mismatched edges. Compilation then converts declaration objects into an immutable {py:class}`jayrun.core.graph.compiled_graph.CompiledGraph`.

The compiled plan contains two step kinds:

| Step | Purpose | Important compiled state |
|---|---|---|
| `CompiledOperatorStep` | Invoke one operator occurrence | Execute method, input/config/resource fields, output fields and mask, execution mode, dependencies, successors, requirements, and layout position |
| `CompiledResourceStep` | Load one resource needed by an operator | Setup and teardown methods, resource config fields, execution mode, operator step group, requirements, and shared layout position |

For every step, compilation resolves:

- `initial_dependency_count`, derived from active input producers and required setup work;
- `successor_indices`, which unlock later steps as dependencies finish or are skipped;
- `execution_mode`, selecting the thread executor for `def` or the event loop for `async def`;
- `group_indices`, grouping an operator with the resource-setup steps it may need;
- `output_mask`, reflecting which declared output positions are bound to artifacts; it may be empty or contain only `False` values;
- graph and package requirements; and
- the occurrence's layout position.

Compilation does not load resources, reserve placement, or execute user code. A resource setup step may be skipped at runtime when matching data is already cached, and an operator may be skipped when any connected input has no runtime value. A step with no connected outputs remains a normal executable step; its successful completion satisfies its successors and records its execution, but publishes no artifact data.

The compiled graph is an execution plan, not application configuration. Continue using the graph declaration and its inspection surface in application code.

## Structural diagnostics

Construction errors identify relationships that cannot form a graph:

| Diagnostic | Meaning | Correction |
|---|---|---|
| Artifact assigned to multiple flows | Two flows claim the same artifact | Merge its consumers into one flow |
| Consumed artifact has no flow | An operator input lacks a flow | Add the artifact's flow |
| Artifact has no origin | A non-entry flow artifact is never generated | Mark the correct flow as entry or add its producer |
| Graph cannot make progress | Flow order contradicts dependencies | Rebuild each flow from artifact origin to end |
| Fan-out detected | One artifact value is consumed more than once | Add an explicit split operator |
| Fan-in detected | Several values produce one artifact simultaneously | Use distinct artifacts and an explicit merge |

Property incompatibility belongs to {doc}`Graph Validation <graph-validation>`, which provides edge- and property-level diagnostics.

(graph-patterns)=
## Larger graph patterns

### Multi-input synchronization

A multi-input operator appears in every corresponding artifact flow:

```python
left_flow = ArtifactFlow(join, artifact=left)
right_flow = ArtifactFlow(join, artifact=right)
```

The derived layout schedules `join` only after both artifacts are active.

(terminal-sink-graph)=
### Terminal sinks

A sink appears as the final consumer in one or more input flows and produces no graph artifact:

```python
from jayrun import Artifact, ArtifactField, ArtifactFlow, BaseOperator


class SaveResult(BaseOperator):
    def __init__(self, *, result: Artifact, name=None, description=None):
        super().__init__(name=name, description=description)
        self.result = ArtifactField(required=True)
        self.outputs = ()

    def execute(self) -> None:
        save_to_disk(self.result.value)


save_result = SaveResult(result=result)
result_flow = ArtifactFlow(save_result, artifact=result)
```

The sink receives a normal layout position and compiled operator step. It creates no producer edge and no exit artifact. A multi-input sink appears in every input artifact's flow at the same layout column, just like any other multi-input operator.

Use this form for operators whose purpose is an external side effect. See {ref}`terminal-operators` for constructor and return rules and {doc}`Failure and Reliability Model <../reliability/failure-and-reliability>` for retry safety.

### Explicit fan-out

One artifact value cannot feed several consumers directly. Add a split operator that consumes it once and produces distinct artifacts:

```python
source_flow = ArtifactFlow(split, artifact=source)
left_flow = ArtifactFlow(process_left, artifact=left)
right_flow = ArtifactFlow(process_right, artifact=right)
```

The split operator binds `(left, right)` as separate outputs and returns one value for each. Each active output now has one producer, one flow, and one next consumer.

An explicit merge performs the inverse pattern: one operator consumes distinct artifacts through distinct input fields and produces one new artifact. The source artifacts remain separate until that operator executes, so this is not implicit fan-in.

(conditional-routing)=
### Conditional routing

A router declares every possible route as an output artifact, then returns `None` for inactive routes:

```python
from jayrun import Artifact, ArtifactField, BaseOperator


class Route(BaseOperator):
    def __init__(self, *, input_data, outputs):
        super().__init__()
        self.input_data = ArtifactField()
        self.outputs = (
            ArtifactField(name="accepted"),
            ArtifactField(name="rejected"),
        )

    def execute(self) -> tuple[object | None, object | None]:
        value = self.input_data.value
        if is_accepted(value):
            return value, None
        return None, value
```

Bind both output positions and construct a flow for each route:

```python
accepted = Artifact(name="accepted")
rejected = Artifact(name="rejected")

router = Route(
    input_data=request,
    outputs=(accepted, rejected),
)

request_flow = ArtifactFlow(router, artifact=request)
accepted_flow = ArtifactFlow(handle_accepted, artifact=accepted)
rejected_flow = ArtifactFlow(handle_rejected, artifact=rejected)
```

Both routes remain part of the compiled DAG. At runtime, an output value of `None` marks that artifact as unavailable. Any downstream operator with an unavailable connected input is skipped; its resource setup is also skipped, and the inactive route propagates through later dependencies. Only routes whose required inputs are non-`None` execute.

:::{important}
`None` returned for a bound output is Jayrun's missing-artifact signal. It is different from binding an output field to `None`, which removes that position from the graph entirely. Do not use `None` as a meaningful artifact payload when downstream execution should continue; wrap that meaning in another application value instead.
:::

### Cross-flow discontinuity

Two consumers in one flow need not be adjacent execution steps. Other flows may place work between them while the flow artifact remains active.

### Shared resources

Bind the same resource declaration to several fields when the operators should share one runtime-managed value. Field-level `parallel_safe` still controls concurrent acquisition.

## API reference

The {py:class}`jayrun.ArtifactFlow` signature is documented under {doc}`Artifacts and Data Flow <../concepts/artifacts-and-data-flow>`.

```{py:class} jayrun.GraphDefinition(*flows, entry_flows)
Construct one reusable graph declaration.

:param flows: Every artifact flow in the graph.
:type flows: jayrun.ArtifactFlow
:param entry_flows: One entry flow or a tuple of entry flows.
:type entry_flows: jayrun.ArtifactFlow | tuple[jayrun.ArtifactFlow, ...]
:raises TypeError: If flows or entry flows have invalid types.
:raises ValueError: If the declarations cannot form a valid structural layout.
```

```{py:method} jayrun.GraphDefinition.bind_resources(resources) -> None
Bind graph resource fields to resource declarations.

:param collections.abc.Mapping resources: Resource-field references mapped to `BaseResource` declarations.
:raises TypeError: If the mapping, a key, or a value has an invalid type.
:raises KeyError: If a reference does not belong to this graph.
:raises ValueError: If required resources are missing or several keys resolve to one field.
:raises RuntimeError: If resources were already bound or the graph is confirmed.
```

```{py:method} jayrun.GraphDefinition.confirm() -> None
Finalize resource selection and make the graph compilable.

:raises RuntimeError: If resources have not been bound or the graph is already confirmed.
```

```{py:attribute} jayrun.GraphDefinition.flows
:type: tuple[jayrun.ArtifactFlow, ...]

All graph flows in declaration order.
```

```{py:attribute} jayrun.GraphDefinition.layout
Derived row-and-column layout used by inspection, validation, and compilation.
```

```{py:attribute} jayrun.GraphDefinition.entry_artifacts
:type: tuple[jayrun.Artifact, ...]

Artifacts that must be supplied by the application.
```

```{py:attribute} jayrun.GraphDefinition.artifacts
:type: tuple[jayrun.Artifact, ...]

All graph artifacts in graph-local ID order.
```

```{py:attribute} jayrun.GraphDefinition.inspect
Declarative inspection grouped by artifacts, resources, configs, and requirements.
```

```{py:attribute} jayrun.GraphDefinition.state
Declaration state: created, resource-bound, or confirmed.
```

```{py:attribute} jayrun.GraphDefinition.confirmed
:type: bool

Whether resource selection is final and compilation is allowed.
```

```{py:attribute} jayrun.GraphDefinition.compiled_graph
Cached execution plan derived from the confirmed graph.

:raises RuntimeError: If the graph is not confirmed.
:raises ValueError: If artifact-property validation contains a mismatch.
```

```{py:class} jayrun.core.graph.graph_layout.GraphLayout
Dependency-derived operator matrix owned by a graph definition.
```

```{py:attribute} jayrun.core.graph.graph_layout.GraphLayout.shape
:type: tuple[int, int]

Number of flow rows and execution-stage columns.
```

```{py:attribute} jayrun.core.graph.graph_layout.GraphLayout.rows
:type: tuple[tuple[jayrun.BaseOperator | None, ...], ...]

Immutable view of the complete layout matrix.
```

```{py:method} jayrun.core.graph.graph_layout.GraphLayout.row(number) -> tuple[jayrun.BaseOperator | None, ...]
Return one zero-based flow row.
```

```{py:method} jayrun.core.graph.graph_layout.GraphLayout.col(number) -> tuple[jayrun.BaseOperator | None, ...]
Return one zero-based execution-stage column.
```

```{py:class} jayrun.core.graph.compiled_graph.CompiledGraph
Internal immutable execution plan produced from a confirmed graph.
```

```{py:attribute} jayrun.core.graph.compiled_graph.CompiledGraph.steps
Ordered compiled operator and resource-setup steps.
```

```{py:class} jayrun.core.graph.compiled_graph.CompiledOperatorStep
Internal compiled representation of one operator occurrence.
```

```{py:class} jayrun.core.graph.compiled_graph.CompiledResourceStep
Internal compiled representation of one resource-setup dependency.
```

```{py:class} jayrun.core.graph.inspection.graph.GraphInspection
Read-only declarative inspection for one graph specification.
```

```{py:attribute} jayrun.core.graph.inspection.graph.GraphInspection.artifacts
Artifact definitions grouped as entry, intermediate, exit, and all.
```

```{py:attribute} jayrun.core.graph.inspection.graph.GraphInspection.resources
Resource-field definitions grouped as required, optional, and all.
```

```{py:attribute} jayrun.core.graph.inspection.graph.GraphInspection.configs
Config-field definitions grouped as required, optional, and all.

:raises RuntimeError: If resource selection has not been finalized.
```

```{py:attribute} jayrun.core.graph.inspection.graph.GraphInspection.requirements
Operator, resource, and combined package requirements.
```

```{py:attribute} jayrun.core.graph.inspection.graph.GraphInspection.complete
:type: bool

Whether resource selection and config inspection are complete.
```

:::{versionadded} 0.1.0
Artifact-flow graph construction, terminal sink steps, graph-local definitions, inspection, resource binding, and compilation were introduced.
:::

Next, read {doc}`Graph Validation <graph-validation>` to validate artifact-property compatibility and inspect detailed diagnostics.
