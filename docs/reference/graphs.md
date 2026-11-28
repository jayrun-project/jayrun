# GraphDefinition and GraphRegistry

Confirm explicitly before submission/registration. Resource and timing preparation precedes confirmation; serializer binding also precedes confirmation. See [construction](../guides/graphs/construction.md) and [registration](../guides/graphs/registration.md).

`GraphDefinition.flow(reference)` resolves an exact artifact, an inspected
definition, or a graph-local integer ID. Use `graph.inspect.artifacts.by_id(id)`
to inspect the slot. `attach` returns a fresh unconfirmed graph. `attach_many`
validates related input rows together. Both use the same compiled graph model
as direct construction. [Examples and binding rules](../guides/graphs/construction.md#retrieve-or-attach-an-authored-flow).

```{eval-rst}
.. autoclass:: jayrun.ArtifactFlow
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.GraphDefinition
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.GraphRegistry
   :members:
```

```{eval-rst}
.. autodata:: jayrun.registry.GraphIdentity
```

```{eval-rst}
.. autoclass:: jayrun.registry.GraphRegistryInspection()
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.registry.GraphRequirementComparison
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.registry.GraphRequirements
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.registry.RequirementConflict
   :members:
```
