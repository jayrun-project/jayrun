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

```{autoclass} jayrun.Artifact
:members:
:no-index:
```

```{autoclass} jayrun.ArtifactField
:members:
:no-index:
```

```{autoclass} jayrun.ArtifactContext
:members:
:no-index:
```

```{autoclass} jayrun.Data
:members:
:no-index:
```

```{autoclass} jayrun.ConfigField
:members:
:no-index:
```

```{autoclass} jayrun.ConfigContext
:members:
:no-index:
```

```{autoclass} jayrun.ResourceField
:members:
:no-index:
```

```{autoclass} jayrun.BaseResource
:members:
:no-index:
```

```{autoclass} jayrun.BaseOperator
:members:
:no-index:
```

```{autoclass} jayrun.ArtifactFlow
:members:
:no-index:
```

```{autoclass} jayrun.GraphDefinition
:members:
:no-index:
```

```{autoclass} jayrun.Engine
:members:
:special-members: __enter__, __exit__
:no-index:
```

## Context results

Import immutable context results from `jayrun.context`:

```python
from jayrun.context import ArtifactResult, ContextSnapshot, ContextState
```

```{autoclass} jayrun.context.ContextSnapshot
:members:
:no-index:
```

```{autoclass} jayrun.context.ContextState
:members:
:no-index:
```

```{autoclass} jayrun.context.ArtifactResult
:members:
:no-index:
```

Returned reports and records are explained in {doc}`Observability and Inspection <../observability/observability-and-inspection>`.

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

```{autoclass} jayrun.settings.EngineSettings
:members:
:no-index:
```

```{autoclass} jayrun.settings.ContextSettings
:members:
:no-index:
```

```{autoclass} jayrun.settings.ArtifactPolicy
:members:
:no-index:
```

```{autoclass} jayrun.settings.RetryPolicy
:members:
:no-index:
```

```{autoclass} jayrun.settings.RuntimeDevice
:members:
:no-index:
```

```{autoclass} jayrun.settings.FailureMode
:members:
:no-index:
```

```{autoclass} jayrun.settings.RuntimeMode
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

```{autoclass} jayrun.placement.Device
:members:
:no-index:
```

```{autoclass} jayrun.placement.Backend
:members:
:no-index:
```

```{autoclass} jayrun.placement.Placement
:members:
:no-index:
```

```{autoclass} jayrun.placement.PlacementGroup
:members:
:no-index:
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

```{autoclass} jayrun.properties.ArtifactProperty
:members:
:no-index:
```

```{autoclass} jayrun.properties.TypeProperty
:members:
:no-index:
```

```{autoclass} jayrun.properties.DTypeProperty
:members:
:no-index:
```

```{autoclass} jayrun.properties.ShapeProperty
:members:
:no-index:
```

```{autoclass} jayrun.properties.DeviceProperty
:members:
:no-index:
```

```{autoclass} jayrun.properties.BackendProperty
:members:
:no-index:
```

## Graph validation

Graph validation has one public entry point:

```python
from jayrun.validation import GraphValidator
```

```{autoclass} jayrun.validation.GraphValidator
:members:
:no-index:
```

## Injected operational interfaces

Jayrun injects `self.execution`, `self.context`, `self.runtime`, and `self.placement` while it invokes operators and resources. Applications use these handles but do not construct or import their implementation classes. Their complete capability and lifetime reference remains in {doc}`Operational Interfaces <../interfaces/index>`.
