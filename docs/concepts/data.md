(data)=
# Data

{py:class}`jayrun.Data` is Jayrun's immutable runtime container. It pairs a payload with the placement metadata that describes where the payload resides.

```python
from jayrun import Data
from jayrun.placement import CPU_PLACEMENT

data = Data(value=result)
```

`Data` is shared by the whole data model:

- artifact inputs and outputs are exposed as `Data`;
- resolved configuration values are exposed as `Data`; and
- resource `setup()` returns `Data`, which is later passed to `teardown()`.

The surrounding declaration gives the payload its meaning. `Data` itself does not identify an artifact, config field, resource, graph, or context.

## Attributes

| Attribute | Meaning |
|---|---|
| `value` | The runtime payload |
| `placement` | The {py:class}`Placement` or {py:class}`PlacementGroup` associated with the payload |

The default placement is {py:data}`CPU_PLACEMENT`:

```python
data = Data(value=result)
assert data.placement is CPU_PLACEMENT
```

The container is frozen, but Jayrun does not copy or freeze `value`. If the payload is mutable, ordinary Python references can still mutate it.

## Automatic and explicit wrapping

Application-facing context setters accept raw payloads:

```python
artifacts.set({input_artifact: input_value})
configs.set({operator.batch_size: 32})
```

{py:meth}`jayrun.ArtifactContext.set` and {py:meth}`jayrun.ConfigContext.set` wrap those values in CPU `Data`. Pass the payload itself to these methods, not an existing `Data` container.

Connected operator outputs may be raw values or explicit `Data`. A raw output is wrapped automatically with CPU placement:

```python
def execute(self) -> object:
    return transform(self.input_data.value)
```

Return `Data` explicitly when the result carries non-default placement metadata:

```python
def execute(self) -> Data:
    placement = self.placement.cuda(memory_gb=2)
    value = move_to_cuda(self.input_data.value, placement.device_id)
    return Data(value=value, placement=placement)
```

An operator with no connected output returns `None`; that return is completion of the step, not artifact `Data`. An unbound output position never produces a `Data` container or an artifact result. See {ref}`artifact-output-bindings` and {ref}`terminal-operators`.

Resource setup is stricter: {py:meth}`jayrun.BaseResource.setup` must return exactly one `Data` instance.

## Placement metadata

Placement metadata describes location and preserves the corresponding accelerator-capacity lease. It does not move, copy, shard, or otherwise transform the payload. The component creating the payload is responsible for placing it on the reported device.

Attach accelerator placement to every `Data` whose payload depends on that reservation. See {doc}`Placement Interface <../interfaces/placement>` for requesting capacity and {doc}`Placement and Capacity <../runtime/placement-and-capacity>` for lease lifetime.

## Lifetime

`Data` lifetime depends on its owner:

- artifact data follows artifact clearing and retention rules;
- configuration data belongs to one submitted context;
- resource data remains cached until safe eviction or runtime shutdown.

See {doc}`Scope and Lifetime Model <scope-and-lifetime>` for ownership and {doc}`Artifacts and Data Flow <artifacts-and-data-flow>`, {doc}`Configuration <configuration>`, and {doc}`Resources <resources>` for the specific lifecycle contracts.

## API reference

```{py:class} jayrun.Data(value, placement=CPU_PLACEMENT)
Immutable runtime container pairing a payload with placement metadata.

:param value: Runtime payload. Jayrun does not copy or validate the payload.
:type value: object
:param placement: Placement associated with the payload.
:type placement: Placement | PlacementGroup
:raises TypeError: If `placement` is not a `Placement` or `PlacementGroup`.
```

```{py:attribute} jayrun.Data.value
Runtime payload.
```

```{py:attribute} jayrun.Data.placement
:type: Placement | PlacementGroup

Placement metadata associated with the payload.
```

:::{versionadded} 0.1.0
The common runtime data container was introduced.
:::

Next, read {doc}`Artifacts and Data Flow <artifacts-and-data-flow>` to see how runtime data is identified and moved through a graph.
