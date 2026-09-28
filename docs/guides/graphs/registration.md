# Register graphs and bind serializers

Use a `GraphRegistry` when contexts refer to graphs by portable `(key, version)` identities, including Controller submission and remote synchronization. Confirm a graph before registration.

```python
from jayrun import GraphRegistry

# graph is a confirmed GraphDefinition.
registry = GraphRegistry()
registry.register("transform", graph)
identity = registry.identity_for(graph)
assert registry[identity] is graph
```

The version comes from `graph.version`; the registry key is an application-chosen nonempty string. Re-registering the same graph with the same identity is idempotent. A different graph cannot silently replace an occupied identity, and the same graph cannot acquire conflicting registry identities.

## Boundary serialization

Artifact serializers are application-defined `BaseSerializer` implementations. Bind them with `graph.bind_serializers(...)` before confirming the graph. If you use serializer bindings, cover the complete entry/exit boundary expected by the graph. Partial coverage is rejected; an internal-only artifact is not a substitute for a boundary artifact.

This complete example imports Scale from the [workflow program](../../start/first-graph.md), binds a serializer to both boundary artifacts, then confirms and registers the graph. Save both files in the same directory to run it. It prints `('scale', '1')`.

```{literalinclude} ../../_examples/serialization.py
:language: python
```

The serializer handles this example's integer payloads. The factor remains configuration and uses the separate configuration value contract. Once confirmed, this graph cannot acquire different serializer bindings; construct and prepare another declaration if its boundary needs to change.

Registration and serializer binding are distinct from transport. A serializer defines payload encoding/decoding; it does not choose a protocol, authenticate a peer or deliver a snapshot. Config/record values use their own supported codecs. See [portable values](../integration/values.md).

## Requirements and scope

Component requirements are declarations available through graph inspection. Requirement conflicts need a consistent application environment; they are not resolved by deleting the declaration. With an Engine registry, submitted graphs and scoped authority graphs must normalize through that registry. Register the Controller/Supervisor graph itself as well as the work graphs it supervises.

The [Controller example](../runtime/controller.md) demonstrates both registrations and an ordinary child submission. Reference: [GraphDefinition and GraphRegistry](../../reference/graphs.md).
