(graph-validation)=
# Graph Validation

Graph validation compares the artifact properties declared at producer and consumer ports before runtime execution begins. It complements the structural checks performed by {py:class}`jayrun.GraphDefinition` construction.

Validation is declarative. It examines the graph and its {py:class}`jayrun.ArtifactField` metadata; it does not execute operators or inspect runtime {py:class}`jayrun.Data` payloads.

## Structural and property validation

Jayrun has two distinct validation boundaries:

| Boundary | Trigger | What it checks |
|---|---|---|
| Structural construction | `GraphDefinition(...)` | Flows, origins, ordering, ownership, fan-in, fan-out, and layout progress |
| Artifact-property validation | `GraphValidator(graph).validate()` or compilation | Compatibility between a bound producing output field and consuming input field |

A structurally valid graph can still contain a property mismatch. Conversely, an edge with incomplete property declarations can remain structurally valid and executable.

See {doc}`Graph Construction <graph-construction>` for structural rules and diagnostics.

(artifact-property-validation)=
## Artifact-property validation

Properties belong to operator fields, not artifacts. For one artifact edge:

- the producing output field is the **source**;
- the consuming input field is the **target**;
- the target property decides whether it accepts the source property.

```python
from jayrun import ArtifactField
from jayrun.properties import ShapeProperty, TypeProperty

self.input_data = ArtifactField(
    properties=(
        TypeProperty(bytes),
        ShapeProperty((None, 4)),
    ),
)
```

Properties express compatibility claims only. They do **not**:

- check the actual runtime value;
- convert or cast a payload;
- move data between devices;
- request placement capacity; or
- change scheduling or execution behavior after validation.

User code remains responsible for returning values that satisfy its declarations.

## Built-in properties

| Property | Compatibility rule |
|---|---|
| {py:class}`TypeProperty` | Input and output declare the same Python type object |
| {py:class}`DTypeProperty` | Input and output dtype sets have at least one common value |
| {py:class}`ShapeProperty` | Ranks match and every concrete input dimension equals the output dimension; input-side `None` is a wildcard |
| {py:class}`DeviceProperty` | Device-name strings are equal |
| {py:class}`BackendProperty` | Backend-name strings are equal |

Each field may declare at most one property of each concrete type. An empty property tuple is valid and means compatibility cannot be proven from that field.

:::{important}
`DeviceProperty` and `BackendProperty` are declarative validation metadata. They do not reserve devices and are not synchronized automatically with `Data.placement`. Use {doc}`Placement Interface <../interfaces/placement>` to request accelerator capacity.
:::

## Match, mismatch, and unknown

Each property comparison produces one {py:class}`jayrun.core.validation.ValidationStatus`:

- `MATCH` — both sides declare the property and the target accepts the source;
- `MISMATCH` — both sides declare it and the target rejects the source; or
- `UNKNOWN` — either side does not declare the property.

An edge is mismatched if any property mismatches. Otherwise it is unknown when any property is unknown or neither field declares properties. It is a match only when every compared property matches.

Unknown is intentionally not failure. It means the declarations do not contain enough information to prove compatibility. Unknown edges remain compilable; mismatched edges do not.

Entry edges and terminal exit or unused edges have no opposing pair of artifact fields, so they do not receive property compatibility reports. Empty output groups and output fields bound to `None` create no artifact edge and therefore require no property comparison.

## Validating a graph

```python
from jayrun.validation import GraphValidator

validator = GraphValidator(graph)
validation = validator.validate()

if not validation.valid:
    validator.report.print()
```

The validation report is cached for the validator. It contains immutable nodes and edges corresponding to entry artifacts, operators, terminal artifacts, and artifact movement.

`validation.valid` is `True` when no edge is mismatched. Use `mismatched_edges` for failures and `unknown_edges` for declarations that could be made more precise.

Validation may be run immediately after graph construction; resource binding is not required because artifact compatibility depends only on the graph layout and artifact fields.

For a complete PyTorch example that constructs a graph, detects a deliberate dtype mismatch, and plots the result, follow {doc}`Build and Validate a Graph <../tutorials/build-and-validate-graph>`.

## Validation graph model

The validation report is a diagnostic view of the derived {ref}`graph-layout`, not a second executable graph.

It contains three node types:

| Node type | Meaning |
|---|---|
| `ENTRY` | Application origin of one entry artifact |
| `OPERATOR` | One operator occurrence at a layout position, including a terminal sink |
| `EXIT` | Terminal location of an active produced artifact |

Edges have four structural types:

| Edge type | Meaning | Property comparison |
|---|---|---|
| `ENTRY` | Entry artifact to its first operator | Unavailable because there is no producing output field |
| `INTERMEDIATE` | Producing operator to consuming operator | Output-field properties compared with input-field properties |
| `EXIT` | Active flow artifact leaving the layout | Unavailable because there is no consuming input field |
| `UNUSED` | Bound, unflowed produced artifact reaching the terminal view | Unavailable because there is no consumer |

Each operator occurrence receives its own node. A multi-input occurrence has one incoming edge per input artifact. A declaration repeated in a flow appears as several nodes at its several layout positions.

A terminal operator with `self.outputs = ()`, or with every output field bound to `None`, has incoming artifact edges but no outgoing artifact edge. A mixed output group creates producer edges only for its bound fields. Unbound positions do not appear as `UNUSED` edges because they do not identify artifacts.

Graph structure has already been checked by `GraphDefinition`; the validator does not repair ordering, infer missing flows, or rewrite an invalid declaration.

## Reading edge diagnostics

Each {py:class}`jayrun.core.validation.GraphEdge` identifies its source and target nodes, artifact, source output field, target input field, edge type, and optional artifact-validation report.

A property report contains:

| Attribute | Meaning |
|---|---|
| `property_name` | Concrete property class name |
| `target_declared`, `source_declared` | Whether each side declared the property |
| `target_value`, `source_value` | Declared values, or `None` when absent |
| `status` | `MATCH`, `MISMATCH`, or `UNKNOWN` |
| `reason` | Explanation for a mismatch or unknown result |

The text reporter formats these details:

```python
text = validator.report.format()
validator.report.print()
path = validator.report.save("graph_validation.txt")
```

`format()` has no side effects. `print()` writes the same formatted report to standard output. `save()` writes UTF-8 text and returns the resolved path. All three operate on the validator's cached report, so text, programmatic inspection, and plotting describe the same validation result.

## Compilation behavior

Requesting {py:attr}`jayrun.GraphDefinition.compiled_graph` performs property validation before producing the execution plan. A mismatched edge raises `ValueError`; unknown edges are accepted.

Run validation explicitly when applications need to present diagnostics before context creation or engine startup. Explicit validation and compilation use the same compatibility model.

## Plotting with PyVis

Install the optional dependency:

```bash
python -m pip install "jayrun[plotting]"
```

Save an interactive validation graph:

```python
from jayrun.validation import GraphValidator

plot_path = GraphValidator(graph).plot.save("graph_validation.html")
print(plot_path)
```

`plot.build()` returns the underlying `pyvis.network.Network`. `plot.show()` opens a browser; `plot.show(notebook=True)` returns an IPython `IFrame`.

Nodes represent entries, operators—including output-free sinks—and terminal artifacts. Edges represent artifact movement, with mismatch and unknown states visually distinguished. A sink node may therefore have no outgoing edge.

The plot is diagnostic only. Node coordinates come from graph layout positions, while artifact rows provide stable vertical ordering. Saving or displaying a plot does not compile, execute, or mutate the graph.

:::{note}
Use the text report for automated logs and CI diagnostics. Use the PyVis plot when cross-flow synchronization or several simultaneous property results are easier to understand visually.
:::

## Common diagnostics

| Result | Meaning | Correction |
|---|---|---|
| Type mismatch | Python type declarations differ | Align `TypeProperty` on producer and consumer |
| Dtype mismatch | Declared dtype alternatives do not overlap | Correct one side or add a supported alternative |
| Shape mismatch | Rank or a concrete dimension differs | Align dimensions or use an input-side `None` wildcard |
| Device/backend mismatch | Location declarations differ | Align the declared contract and actual placement behavior |
| Unknown source | Consumer declares a property but producer does not | Add the corresponding output property when it is known |
| Unknown target | Producer declares a property but consumer does not | Add an input property when the consumer has a constraint |

Do not silence a true mismatch by removing metadata unless the compatibility is genuinely unconstrained. An unknown result trades early assurance for flexibility.

## API reference

```{py:class} ArtifactProperty(value)
Base contract for one artifact-field compatibility property.
```

```{py:method} ArtifactProperty.accepts(output) -> bool
Return whether this target-side property accepts a source-side property of the same type.
```

```{py:class} TypeProperty(value)
Require the same Python type object.
```

```{py:class} DTypeProperty(value)
Accept one dtype or a non-empty iterable of alternative dtypes.
```

```{py:class} ShapeProperty(value)
Require equal rank and compatible dimensions, using input-side `None` as a wildcard.
```

```{py:class} DeviceProperty(value)
Require an equal device-name string.
```

```{py:class} BackendProperty(value)
Require an equal backend-name string.
```

```{py:class} jayrun.validation.GraphValidator(graph)
Validate artifact-property compatibility and expose reporting and plotting helpers.

:param jayrun.GraphDefinition graph: Graph declaration to validate.
:raises TypeError: If `graph` is not a `GraphDefinition`.
```

```{py:method} jayrun.validation.GraphValidator.validate() -> jayrun.core.validation.GraphValidationReport
Return the cached graph validation report.
```

```{py:attribute} jayrun.validation.GraphValidator.report
Text reporter for the cached validation result.
```

```{py:attribute} jayrun.validation.GraphValidator.plot
PyVis plotting helper for the cached validation result.
```

```{py:class} jayrun.core.validation.ValidationStatus
Compatibility enumeration containing `MATCH`, `MISMATCH`, and `UNKNOWN`.
```

```{py:class} jayrun.core.validation.PropertyValidationReport
Immutable result for one property comparison.
```

```{py:class} jayrun.core.validation.ArtifactValidationReport
Immutable aggregate property result for one artifact edge.
```

```{py:class} jayrun.core.validation.GraphValidationReport(nodes, edges)
Immutable nodes and edges produced by graph validation.
```

```{py:attribute} jayrun.core.validation.GraphValidationReport.valid
:type: bool

Whether the report contains no mismatched edges.
```

```{py:attribute} jayrun.core.validation.GraphValidationReport.mismatched_edges
Edges containing one or more incompatible declared properties.
```

```{py:attribute} jayrun.core.validation.GraphValidationReport.unknown_edges
Edges whose compatibility cannot be decided completely from declarations.
```

```{py:class} jayrun.core.validation.GraphEdge
Immutable validation edge joining an artifact producer to a consumer or terminal node.
```

```{py:attribute} jayrun.core.validation.GraphEdge.edge_type
:type: jayrun.core.validation.EdgeType

Structural classification of the edge.
```

```{py:attribute} jayrun.core.validation.GraphEdge.source
:type: int

Source node identifier within the validation report.
```

```{py:attribute} jayrun.core.validation.GraphEdge.target
:type: int

Target node identifier within the validation report.
```

```{py:attribute} jayrun.core.validation.GraphEdge.validation
Artifact-property report, or `None` when the edge lacks a producer/consumer field pair.
```

```{py:attribute} jayrun.core.validation.GraphEdge.mismatched
:type: bool

Whether at least one compared property mismatches.
```

```{py:attribute} jayrun.core.validation.GraphEdge.unknown
:type: bool

Whether compatibility cannot be fully decided from declarations.
```

```{py:class} jayrun.core.validation.NodeType
Validation-node enumeration containing `ENTRY`, `OPERATOR`, and `EXIT`.
```

```{py:class} jayrun.core.validation.EdgeType
Validation-edge enumeration containing `ENTRY`, `INTERMEDIATE`, `EXIT`, and `UNUSED`.
```

```{py:class} jayrun.core.validation.ValidationReporter
Format, print, or save one graph validation report.
```

```{py:method} jayrun.core.validation.ValidationReporter.format() -> str
Format the complete report as text.
```

```{py:method} jayrun.core.validation.ValidationReporter.print() -> None
Print the formatted report.
```

```{py:method} jayrun.core.validation.ValidationReporter.save(path=None) -> pathlib.Path
Write the report to a UTF-8 text file.
```

```{py:class} jayrun.core.validation.GraphPlotter
Build, save, or display an interactive PyVis validation graph.
```

```{py:method} jayrun.core.validation.GraphPlotter.build() -> object
Build and return a `pyvis.network.Network`.

:raises RuntimeError: If PyVis is not installed.
```

```{py:method} jayrun.core.validation.GraphPlotter.save(path=None) -> pathlib.Path
Write the interactive graph to HTML and return its absolute path.

:raises RuntimeError: If PyVis is not installed.
```

```{py:method} jayrun.core.validation.GraphPlotter.show(name="graph_validation.html", notebook=False) -> object | None
Write and display the interactive graph.

:param str name: Output filename.
:param bool notebook: Return an IPython `IFrame` instead of opening a browser.
:raises RuntimeError: If PyVis is unavailable, or IPython is unavailable in notebook mode.
```

:::{versionadded} 0.1.0
Artifact-property reports, validation diagnostics, and PyVis plotting were introduced.
:::

Next, read {doc}`Operational Interfaces <../interfaces/index>` for the runtime capabilities injected into operators and resource setup.
