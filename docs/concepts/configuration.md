(configuration)=
# Configuration

Configuration is context-scoped input data that remains fixed while a graph submission executes. {py:class}`jayrun.ConfigField` declares a value required by an operator or resource, and {py:class}`jayrun.ConfigContext` supplies those values for one confirmed graph.

Configuration belongs in Jayrun's data model beside artifacts, but the two serve different roles: artifacts flow through operators and may be regenerated, cleared, or retained; configuration supplies stable parameters that executions read without transforming.

This page describes configuration declarations and values independently. Field ownership is explained in {doc}`Operators and Executions <../components/operators-and-executions>`, while graph registration and inspection are explained in {doc}`Graph Construction <../components/graph-construction>`.

## Configuration model

Configuration separates reusable declarations from submission values:

| Object | Ownership | Purpose |
|---|---|---|
| {py:class}`jayrun.ConfigField` | Operator or resource declaration | Defines a named, typed requirement |
| {py:class}`jayrun.core.graph.definition.ConfigDefinition` | Confirmed graph | Describes one registered field and assigns a graph-local ID |
| {py:class}`jayrun.ConfigContext` | Submitted context | Holds values for one graph submission |
| {py:class}`jayrun.Data` | Runtime execution | Wraps each resolved value exposed to a component |

Use configuration for parameters that describe one submission but do not participate in graph data flow. Use an {py:class}`jayrun.Artifact` when a value has producers and consumers or requires artifact lifecycle, placement, or lineage behavior.

(config-field)=
## `ConfigField`

Declare config fields directly in an operator or resource constructor:

```python
from jayrun import ConfigField


self.factor = ConfigField(
    value_type=float,
    required=False,
    default=1.0,
)
```

`value_type` must be a hashable Python type. A required field cannot define a default. An optional field may define a default or remain unresolved.

During execution, a resolved config value is injected as {py:class}`jayrun.Data`:

```python
def execute(self) -> object:
    return self.input_data.value * self.factor.value
```

An optional field with neither a supplied value nor a default is injected as `None`. Test the field itself before accessing `.value` in that case.

(config-definition)=
## `ConfigDefinition`

After a graph's resource selection is finalized, each registered config field has an immutable {py:class}`jayrun.core.graph.definition.ConfigDefinition`. It records:

| Attribute | Meaning |
|---|---|
| `config_id` | Integer identifier local to the graph |
| `owner` | Display representation of the owning operator or resource |
| `attribute_name` | Python attribute under which the field was declared |
| `layout_position` | Position of the owning component in the graph |
| `name`, `description`, `required` | Copied declaration metadata |
| `value_type`, `default` | Config-specific declaration metadata |

Definitions are produced by graph inspection:

```python
required = graph.inspect.configs.required
optional = graph.inspect.configs.optional
all_configs = graph.inspect.configs.all
```

Applications do not construct config definitions. They declare `ConfigField` objects; the graph later creates definitions for stable inspection and reference. See {ref}`graph-inspection` for the complete inspection lifecycle.

The source `ConfigField`, its `ConfigDefinition`, and its `config_id` all refer to the same registered field. Definitions and IDs belong only to the graph that created them. Use a direct field reference in ordinary Python code, a definition in inspection-driven tooling, and an integer ID for serialized graph-local configuration.

Config definitions become complete only after resources are bound because resources may declare their own config fields. See {ref}`graph-inspection` for this two-phase inspection model.

## `ConfigContext`

A {py:class}`jayrun.ConfigContext` belongs to one confirmed graph:

```python
from jayrun import ConfigContext


configs = ConfigContext(graph=graph)
configs.set({operator.factor: 2.0})
```

In `ConfigContext.set(configs)`, `configs` is a mapping from config references to raw values. Accepted keys are a `ConfigField`, its graph-local `ConfigDefinition`, or its graph-local integer ID:

```python
definition = next(
    item
    for item in graph.inspect.configs.all
    if item.attribute_name == "factor"
)

configs.set({operator.factor: 2.0})
# Equivalent reference forms:
configs.set({definition: 3.0})
configs.set({definition.config_id: 4.0})
```

The mapping values are raw configuration values, not {py:class}`jayrun.Data`; `set()` validates and wraps them. Several keys may not resolve to the same field in one call.

`set()` updates selected values; it does not replace the complete context. Supplied values must match the field's declared type and be hashable. Unknown IDs, foreign definitions, and fields that do not belong to the graph are rejected.

```python
assert configs.validate()
assert configs.get(operator.factor).value == 2.0
```

`get()` returns {py:class}`jayrun.Data` for a supplied or defaulted value, and `None` for an unresolved optional field. `validate()` returns whether every required field resolves to a value.

:::{important}
The config context and artifact context submitted together must belong to the same graph. Jayrun forks both contexts at submission, so later changes to caller-owned mappings do not change queued work.
:::

## Required, optional, and default values

Resolution follows this order:

1. A value explicitly supplied in the config context is used.
2. Otherwise, the field default is used when one exists.
3. Otherwise, an optional field resolves to `None`.
4. Otherwise, the required configuration is incomplete and submission validation fails.

Defaults belong to field declarations and do not appear in `ConfigContext.instances` unless explicitly supplied. Use `get()` when code needs the effective value.

## Providing values in Python

Python is the primary configuration path. It preserves value types, IDE assistance, immediate validation, and direct references to declaration fields:

```python
configs = ConfigContext(graph=graph)
configs.set(
    {
        preprocess.batch_size: 32,
        train.learning_rate: 0.001,
    }
)

run = engine.submit(artifacts, configs)
```

Because `set()` is additive, values may be assembled in stages before submission:

```python
configs.set({preprocess.batch_size: 32})
configs.set({train.learning_rate: 0.001})
```

## Configuration inspection

After resource selection is finalized, the confirmed graph exposes the configuration definitions described above:

```python
required = graph.inspect.configs.required
optional = graph.inspect.configs.optional
all_configs = graph.inspect.configs.all
```

Resource config fields cannot be finalized until resources are selected. Accessing `graph.inspect.configs` before that point raises `RuntimeError`; `graph.inspect.complete` reports whether inspection is complete.

Graph-local IDs are useful for generated forms and serialized values. Direct field references remain clearer in ordinary Python code.

## Lazy YAML configuration

YAML support serializes only {py:class}`jayrun.ConfigContext` values. Install it separately:

```bash
python -m pip install "jayrun[yaml]"
```

Export a self-describing template or populated context:

```python
yaml_text = configs.to_yaml()
```

The generated structure resembles:

```yaml
configs:
  0:
    name: factor
    description: null
    owner: "Scale(name='scale')"
    required: false
    layout_position: [0, 0]
    attribute_name: factor
    value_type: float
    default: 1.0
    value: 2.0
```

Load values into a config context for the same graph:

```python
loaded = ConfigContext(graph=graph)
loaded.load_yaml(yaml_text)
```

Loading uses only each integer config ID and its `value`. Descriptive metadata does not alter field declarations. Existing values absent from the YAML remain unchanged because loading follows `set()` update semantics.

YAML is imported only when `to_yaml()` or `load_yaml()` is called. Importing Jayrun does not require PyYAML.

:::{important}
YAML does not configure execution settings, resources, or graph structure. It is a serialization format for graph-scoped configuration values only.
:::

## Configuration validation

Validation occurs at several boundaries:

- `ConfigField` validates declaration metadata, value type, and default.
- `ConfigContext.set()` validates references, runtime types, `None`, and hashability.
- `ConfigContext.validate()` checks that required values resolve.
- Submission checks that artifact and config contexts belong to the same graph.

Invalid configuration is rejected before normal graph execution begins. Configuration values are copied structurally into the submitted context; payload objects are not deep-copied.

## API reference

```{py:class} jayrun.ConfigField(*, name=None, description=None, required=True, value_type, default=None)
Declare one context-scoped configuration value on an operator or resource.

:param name: Optional field name.
:type name: str | None
:param description: Optional field description.
:type description: str | None
:param bool required: Whether a value must resolve before submission. A required field cannot define a default.
:param type value_type: Required hashable Python type for supplied values.
:param default: Optional default value matching `value_type`.
:raises TypeError: If metadata, `value_type`, or `default` has an invalid type.
:raises ValueError: If a required field defines a default.
```

```{py:attribute} jayrun.ConfigField.value_type
:type: type

Required Python type for supplied values.
```

```{py:attribute} jayrun.ConfigField.default
Default value, or `None` when no default is declared.
```

```{py:class} jayrun.core.graph.definition.ConfigDefinition(*, config_id, owner, required, layout_position, attribute_name, value_type, default, name, description)
Immutable graph-local description of one registered config field.

:param int config_id: Integer identifier local to the owning graph.
:param str owner: Display representation of the field owner.
:param bool required: Whether a value must resolve.
:param tuple layout_position: Graph layout position of the owner.
:param str attribute_name: Attribute under which the field was declared.
:param type value_type: Accepted runtime value type.
:param default: Declared default, or `None`.
```

```{py:class} jayrun.ConfigContext(*, graph, name=None, description=None)
Hold configuration values for one confirmed graph.

:param jayrun.GraphDefinition graph: Confirmed graph whose config fields may be referenced.
:param name: Optional context name.
:type name: str | None
:param description: Optional context description.
:type description: str | None
:raises TypeError: If arguments have invalid types.
:raises RuntimeError: If the graph is not confirmed.
```

```{py:method} jayrun.ConfigContext.set(configs) -> None
Set or replace selected configuration values.

:param collections.abc.Mapping configs: `ConfigField`, `ConfigDefinition`, or integer config ID keys mapped to raw values.
:raises TypeError: If a reference or value has an invalid type, or a value is not hashable.
:raises KeyError: If a reference does not belong to the graph.
:raises ValueError: If several keys resolve to one field or a required value is `None`.
```

```{py:method} jayrun.ConfigContext.get(config) -> jayrun.Data | None
Return a supplied or defaulted value, or `None` for an unresolved optional field.

:raises TypeError: If the reference type is invalid.
:raises KeyError: If the reference does not belong to the graph.
```

```{py:method} jayrun.ConfigContext.validate() -> bool
Return whether every required config field resolves to a value.
```

```{py:method} jayrun.ConfigContext.to_yaml() -> str
Serialize graph config metadata and current values as YAML.

:raises ModuleNotFoundError: If PyYAML is not installed.
```

```{py:method} jayrun.ConfigContext.load_yaml(content) -> None
Load config values by graph-local integer ID.

:param str content: YAML document containing a `configs` mapping.
:raises ModuleNotFoundError: If PyYAML is not installed.
:raises TypeError: If the document shape, IDs, or loaded values have invalid types.
:raises KeyError: If an ID does not belong to the graph.
:raises ValueError: If an entry lacks `value` or violates field rules.
```

```{py:attribute} jayrun.ConfigContext.instances
Read-only mapping from config fields to explicitly supplied {py:class}`jayrun.Data` values. Defaults are resolved by `get()`.
```

```{py:attribute} jayrun.ConfigContext.graph
:type: jayrun.GraphDefinition

Graph declaration that owns the referenced config fields.
```


Next, read {doc}`Resources <resources>` to define runtime-managed data and capabilities. Execution policy is configured separately; see {doc}`Execution Settings <../settings/execution-settings>`.
