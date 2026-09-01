(resources)=
# Resources

Resources represent reusable, stateful data or capabilities that are expensive to create for every operator invocation. A resource declaration describes how to load and tear down that data; Jayrun owns the loaded instance at runtime and may share it across contexts.

Resources belong to the data model because operators receive their loaded values as {py:class}`jayrun.Data`. Unlike artifacts, resource data does not flow along graph edges. It is addressed through {py:class}`jayrun.ResourceField` declarations and managed by runtime lifetime rules.

This page separates the resource declaration, the operator field, the graph-local field definition, and the loaded runtime data. See {doc}`Operators and Executions <../components/operators-and-executions>` for field ownership and {doc}`Graph Construction <../components/graph-construction>` for binding resources into a graph.

## Resource lifetime

Resource lifetime has two distinct layers:

| Layer | Owner | Lifetime |
|---|---|---|
| Resource declaration | Application | Reusable Python object, independent of engine execution |
| Loaded resource data | Engine runtime | From successful setup until safe eviction or engine shutdown |

Loading is demand-driven. When an operator becomes eligible, Jayrun resolves its bound resource fields. If a matching resource is already available, setup is skipped. Otherwise, one setup execution creates the loaded data while matching consumers wait.

After the operator releases the resource, the loaded data normally remains cached. It can be acquired by later operators or contexts without running setup again.

## `BaseResource`

Every resource subclasses {py:class}`jayrun.BaseResource`, declares configuration fields in `__init__()`, and implements `setup()` and `teardown()`:

```python
from jayrun import BaseResource, ConfigField, Data


class ModelResource(BaseResource):
    def __init__(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.model_path = ConfigField(value_type=str, required=True)

    def setup(self) -> Data:
        model = load_model(self.model_path.value)
        return Data(value=model)

    def teardown(self, data: Data) -> None:
        close_model(data.value)
```

The constructed object is an immutable declaration. Jayrun invokes the unbound setup method on a runtime proxy containing config values and operational interfaces.

:::{important}
Arbitrary constructor attributes are not copied to the setup proxy and do not participate in cache identity. Declare runtime-varying inputs with {py:class}`jayrun.ConfigField`, or use class-level constants and module-level helper functions.
:::

Resource declarations may define class-level `requirements` using standard package requirement strings. These requirements join the graph specification after resource binding.

(resource-field)=
## `ResourceField`

Operators declare resource dependencies with {py:class}`jayrun.ResourceField`:

```python
from jayrun import ResourceField


self.model = ResourceField(
    required=True,
    parallel_safe=False,
)
```

Bind the field while constructing the graph:

```python
model_resource = ModelResource(name="model")
graph.bind_resources({inference.model: model_resource})
```

At execution time, the field contains the loaded {py:class}`jayrun.Data`:

```python
def execute(self) -> object:
    return self.model.value(self.input_data.value)
```

A required field must be bound before graph confirmation. An optional field may remain unbound; in that case it is not attached to the operator execution proxy.

(resource-definition)=
## `ResourceDefinition`

When an operator's resource field is registered in a graph, Jayrun creates an immutable {py:class}`jayrun.core.graph.definition.ResourceDefinition`. The definition describes the **field dependency**, not the `BaseResource` later bound to it.

| Attribute | Meaning |
|---|---|
| `resource_id` | Integer identifier local to the graph |
| `owner` | Display representation of the operator that owns the field |
| `attribute_name` | Operator attribute under which the field was declared |
| `layout_position` | Position of the owning operator |
| `name`, `description`, `required` | Copied field metadata |
| `parallel_safe` | Copied acquisition capability |

Resource definitions are available before binding:

```python
required = graph.inspect.resources.required
optional = graph.inspect.resources.optional
all_resources = graph.inspect.resources.all
```

Applications do not construct resource definitions. They declare `ResourceField` objects, and the graph creates definitions when it registers those fields. See {ref}`graph-inspection` for the inspection surface.

{py:meth}`jayrun.GraphDefinition.bind_resources` accepts a source `ResourceField`, its graph-local `ResourceDefinition`, or its graph-local integer ID:

```python
definition = next(
    item
    for item in graph.inspect.resources.all
    if item.attribute_name == "model"
)

graph.bind_resources({inference.model: model_resource})
# Equivalent reference forms for the same graph field:
# graph.bind_resources({definition: model_resource})
# graph.bind_resources({definition.resource_id: model_resource})
```

Use the field in normal Python construction, a definition in inspection-driven tooling, and the ID in serialized graph-local input. Unknown IDs, foreign definitions, and duplicate aliases for the same field are rejected.

See {ref}`graph-resource-binding` for confirmation behavior and optional fields.

## Resource setup

`setup()` must return exactly one {py:class}`jayrun.Data` instance. Raw objects and tuples are not accepted as resource setup results.

```python
def setup(self) -> Data:
    client = create_client(self.endpoint.value)
    return Data(value=client)
```

Define setup with `def` for thread-executor work or `async def` for event-loop work:

```python
async def setup(self) -> Data:
    client = await create_client(self.endpoint.value)
    return Data(value=client)
```

Setup receives the four {doc}`operational interfaces <../interfaces/index>`. It may store records, log metrics, inspect its context, or request placement capacity. Repetition is operator-only and is not available to resource setup.

Jayrun loads a resource only when the consuming operator can otherwise run. If the operator is skipped because a required artifact value is absent, its resource setup is skipped as well.

## Resource teardown

`teardown()` receives the exact {py:class}`jayrun.Data` returned by successful setup:

```python
def teardown(self, data: Data) -> None:
    data.value.close()
```

Teardown may also return an awaitable:

```python
async def teardown(self, data: Data) -> None:
    await data.value.aclose()
```

Resource config fields are available during teardown with the same resolved values used by setup. Operational interfaces are intentionally unavailable: teardown is runtime cleanup, not an execution scope exposed to user control.

Teardown runs when an idle cached resource is evicted or during engine shutdown. A teardown failure is recorded as a runtime cleanup failure. During eviction, the resource remains registered as ready if teardown fails; during shutdown, Jayrun continues attempting cleanup of other resources.

`teardown()` may contain only `pass` when the payload owns no explicit external or native resource. After successful teardown, Jayrun removes its cached reference to the `Data`; normal Python reference counting or garbage collection can then reclaim the payload once no other references remain. This does not guarantee immediate destruction.

Use explicit teardown for database connections, files, sockets, client sessions, thread pools, subprocesses, device allocations, or any object with a documented `close()`, `shutdown()`, or equivalent lifecycle method.

## Setup and teardown data

The setup result is the resource's runtime value and lifetime carrier:

```python
return Data(
    value=loaded_resource,
    placement=placement,
)
```

The `value` becomes available through every bound operator field. The `placement` identifies where the data lives and keeps accelerator capacity leased while the resource remains cached.

The same `Data` is later passed to teardown. Do not return a container whose payload has already been invalidated, and do not move placement-backed data without returning a new `Data` that describes its actual location.

## Shared resources

Loaded resources are cached by a runtime key containing:

1. the resource subclass;
2. the resolved values of its config fields, in declaration order; and
3. the binding field's `parallel_safe` value.

Declaration-object identity, name, and description are not part of this key. Two resource declarations with the same subclass, resolved configuration, and parallel-safety mode may therefore reuse one loaded instance—even across different graphs or contexts hosted by the same engine.

```python
first_graph.bind_resources({first_operator.model: model_resource})
second_graph.bind_resources({second_operator.model: model_resource})
```

Sharing ends at runtime shutdown. A new engine creates a new resource cache.

:::{warning}
Do not hide behavior-changing values in arbitrary resource attributes. If a value changes what setup loads, declare it as configuration so cache identity remains correct.
:::

## Parallel-safe resources

`ResourceField.parallel_safe` controls concurrent acquisition of the same cached instance.

- `True` allows several active operator executions to use it concurrently.
- `False` allows only one active operator execution at a time.

```python
self.client = ResourceField(parallel_safe=True)
self.model = ResourceField(parallel_safe=False)
```

`parallel_safe=True` is a declaration of capability, not automatic synchronization. The resource payload and every library it calls must actually support concurrent use.

Parallel-safety mode participates in the cache key. Bindings with different modes do not share the same cached entry.

## Resource acquisition and release

Acquisition is automatic:

1. The execution checks whether each resource key is ready.
2. Jayrun acquires every distinct required key before invoking the operator.
3. Loaded `Data` is attached to all fields using that key.
4. Jayrun releases the acquisitions after the invocation result is applied or the session is drained.

If several fields on one operator resolve to the same key, Jayrun acquires the cached resource once and attaches the same `Data` to each field.

A non-parallel-safe resource that is already in use temporarily blocks another consumer. The consumer remains undispatched until the resource becomes acquirable; user code does not poll or release it manually.

## Pinning and eviction

Pinning is an internal ownership mechanism that protects a loaded resource between preparation and operator acquisition. A resource cannot be evicted while pinned or actively used.

After all pins and active acquisitions are released, a resource is ready and evictable. Accelerator placement pressure may cause Jayrun to select idle placement-backed resources for teardown. Eviction favors resources by least recent access and creation time while minimizing the number of cache entries and excess capacity released.

There is no public pin, unpin, acquire, release, or evict API. Exposing those operations would let user code invalidate resources still required by another context.

## Failure during resource initialization

Setup failures follow the effective {py:class}`jayrun.settings.RetryPolicy`. While setup is retrying, the cache registration remains in the loading state and matching consumers continue to wait.

If retry succeeds, the returned `Data` becomes the shared cached value. If retries are exhausted, Jayrun cancels the loading registration and fails the context according to the configured failure policy.

:::{warning}
Teardown is available only after setup successfully returns and the `Data` is registered. If setup acquires external state and then raises, setup must clean up that partial state itself before propagating the exception.
:::

A failed setup does not publish partial resource data. Another later context may attempt a fresh registration after the failed one is removed.

## CPU model-resource example

This resource loads one CPU model and serializes its use:

```python
from jayrun import BaseResource, ConfigField, Data


class CpuModelResource(BaseResource):
    def __init__(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.model_path = ConfigField(value_type=str, required=True)

    def setup(self) -> Data:
        model = load_model(self.model_path.value)
        model.eval()
        return Data(value=model)

    def teardown(self, data: Data) -> None:
        pass
```

No placement request is needed: `Data` uses CPU placement by default. The empty teardown is appropriate only when the model owns no handle that requires explicit closure; Jayrun releases its cache reference after teardown.

Bind it through a non-parallel-safe field when the model implementation is not safe for simultaneous calls:

```python
self.model = ResourceField(parallel_safe=False)
```

## Database-resource example

A database connection requires explicit teardown even though its Python wrapper is garbage-collectable:

```python
import sqlite3

from jayrun import BaseResource, ConfigField, Data


class DatabaseResource(BaseResource):
    def __init__(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.path = ConfigField(value_type=str, required=True)

    def setup(self) -> Data:
        connection = sqlite3.connect(
            self.path.value,
            check_same_thread=False,
        )
        return Data(value=connection)

    def teardown(self, data: Data) -> None:
        data.value.close()
```

Bind this resource to a serialized field unless the selected database client explicitly supports concurrent operations through one connection:

```python
self.database = ResourceField(parallel_safe=False)
```

For production database concurrency, a thread-safe connection pool is usually the resource payload; its teardown should close the pool.

## GPU model-resource example

Placement-bearing resource data keeps GPU capacity reserved while the model remains cached:

```python
class CudaModelResource(BaseResource):
    def __init__(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.model_path = ConfigField(value_type=str, required=True)
        self.memory_gb = ConfigField(value_type=float, required=True)

    def setup(self) -> Data:
        placement = self.placement.cuda(memory_gb=self.memory_gb.value)
        device = f"cuda:{placement.device_id}"
        model = load_model(self.model_path.value).to(device)
        model.eval()
        return Data(value=model, placement=placement)

    def teardown(self, data: Data) -> None:
        pass
```

The declared reservation is capacity accounting; the model library still performs the actual device transfer. An explicit transfer back to CPU is not required for ordinary teardown. After `teardown()` returns, Jayrun removes its cached `Data` reference. If application code holds no other reference to the model, the model and its tensor storage become eligible for reclamation, and the placement carried by `Data` is released through its normal lifetime mechanism.

An empty teardown is therefore appropriate when the model owns no external handle that requires deterministic closure. A tensor library may retain released device blocks in its allocator cache for reuse by the same process; that is library-managed caching, not a live Jayrun resource. Use a library-specific cleanup operation only when the library requires one or the application has a concrete need to release that cached capacity. External references retained by application code also remain the application's responsibility.

See {ref}`placement-and-capacity` for allocator behavior and multi-device usage.

## API reference

```{py:class} jayrun.BaseResource(*, name=None, description=None, **kwargs)
Abstract immutable declaration for one runtime-managed resource.

:param name: Optional resource name.
:type name: str | None
:param description: Optional human-readable description.
:type description: str | None
:raises TypeError: If `name` or `description` has an invalid type.
```

```{py:attribute} jayrun.BaseResource.requirements
:type: tuple[str, ...]

Class-level package requirements contributed by the resource.
```

```{py:attribute} jayrun.BaseResource.name
:type: str | None

Optional declaration name.
```

```{py:attribute} jayrun.BaseResource.description
:type: str | None

Optional declaration description.
```

```{py:attribute} jayrun.BaseResource.config_fields
:type: tuple[jayrun.ConfigField, ...]

Resource configuration fields in declaration order.
```

```{py:attribute} jayrun.BaseResource.display_name
:type: str

Explicit name, or the resource subclass name when no name was supplied.
```

```{py:method} jayrun.BaseResource.setup() -> jayrun.Data
Load and return exactly one runtime resource value.

Subclasses may implement a synchronous method or an asynchronous coroutine method.
```

```{py:method} jayrun.BaseResource.teardown(data) -> None
Release a previously loaded resource value.

:param jayrun.Data data: Exact data container returned by successful setup.
```

```{py:class} jayrun.ResourceField(*, name=None, description=None, required=True, parallel_safe=True)
Declare a runtime-managed resource dependency on an operator.

:param name: Optional field name.
:type name: str | None
:param description: Optional field description.
:type description: str | None
:param bool required: Whether graph confirmation requires a bound resource.
:param bool parallel_safe: Whether concurrent executions may acquire the same cached instance.
:raises TypeError: If field metadata or `parallel_safe` has an invalid type.
```

```{py:attribute} jayrun.ResourceField.parallel_safe
:type: bool

Whether the bound cached resource may be acquired concurrently.
```

```{py:class} jayrun.core.graph.definition.ResourceDefinition(*, resource_id, parallel_safe, owner, required, layout_position, attribute_name, name, description)
Immutable graph-local description of one registered resource field.

:param int resource_id: Integer identifier local to the owning graph.
:param bool parallel_safe: Whether the selected cached resource may be acquired concurrently through this field.
:param str owner: Display representation of the owning operator.
:param bool required: Whether the field must be bound before confirmation.
:param tuple layout_position: Graph layout position of the owner.
:param str attribute_name: Attribute under which the field was declared.
```


Next, read {doc}`Operators and Executions <../components/operators-and-executions>` to use artifact, configuration, and resource fields in reusable computation.
