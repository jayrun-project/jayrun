(getting-started)=
# Getting Started

This chapter builds and executes one complete Jayrun graph. It introduces only the objects needed for a successful first run; later chapters explain their contracts in detail.

## Installation

Install Jayrun from PyPI:

```bash
python -m pip install jayrun
```

To install a source checkout instead:

```bash
python -m pip install .
```

Jayrun 0.1.0 requires Python 3.11 or later.

## Define an artifact

An artifact identifies data as it flows through a graph. It is a declaration, not the runtime value itself.

```python
from jayrun import Artifact

data = Artifact(name="data")
```

The same declaration is used to connect the graph, provide an entry value, and retrieve the retained result.

## Define an operator

This operator consumes `data`, multiplies its value by a configured factor, and produces a new value for the same artifact:

```python
from jayrun import ArtifactField, BaseOperator, ConfigField


class ScaleData(BaseOperator):
    def __init__(
        self,
        *,
        input_data: Artifact,
        outputs: tuple[Artifact | None, ...],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.input_data = ArtifactField(required=True)
        self.factor = ConfigField(value_type=int, required=True)
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> object:
        return self.input_data.value * self.factor.value
```

Create the operator and bind its declared input and output:

```python
scale = ScaleData(
    input_data=data,
    outputs=(data,),
    name="scale_data",
)
```

`data` identifies graph data. `scale.input_data` is the operator port bound to that artifact. At runtime, `.value` exposes the value belonging to the current context.

## Connect an `ArtifactFlow`

An `ArtifactFlow` identifies the operators that consume an artifact:

```python
from jayrun import ArtifactFlow

data_flow = ArtifactFlow(
    scale,
    artifact=data,
)
```

Because the operator regenerates `data`, its produced value remains available as the graph output.

## Create a `GraphDefinition`

```python
from jayrun import GraphDefinition

graph = GraphDefinition(
    data_flow,
    entry_flows=(data_flow,),
)
```

`entry_flows` identifies artifact values that must be supplied when the graph is submitted. This graph has no resources to bind, so it is ready for use immediately.

## Provide artifact and configuration values

An `ArtifactContext` supplies entry values for one submission:

```python
from jayrun import ArtifactContext

artifacts = ArtifactContext(graph=graph)
artifacts.set({data: 7})
```

A `ConfigContext` supplies configuration values declared by the graph:

```python
from jayrun import ConfigContext

configs = ConfigContext(graph=graph)
configs.set({scale.factor: 3})
```

Both contexts must belong to the submitted graph. Artifact values are keyed by artifact declarations, while configuration values may be keyed by their registered config fields.

## Start an engine

```python
from jayrun import Engine

engine = Engine()
engine.start()
```

The engine creates the runtime that validates, schedules, executes, and finalizes submitted contexts.

## Submit the graph

```python
context_id = engine.submit(
    artifacts,
    configs,
)
```

`submit()` returns the integer identifier assigned to the new context. Submission does not wait for the graph to finish.

## Wait for completion

```python
snapshot = engine.wait(context_id)
```

With no requested state or timeout, `wait()` waits for context finalization. It returns a `ContextSnapshot`, or `None` if the identifier is unavailable.

```python
from jayrun.context import ContextState

if snapshot is None:
    raise RuntimeError("context is unavailable")

if snapshot.state is not ContextState.FINISHED:
    raise RuntimeError(
        f"context finished in state {snapshot.state.value!r}"
    ) from snapshot.failure
```

:::{note}
A normal context failure is represented in its snapshot; waiting does not raise that failure in the calling thread.
:::

## Inspect the retained result

Successful contexts retain exit artifacts by default:

```python
artifact_result = snapshot.artifact(data)
print(artifact_result.value)
```

Output:

```text
21
```

The `ArtifactResult` contains the final value, placement, and lifecycle report. `snapshot.artifacts` exposes the complete artifact result mapping; cleared artifacts remain present with a value of `None`.

## Delete the completed context

After consuming or persisting the result, remove the finalized context from the engine:

```python
deleted = engine.delete(context_id)
```

`delete()` returns `True` when it removes the context and `False` when the identifier is unavailable. Active contexts cannot be deleted. A snapshot already held by the caller remains available after deletion.

:::{important}
Delete or prune finalized contexts after their retained results have been consumed. Otherwise, retained payloads remain reachable through the engine registry.
:::

## Shut down the engine

```python
engine.shutdown()
```

Place shutdown in a `finally` block so it also runs when application code raises an exception.

## Complete minimal example

For the normal synchronous lifecycle, use `Engine` as a context manager. Entering starts the engine; leaving performs graceful shutdown, including when the block raises.

```python
from jayrun import (
    Artifact,
    ArtifactContext,
    ArtifactField,
    ArtifactFlow,
    BaseOperator,
    ConfigContext,
    ConfigField,
    Engine,
    GraphDefinition,
)
from jayrun.context import ContextState


class ScaleData(BaseOperator):
    def __init__(
        self,
        *,
        input_data: Artifact,
        outputs: tuple[Artifact | None, ...],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.input_data = ArtifactField(required=True)
        self.factor = ConfigField(value_type=int, required=True)
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> object:
        return self.input_data.value * self.factor.value


data = Artifact(name="data")

scale = ScaleData(
    input_data=data,
    outputs=(data,),
    name="scale_data",
)

data_flow = ArtifactFlow(scale, artifact=data)
graph = GraphDefinition(data_flow, entry_flows=(data_flow,))

artifacts = ArtifactContext(graph=graph)
artifacts.set({data: 7})

configs = ConfigContext(graph=graph)
configs.set({scale.factor: 3})

with Engine() as engine:
    context_id = engine.submit(artifacts, configs)
    snapshot = engine.wait(context_id)

    if snapshot is None:
        raise RuntimeError("context is unavailable")

    if snapshot.state is not ContextState.FINISHED:
        raise RuntimeError(
            f"context finished in state {snapshot.state.value!r}"
        ) from snapshot.failure

    print(snapshot.artifact(data).value)
    engine.delete(context_id)
```

Output:

```text
21
```

Next, read {doc}`Scope and Lifetime Model <concepts/scope-and-lifetime>` to understand who owns each kind of state and when it may be cleaned up. Then use {doc}`Build and Validate a Graph <tutorials/build-and-validate-graph>` for a realistic multi-operator example with artifact contracts and validation.
