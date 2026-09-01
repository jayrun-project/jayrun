(api-reference)=
# API Reference

This reference is generated from the docstrings of Jayrun's supported public imports. Use the linked explanatory chapters for concepts, lifecycle rules, and complete examples. Internal `jayrun.core.*` and `jayrun.engine.*` modules are implementation details and are not part of this public reference.

## Graphs, components, and execution

Import these objects directly from `jayrun`:

```python
from jayrun import (
    Artifact,
    ArtifactContext,
    ArtifactField,
    ArtifactFlow,
    BaseOperator,
    BaseResource,
    ConfigContext,
    ConfigField,
    Data,
    Engine,
    GraphDefinition,
    ResourceField,
)
```

See {doc}`Artifacts and Data Flow <../concepts/artifacts-and-data-flow>`, {doc}`Configuration <../concepts/configuration>`, {doc}`Resources <../concepts/resources>`, {doc}`Operators and Executions <../components/operators-and-executions>`, {doc}`Graph Construction <../components/graph-construction>`, and {doc}`Engine and Context Lifecycle <../runtime/engine-and-context-lifecycle>` for the corresponding guides.

```{eval-rst}
.. autoclass:: jayrun.Artifact
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: jayrun.ArtifactField
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: jayrun.ArtifactContext
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: jayrun.Data
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: jayrun.ConfigField
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: jayrun.ConfigContext
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: jayrun.ResourceField
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: jayrun.BaseResource
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: jayrun.BaseOperator
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: jayrun.ArtifactFlow
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: jayrun.GraphDefinition
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: jayrun.Engine
   :members:
   :special-members: __enter__, __exit__
```

## Context runs and results

Import lifecycle handles and terminal results from `jayrun.context`:

```python
from jayrun.context import (
    ArtifactResult,
    ContextNotTerminatedError,
    ContextReport,
    ContextRun,
    ContextState,
    ValueRecord,
)
```

```{eval-rst}
.. autoclass:: jayrun.context.ContextRun
   :members:
   :special-members: __await__
```

```{eval-rst}
.. autoclass:: jayrun.context.ContextState
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.ArtifactResult
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.ContextReport
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.ValueRecord
   :members:
   :no-index:
```

```{eval-rst}
.. autoexception:: jayrun.context.ContextNotTerminatedError
```

Lifecycle behavior is explained in {doc}`Engine and Context Lifecycle <../runtime/engine-and-context-lifecycle>`. Returned reports and records are explained in {doc}`Observability and Inspection <../observability/observability-and-inspection>`.

## Settings

Import engine-wide and per-context policy from `jayrun.settings`:

```python
from jayrun.settings import (
    ArtifactPolicy,
    ContextSettings,
    EngineSettings,
    FailureMode,
    RetryPolicy,
    RuntimeDevice,
    RuntimeMode,
)
```

See {doc}`Execution Settings <../settings/execution-settings>` for precedence, defaults, and operational guidance.

```{eval-rst}
.. autoclass:: jayrun.settings.EngineSettings
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: jayrun.settings.ContextSettings
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: jayrun.settings.ArtifactPolicy
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: jayrun.settings.RetryPolicy
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: jayrun.settings.RuntimeDevice
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: jayrun.settings.FailureMode
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: jayrun.settings.RuntimeMode
   :members:
   :no-index:
```

## Placement values

Import placement declarations from `jayrun.placement`:

```python
from jayrun.placement import (
    Backend,
    CPU_PLACEMENT,
    Device,
    Placement,
    PlacementGroup,
    PlacementLocation,
)
```

`PlacementLocation` is the public type alias `Placement | PlacementGroup`, and `CPU_PLACEMENT` is the canonical unreserved CPU placement. See {doc}`Placement and Capacity <../runtime/placement-and-capacity>` and {doc}`Placement Interface <../interfaces/placement>` for reservation behavior.

```{eval-rst}
.. autoclass:: jayrun.placement.Device
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.placement.Backend
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.placement.Placement
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.placement.PlacementGroup
   :members:
```

## Artifact properties

Import static artifact contracts from `jayrun.properties`:

```python
from jayrun.properties import (
    ArtifactProperty,
    BackendProperty,
    DTypeProperty,
    DeviceProperty,
    ShapeProperty,
    TypeProperty,
)
```

See {doc}`Graph Validation <../components/graph-validation>` for property matching rules and diagnostics.

```{eval-rst}
.. autoclass:: jayrun.properties.ArtifactProperty
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.properties.TypeProperty
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.properties.DTypeProperty
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.properties.ShapeProperty
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.properties.DeviceProperty
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.properties.BackendProperty
   :members:
```

## Graph validation

Graph validation has one public entry point:

```python
from jayrun.validation import GraphValidator
```

```{eval-rst}
.. autoclass:: jayrun.validation.GraphValidator
   :members:
   :no-index:
```

## Injected operational interfaces

Jayrun injects `self.execution`, `self.context`, `self.runtime`, and `self.placement` while it invokes operators and resources. Applications use these handles but do not construct or import their implementation classes. Their complete capability and lifetime reference remains in {doc}`Operational Interfaces <../interfaces/index>`.
