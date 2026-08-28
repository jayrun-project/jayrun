# Jayrun

[![PyPI version](https://img.shields.io/pypi/v/jayrun.svg)](https://pypi.org/project/jayrun/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Documentation](https://github.com/jayrun-project/jayrun/actions/workflows/docs.yml/badge.svg)](https://github.com/jayrun-project/jayrun/actions/workflows/docs.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Jayrun is an artifact-centric Python execution framework for computational graphs that need more than one-pass task scheduling. It coordinates data flow, iteration, shared resources, hardware placement, supervision, failure containment, and shutdown while keeping application components ordinary Python classes.

Jayrun is useful when a workload must do one or more of the following:

- iterate a graph or repeat selected operators;
- share expensive runtime resources safely across submissions;
- reserve CPU, GPU, or atomic multi-device capacity;
- combine synchronous and asynchronous operators;
- inspect, pause, resume, or abort contexts, and stop graph iteration;
- supervise several contexts from another context;
- retain declared results while clearing intermediate data;
- apply retry and failure policies consistently.

## Installation

Jayrun requires Python 3.11 or later.

```bash
python -m pip install jayrun
```

Optional integrations are installed only when an application needs them:

```bash
python -m pip install "jayrun[yaml]"      # YAML configuration loading
python -m pip install "jayrun[plotting]"  # Interactive validation graphs
```

## A complete first graph

An artifact declares data flowing through a graph. An operator declares how that data is consumed and produced. Runtime values are supplied separately for each submission.

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
        data: Artifact,
        outputs: tuple[Artifact | None, ...],
        name: str | None = None,
    ) -> None:
        super().__init__(name=name)
        self.data = ArtifactField(required=True)
        self.factor = ConfigField(value_type=int, required=True)
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> object:
        return self.data.value * self.factor.value


data = Artifact(name="data")
scale = ScaleData(data=data, outputs=(data,), name="scale_data")
data_flow = ArtifactFlow(scale, artifact=data)
graph = GraphDefinition(data_flow, entry_flows=(data_flow,))

artifacts = ArtifactContext(graph=graph)
artifacts.set({data: 7})

configs = ConfigContext(graph=graph)
configs.set({scale.factor: 3})

with Engine() as engine:
    context_id = engine.submit(artifacts, configs)
    snapshot = engine.wait(context_id)

if snapshot is None or snapshot.state is not ContextState.FINISHED:
    raise RuntimeError("the context did not finish successfully")

print(snapshot.artifact(data).value)  # 21
```

The graph definition is reusable. Each submission receives its own artifact values, configuration, settings, records, and lifecycle state.

## Core ideas

| Concept | Purpose |
|---|---|
| Artifact | Declares data identity and flow through a graph |
| Operator | Transforms artifacts or performs a terminal side effect |
| Resource | Shares a runtime-managed value or capability safely |
| Context | Isolates one graph submission and its lifecycle |
| Placement | Reserves execution capacity on CPU or accelerator devices |
| Supervisor | Lets running workflows observe and control other contexts |

Graph-building primitives are imported from `jayrun`:

```python
from jayrun import Artifact, ArtifactContext, ArtifactField, ArtifactFlow
from jayrun import BaseOperator, BaseResource, ConfigContext, ConfigField
from jayrun import Data, Engine, GraphDefinition, ResourceField
```

Focused public APIs are grouped by purpose:

```python
from jayrun.context import ArtifactResult, ContextSnapshot, ContextState
from jayrun.placement import Backend, Device, Placement, PlacementGroup
from jayrun.properties import DTypeProperty, ShapeProperty, TypeProperty
from jayrun.settings import ArtifactPolicy, ContextSettings, EngineSettings
from jayrun.validation import GraphValidator
```

Internal `jayrun.core.*` and `jayrun.engine.*` modules are implementation details and are not supported import paths.

## Documentation

Read the [documentation](https://jayrun.readthedocs.io/en/latest/) for the conceptual model, complete tutorials, operational guidance, and API reference.

Recommended starting points:

- [Introduction](https://jayrun.readthedocs.io/en/latest/introduction.html)
- [Getting Started](https://jayrun.readthedocs.io/en/latest/getting-started.html)
- [Denoise Images with FastAPI](https://jayrun.readthedocs.io/en/latest/tutorials/denoise-images-with-fastapi.html)
- [MNIST Inference and Supervised Training on CUDA](https://jayrun.readthedocs.io/en/latest/tutorials/mnist-inference-and-training.html)
- [API Reference](https://jayrun.readthedocs.io/en/latest/reference/api.html)

## Project status

Jayrun 0.1.0 is an alpha release. Its public APIs are documented, but compatibility may change before 1.0 when a clearer or safer contract requires it. Report bugs and request features through [GitHub Issues](https://github.com/jayrun-project/jayrun/issues).

## License

Jayrun is licensed under the [Apache License 2.0](LICENSE).

Copyright 2026 Masoud Yavari.
