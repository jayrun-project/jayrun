(data-model)=
# Data Model

Jayrun separates reusable declarations from graph-local descriptions and runtime values. This separation is the key to understanding artifacts, configuration, resources, operators, and graphs without treating them as one object.

The same concept normally passes through these layers:

```text
Declaration
    A reusable Artifact, ConfigField, ResourceField, or BaseResource
        ↓ bound to an operator or registered in a graph
Graph-local definition
    An immutable description with a graph-local integer ID
        ↓ resolved for one submission or runtime load
Runtime data
    Data(value, placement)
```

No single page can remove every relationship between these layers. Instead, each data-model page describes the object itself and links to the component that gives it its wider meaning:

| Layer | Objects | What can be understood independently | Where the relationship is completed |
|---|---|---|---|
| Runtime value | {py:class}`jayrun.Data` | Payload and placement metadata | Artifact values, resolved configuration, and loaded resources |
| Artifact declaration | {py:class}`jayrun.Artifact` | Identity of flowing data | {doc}`operator ports <../components/operators-and-executions>` and {doc}`artifact flows <../components/graph-construction>` |
| Configuration declaration | {py:class}`jayrun.ConfigField` | Typed, context-scoped input | Its operator or resource owner and the confirmed graph |
| Resource declaration | {py:class}`jayrun.BaseResource`, {py:class}`jayrun.ResourceField` | Setup, teardown, and dependency requirements | {doc}`resource binding <../components/graph-construction>` and runtime acquisition |
| Graph definition | {py:class}`jayrun.core.graph.definition.ArtifactDefinition`, {py:class}`jayrun.core.graph.definition.ConfigDefinition`, {py:class}`jayrun.core.graph.definition.ResourceDefinition` | Immutable graph-local identity and metadata | {ref}`graph-inspection` |

## Declarations

Declarations are the objects application code creates and connects:

- an {py:class}`jayrun.Artifact` identifies data that can flow through operators;
- an {py:class}`jayrun.ArtifactField` declares an operator artifact port;
- a {py:class}`jayrun.ConfigField` declares a typed configuration requirement;
- a {py:class}`jayrun.ResourceField` declares an operator resource dependency; and
- a {py:class}`jayrun.BaseResource` declares how runtime-managed data is loaded and torn down.

Declarations are reusable Python objects. Their names are descriptive labels, not graph-wide identifiers.

## Bindings

A binding gives a declaration a relationship:

- constructing an operator binds artifacts or `None` to its artifact fields;
- constructing a graph registers artifacts and every field owned by its operators;
- binding resources associates graph resource fields with resource declarations.

An {py:class}`jayrun.ArtifactField`, {py:class}`jayrun.ConfigField`, or {py:class}`jayrun.ResourceField` belongs to its operator or resource declaration. It is not a standalone graph value. See {doc}`Operators and Executions <../components/operators-and-executions>` for field ownership and runtime injection.

## Graph-local definitions and IDs

When Jayrun registers a declaration in a graph, it creates an immutable definition:

| Source declaration | Graph-local definition | ID attribute |
|---|---|---|
| {py:class}`jayrun.Artifact` | {py:class}`jayrun.core.graph.definition.ArtifactDefinition` | `artifact_id` |
| {py:class}`jayrun.ConfigField` | {py:class}`jayrun.core.graph.definition.ConfigDefinition` | `config_id` |
| {py:class}`jayrun.ResourceField` | {py:class}`jayrun.core.graph.definition.ResourceDefinition` | `resource_id` |

A definition is a graph-owned description of its source declaration. It does not replace the declaration, carry runtime data, or have global identity. Its integer ID is meaningful only within the graph that created it.

Definitions make graph inspection stable and serializable. They record names, ownership, layout position, required status, and type-specific metadata without exposing mutable framework internals. See {ref}`graph-inspection` for the inspection collections that return them.

## Choosing a reference form

Some graph-bound APIs accept a source declaration or field, its definition, or its integer ID. All three resolve to the same registered object:

```python
definition = graph.inspect.artifacts.entry[0]

artifacts.set({input_artifact: value})
artifacts.set({definition: value})
artifacts.set({definition.artifact_id: value})
```

Choose the form that matches the caller:

- use declarations and fields in ordinary Python application code;
- use definitions while working with graph inspection results;
- use integer IDs in serialized documents, generated forms, or external tools.

Definitions and IDs are graph-local. A foreign definition or unknown ID is rejected. Supplying two aliases for the same declaration in one mapping is also rejected because the intended value would be ambiguous.

:::{important}
An operator field is not interchangeable with every other declaration. {py:meth}`jayrun.ArtifactContext.set` accepts an `Artifact`, not an operator's `ArtifactField`; {py:meth}`jayrun.ConfigContext.set` accepts a `ConfigField`; and {py:meth}`jayrun.GraphDefinition.bind_resources` accepts a `ResourceField`.
:::

## Runtime `Data`

{py:class}`jayrun.Data` is the common runtime container. It pairs a payload with placement metadata and is used for artifact values, resolved configuration, and loaded resources.

`Data` does not identify what the value means in the graph. That meaning still comes from the artifact, config field, or resource field through which the container is accessed. See {doc}`Data <data>` for its complete contract.

## Reading order

Read the remaining data-model pages in this order:

1. {doc}`Data <data>` for the common runtime container.
2. {doc}`Artifacts and Data Flow <artifacts-and-data-flow>` for flowing graph data.
3. {doc}`Configuration <configuration>` for context-scoped values.
4. {doc}`Resources <resources>` for runtime-managed shared data.

Then read {doc}`Operators and Executions <../components/operators-and-executions>` and {doc}`Graph Construction <../components/graph-construction>`. The separate {doc}`Graph Validation <../components/graph-validation>` chapter explains artifact-property compatibility in depth.
