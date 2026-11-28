# Inspect a graph and print its report

Use inspection when application code needs graph metadata, a textual report for human review, and structured JSON for AI-assisted review or reconstruction. None of these runs the graph.

With the graph from the [guided workflow](../../start/first-graph.md):

```python
for artifact in graph.inspect.artifacts.all:
    print(artifact.artifact_id, artifact.name, artifact.is_exit)

print(graph.report.format(compact=True))
graph.report.save("graph-report.txt")
```

The inspected artifacts include `source` and `result`. `result` is an exit because its final value has no consumer. Their numeric IDs are local to this graph; use the declarations as submission keys unless you are building a generic tool.

The full report adds component field declarations and contracts. The compact report keeps the structure, bindings and validation findings while reducing field detail. `graph.report.print()` writes directly to standard output.

## Find required values and missing resources

After confirmation, `graph.inspect.configs.required` lists required configurations. Before confirmation, `graph.inspect.resources.missing` identifies required resource fields without bindings. `graph.inspect.resources.shared` groups fields bound to the same resource declaration; runtime reuse also depends on effective configuration.

For example, a generic submission form can show a configuration field's `attribute_name`, `value_type` and `default`. Keep the inspected definition itself as the key rather than attempting to recreate identity from its display name.

## Inspect validation separately

```python
validation = graph.validate()
for edge in validation.mismatched_edges:
    print(edge.edge_id, edge.validation)
```

A mismatch describes a known incompatibility between declared producer and consumer properties. `unknown_edges` contains relationships where available declarations do not establish compatibility. Read [validation](../graphs/validation.md) for an executable mismatch example and its correction.

Next: [visualize a declaration](graphs.md). Full returned types: [inspection reference](../../reference/inspection.md).

## Export a self-contained declaration for an AI agent

After confirmation, use the structured report when another agent needs to understand
or rebuild the graph without its original construction code:

```python
text = graph.report.to_json()  # compact JSON, with complete supplied descriptions
payload = graph.report.to_dict()  # detached data; editing it cannot change the graph
graph.report.save("graph-declaration.json", format="json", compact=True)
```

Give a graph an authored purpose when constructing it:

```python
graph = GraphDefinition(
    *flows,
    entry_flows=entry_flows,
    name="Calibrated branch sum",
    description="Duplicate an input integer, calibrate both branches, and add their results.",
)
```

The developing agent supplies meaningful descriptions for the graph, operators,
artifacts, fields and resources. Jayrun preserves these strings verbatim, including
whitespace and Unicode; it does not invent purpose or infer algorithms from code.
Absent names/descriptions appear as null. Graph names/descriptions do not change
structural `graph_id` values. Descriptions state intent, not verified behavior.

The JSON schema identifier is `jayrun.declaration/2`. Consumers must check it and
reject unknown schemas rather than interpreting them as version 1. The document
contains no execution logs, timings, credentials supplied at submission, result
values or effective authority. It is a declaration, not a configured run or checkpoint.

| Section | Meaning |
|---|---|
| `graph` | Authored name/description, graph version and structural ID |
| `components` | Python type references, resolved component versions, version-declaring classes and requirements |
| `artifacts` | Distinct identities, graph-local artifact IDs, descriptions, boundary roles and serializer references |
| `operators` | Distinct declarations, descriptions, named input fields, ordered outputs, contracts and resource bindings |
| `resources`, `serializers` | Distinct bound component declarations; repeated references preserve reuse |
| `configs` | Graph-local config ID, owner declaration, field name, description, type, required flag and default |
| `flows` | Nested flows, authored metadata, carried artifacts and ordered operator/flow references |
| `root_flows`, `entry_flows` | Exact graph constructor flow order and entry selection |
| `timing_configs` | Selected configuration references, or null for the existing default selection |
| `limitations` | Redacted defaults and unsupported construction information, with paths and reasons |

Local references `a0`, `o0`, `r0`, `s0`, `c0`, `f0` and `t0` identify artifacts,
operators, resources, serializers, configs, flows and component types respectively.
The same operator reference in several flows means the same declaration; distinct
references remain distinct even when metadata matches. An input/output with
`bound: true` and `artifact: null` is explicitly disconnected/disabled. A null
resource binding means no resource was selected. Artifact-free roots have a null
flow artifact. Ordered flows preserve feedback and repeated operator occurrences.

Strings, booleans and nulls retain their JSON scalar form. Configuration numbers
use `{"int": "0x1"}` or `{"float": "-0x0.0p+0"}`. Tuples use `{"tuple": [...]}` recursively.

Python type contracts use `{"python_type": "module.QualifiedName"}`. Unsupported
values use `{"unavailable_type": "module.QualifiedName"}` plus a limitation.
Sensitive defaults identified by configuration field names use `{"redacted": true}`;
provide those values externally. Authored descriptions themselves are not scrubbed:
do not place secrets in descriptive text. The exporter never truncates supported
values or descriptions; it rejects exports exceeding 32 MiB. `to_json(indent=2)`
changes only whitespace. The existing text formatter remains a human summary and
may summarize values; use JSON for reconstruction.

To reconstruct, resolve the referenced component types from the application's
pinned collection, create artifacts and distinct component instances, bind named
inputs/ordered outputs, rebuild nested/root flows, bind resources/serializers and
apply timing selections before confirming. Preserve the config ID-to-owner/field
mapping when pairing this report with `ConfigContext.to_yaml(graph)`; never apply
values to reordered IDs by guesswork. Selected run values stay in that separate
configuration document.

The report also supports implementing replacement operators from authored intent
without their original source. Exact original algorithms cannot be recovered unless
they were specified. Extra constructor arguments or instance state are flagged as
limitations: obtain an explicit construction recipe instead of guessing. An empty
limitations list does not establish that arbitrary closure/class state or behavior
was fully specified. The component collection identity and executable package/model
bindings remain application-owned evidence.

Compare full declarations and bindings after rebuilding; successful validation or
matching structural IDs alone does not establish equivalence. Resource declaration
reuse is distinct from runtime cache reuse, which depends on class identity, effective
configuration and concurrency requirements. This export does not certify model thread
safety or execution outcomes. Registry reports retain their existing text interface;
export each individual graph for declaration evidence.

In declaration version 2 every configuration integer and finite float default
uses a tagged hexadecimal string, including tuple members. Comparing detached
records distinguishes booleans, integers, floats and the sign of zero, even in
JSON readers with limited numeric precision. Version 1 exports remain viewable.
Graph fingerprints continue to exclude defaults and execution bindings.
