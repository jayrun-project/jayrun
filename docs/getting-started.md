(getting-started)=
# Getting Started

This chapter builds and runs one complete graph. It introduces the smallest useful path from declarations to a retained result.

## Installation

```bash
python -m pip install jayrun
```

Jayrun requires Python 3.11 or later.

## 1. Declare the data

An artifact identifies data as it moves through a graph. It is a declaration, not the runtime value.

```python
from jayrun import Artifact

data = Artifact(name="data")
```

## 2. Define one operator

The operator consumes `data`, multiplies it by a configured factor, and regenerates the same artifact:

```python
from jayrun import ArtifactField, BaseOperator, ConfigField


class ScaleData(BaseOperator):
    def __init__(
        self,
        *,
        data: Artifact,
        outputs: tuple[Artifact | None, ...],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.data = ArtifactField(required=True)
        self.factor = ConfigField(value_type=int, required=True)
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> object:
        return self.data.value * self.factor.value
```

Create the operator and bind its input and output declarations:

```python
scale = ScaleData(data=data, outputs=(data,), name="scale_data")
```

At runtime, `self.data.value` is the value belonging to the current submission and `self.factor.value` is its configured factor.

## 3. Build the graph

An `ArtifactFlow` lists the operators that consume one artifact:

```python
from jayrun import ArtifactFlow, GraphDefinition

data_flow = ArtifactFlow(scale, artifact=data)
graph = GraphDefinition(data_flow, entry_flows=(data_flow,))
```

`entry_flows` identifies values supplied by the application. Because `scale` regenerates `data`, the last value becomes a graph exit.

## 4. Create submission contexts

An `ArtifactContext` supplies entry values. A `ConfigContext` supplies declared configuration.

```python
from jayrun import ArtifactContext, ConfigContext

artifacts = ArtifactContext(graph=graph)
artifacts.set({data: 7})

configs = ConfigContext(graph=graph)
configs.set({scale.factor: 3})
```

Both contexts are tied to the confirmed graph. `Engine.submit()` captures sealed, read-only submission views, so later mutation cannot change a running context.

## 5. Submit and wait

```python
from jayrun import Engine

with Engine() as engine:
    run = engine.submit(artifacts, configs)
    run.wait(timeout=10)
```

`submit()` returns a `ContextRun`. The run updates in place throughout the lifecycle and remains useful after the engine releases its internal execution state.

In asynchronous applications, start the engine with the running event loop and await the same run:

```python
import asyncio

engine.start(loop=asyncio.get_running_loop())
try:
    run = engine.submit(artifacts, configs)
    await run
finally:
    await engine.shutdown_async()
```

## 6. Check the outcome

```python
from jayrun.context import ContextState

if run.state is not ContextState.FINISHED:
    raise RuntimeError(
        f"context ended in {run.state.value!r}"
    ) from run.report.failure
```

Waiting reports lifecycle outcomes through `run.state` and `run.report`; an operator failure is not re-raised in the waiting thread.

## 7. Read the retained artifact

```python
result = run.artifact(data)
print(result.value)
```

Output:

```text
21
```

`ArtifactResult` keeps the retained `Data`, its placement, and artifact lifecycle records. A run owns its terminal report and retained results, so no registry deletion or pruning step is required.

## Complete example

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
    def __init__(self, *, data, outputs, name=None, description=None):
        super().__init__(name=name, description=description)
        self.data = ArtifactField(required=True)
        self.factor = ConfigField(value_type=int, required=True)
        self.outputs = (ArtifactField(required=True),)

    def execute(self):
        return self.data.value * self.factor.value


data = Artifact(name="data")
scale = ScaleData(data=data, outputs=(data,), name="scale_data")
flow = ArtifactFlow(scale, artifact=data)
graph = GraphDefinition(flow, entry_flows=(flow,))

artifacts = ArtifactContext(graph=graph)
artifacts.set({data: 7})
configs = ConfigContext(graph=graph)
configs.set({scale.factor: 3})

with Engine() as engine:
    run = engine.submit(artifacts, configs)
    run.wait(timeout=10)

if run.state is not ContextState.FINISHED:
    raise RuntimeError("scale failed") from run.report.failure

print(run.artifact(data).value)
```

Continue with {doc}`Build and Validate a Graph <tutorials/build-and-validate-graph>` for a realistic multi-operator declaration, then {doc}`Denoise Images with FastAPI <tutorials/denoise-images-with-fastapi>` to embed Jayrun in an application event loop.
