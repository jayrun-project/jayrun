# Jayrun

[![PyPI version](https://img.shields.io/pypi/v/jayrun.svg)](https://pypi.org/project/jayrun/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Documentation](https://github.com/jayrun-project/jayrun/actions/workflows/docs.yml/badge.svg)](https://github.com/jayrun-project/jayrun/actions/workflows/docs.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Jayrun is a lightweight, artifact-centric Python framework for computational graphs that need iteration, shared resources, hardware placement, supervision, and reliable lifecycle management. Components remain ordinary synchronous or asynchronous Python classes; Jayrun coordinates when they run and who owns their data.

Jayrun fits workloads that need to:

- iterate an entire graph or repeat one operator;
- share an expensive model, client, or service across submissions;
- reserve GPU or atomic multi-device capacity;
- combine blocking libraries with an application event loop;
- pause, resume, abort, or stop iteration through one `ContextRun` API;
- supervise selected graph contexts from another graph;
- retain declared results while releasing intermediate data;
- apply retry, failure, and shutdown policies consistently.

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

An artifact declares data flowing through a graph. Runtime values and configuration are supplied separately for each submission.

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
    print(run.artifact(data).value)  # 21
```

`Engine.submit()` returns a stable `ContextRun`. Calling `run.wait()` waits until the context is finalized, so retained artifacts and the terminal report are ready. The same object exposes live state and lifecycle control while work is active, then stored values and retained `ArtifactResult`s after completion. Applications that need to distinguish unsuccessful terminal outcomes can inspect `run.state` and `run.report.failure` before reading an artifact.

## Public API

Graph construction and execution:

```python
from jayrun import Artifact, ArtifactContext, ArtifactField, ArtifactFlow
from jayrun import BaseOperator, BaseResource, ConfigContext, ConfigField
from jayrun import Data, Engine, GraphDefinition, ResourceField
```

Focused APIs:

```python
from jayrun.context import ArtifactResult, ContextRun, ContextState
from jayrun.placement import Backend, Device, Placement, PlacementGroup
from jayrun.properties import DTypeProperty, ShapeProperty, TypeProperty
from jayrun.settings import ArtifactPolicy, ContextSettings, EngineSettings
from jayrun.validation import GraphValidator
```

Modules under `jayrun.core` and `jayrun.engine` are implementation details.

## Documentation

Read the [documentation](https://jayrun.readthedocs.io/en/latest/) for the conceptual model, operational guidance, and complete tutorials:

- [Getting Started](https://jayrun.readthedocs.io/en/latest/getting-started.html)
- [Build and Validate a Graph](https://jayrun.readthedocs.io/en/latest/tutorials/build-and-validate-graph.html)
- [Denoise Images with FastAPI](https://jayrun.readthedocs.io/en/latest/tutorials/denoise-images-with-fastapi.html)
- [MNIST Inference and Supervised Training on CUDA](https://jayrun.readthedocs.io/en/latest/tutorials/mnist-inference-and-training.html)
- [API Reference](https://jayrun.readthedocs.io/en/latest/reference/api.html)

## Project status

Jayrun is under active development. Public APIs may still be refined before 1.0 when a clearer or safer contract requires it. Report bugs and request features through [GitHub Issues](https://github.com/jayrun-project/jayrun/issues).

## License

Jayrun is licensed under the [Apache License 2.0](LICENSE).

Copyright 2026 Masoud Yavari.
