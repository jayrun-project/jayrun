# Jayrun

[![PyPI version](https://img.shields.io/pypi/v/jayrun.svg)](https://pypi.org/project/jayrun/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Documentation](https://github.com/jayrun-project/jayrun/actions/workflows/docs.yml/badge.svg)](https://github.com/jayrun-project/jayrun/actions/workflows/docs.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/jayrun-project/jayrun/blob/main/LICENSE)

Jayrun is an artifact-centric Python execution framework for pipelines, iterative computation and application services. Operators consume and produce artifact values; an Engine manages execution, resource lifetimes and control of running work. Components use ordinary synchronous or asynchronous Python methods.

[Documentation](https://jayrun.readthedocs.io/en/latest/) · [First program](https://jayrun.readthedocs.io/en/latest/start/first-graph.html) · [Tutorials](https://jayrun.readthedocs.io/en/latest/tutorials/index.html) · [API reference](https://jayrun.readthedocs.io/en/latest/reference/imports.html)

[![Jayrun dashboard listing running and paused contexts with graph versions, progress and iteration counts](https://raw.githubusercontent.com/jayrun-project/jayrun/main/docs/_static/screenshots/dashboard.png)](https://jayrun.readthedocs.io/en/latest/guides/visualization/dashboard.html)

*Running and paused work in the dashboard. The dashboard is itself a graph, built from an observing operator and a managed service resource. Click the screenshot for an interactive offline preview and setup guide.*

## What Jayrun does

- **Release intermediate data automatically.** Artifact flow lets Jayrun release consumed values when execution no longer needs them. Entry/exit retention policies and application references still determine what stays alive.
- **Reuse expensive resources.** Models, calibration data and clients can remain available across compatible runs. The Engine manages acquisition, reuse and eventual teardown.
- **Build your own observers and controllers.** Use graphs for monitoring, experiment scheduling or distributed-work coordination. They use the existing execution and lifecycle machinery, with separate supervision capacity. Your application supplies transport and authentication.
- **Separate declaration from execution.** Validate and visualize a graph before running it, then submit it repeatedly with different inputs and configuration. Each submission returns its own `ContextRun`.
- **Manage iteration and capacity explicitly.** Combine graph iteration, operator repetition, conditional routes, sync/async execution and placement requests with lifecycle controls and scoped authority.
- **Keep dependencies small.** The required third-party runtime dependency is `packaging`; PyYAML is optional. HTML visualization needs no additional plotting package.

See [what Jayrun does](https://jayrun.readthedocs.io/en/latest/start/overview.html) for practical benefits and boundaries, and [data and lifetimes](https://jayrun.readthedocs.io/en/latest/start/data-and-lifetimes.html) for how artifacts, configuration and resources work together.

## Install

Requires Python 3.11 or later:

```bash
python -m pip install jayrun
```

For YAML configuration support, install `jayrun[yaml]`. Workload libraries such as PyTorch are application dependencies, not core requirements.

## A complete first graph

This program declares a multiplication, confirms the graph, supplies input and configuration, and prints `21`:

```python
from jayrun import (
    Artifact, ArtifactContext, ArtifactField, ArtifactFlow, BaseOperator,
    ConfigContext, ConfigField, Engine, GraphDefinition,
)
from jayrun.context import ContextState


class Scale(BaseOperator):
    def __init__(self, *, source, outputs):
        super().__init__()
        self.source = ArtifactField()
        self.factor = ConfigField(value_type=int)
        self.outputs = (ArtifactField(),)

    def execute(self):
        result = self.source.value * self.factor.value
        self.context.record("scaled", result)
        return result


source = Artifact(name="source")
result = Artifact(name="result")
scale = Scale(source=source, outputs=(result,))
flow = ArtifactFlow(scale, artifact=source)
graph = GraphDefinition(flow, entry_flows=flow)
graph.confirm()

with Engine() as engine:
    run = engine.submit(
        graph,
        ArtifactContext({source: 7}),
        ConfigContext({scale.factor: 3}),
    )
    run.wait(timeout=10)
    if run.state is not ContextState.FINISHED:
        raise RuntimeError(str(run.report.data.failure))
    print(run.artifact(result).value)  # 21
```

`ArtifactContext` supplies data; `ConfigContext` supplies the operator's parameters. Execution settings separately control policies such as retries and iteration limits. `run.wait()` waits for finalization, which can include failure; the example checks the outcome before reading the result.

The same confirmed graph can serve another submission. The [complete walkthrough](https://jayrun.readthedocs.io/en/latest/start/first-graph.html) explains each declaration, inspects recorded values and visualizes the finished run.

## Inspect declarations and execution

Save a declaration with `graph.plot.save("graph.html")`, a registry with `registry.plot.save("registry.html")`, or a completed run with `run.plot.save("run.html")`. These HTML viewers are interactive and open in a browser. Declaration views show structure; run views add captured outcomes, timings, records and reports.

[![Split-and-join graph with an explicit Splitter, two processing branches and a Join operator](https://raw.githubusercontent.com/jayrun-project/jayrun/main/docs/_static/screenshots/split-and-join.png)](https://jayrun.readthedocs.io/en/latest/guides/visualization/graphs.html)

*An explicit split-and-join declaration. Click to explore the interactive graph and its explanation.*

The [visualization and reporting chapter](https://jayrun.readthedocs.io/en/latest/guides/evidence/plots.html) covers graph definitions, registries, completed runs and the dashboard. A controller graph can use `self.runtime` to observe or coordinate work; see [the Controller example](https://jayrun.readthedocs.io/en/latest/guides/runtime/controller.html) and [Engine/runtime correspondence](https://jayrun.readthedocs.io/en/latest/guides/runtime/correspondence.html).

## Persist execution history

Pass `Database("execution.sqlite")` from `jayrun.persistence` to `Engine(database=...)` to retain bounded execution/session history and timing profiles. The Engine owns the database lifecycle. After a run finishes, explicit `engine.database.flush()` checks storage settlement; computation completion alone does not establish successful persistence.

The [Persistence and Database guide](https://jayrun.readthedocs.io/en/latest/guides/evidence/persistence.html) includes a complete write–close–read example. Stored diagnostic history is separate from application checkpoints and arbitrary artifact storage.

## Tutorials

Explore complete applications with a walkthrough, runnable Python source and notebook:

| Tutorial | Python source | Notebook | What it demonstrates |
| --- | --- | --- | --- |
| [Build and validate](https://jayrun.readthedocs.io/en/latest/tutorials/build-and-validate-graph.html) | [build_graph.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/build_graph.py) | [01_build_graph](https://github.com/jayrun-project/jayrun/blob/main/tutorials/01_build_graph.ipynb) | Properties, diagnostics and corrected execution |
| [Image service](https://jayrun.readthedocs.io/en/latest/tutorials/denoise-images-with-fastapi.html) | [denoise_images.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/denoise_images.py) | [02_denoise_images](https://github.com/jayrun-project/jayrun/blob/main/tutorials/02_denoise_images.ipynb) | Async service, shared client and routing |
| [Shared model inference](https://jayrun.readthedocs.io/en/latest/tutorials/mnist-inference-and-training.html#share-a-read-only-model-for-inference) | [mnist_inference.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/mnist_inference.py) | [03_mnist_inference](https://github.com/jayrun-project/jayrun/blob/main/tutorials/03_mnist_inference.ipynb) | Read-only model reuse and placement |
| [Supervised training](https://jayrun.readthedocs.io/en/latest/tutorials/mnist-inference-and-training.html#supervise-replace-and-promote) | [mnist_training.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/mnist_training.py) | [04_mnist_training](https://github.com/jayrun-project/jayrun/blob/main/tutorials/04_mnist_training.ipynb) | Iteration, mutable state and scoped supervision |
| [Document service](https://jayrun.readthedocs.io/en/latest/tutorials/document-ingestion.html) | [document_ingestion.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/document_ingestion.py) | [05_document_ingestion](https://github.com/jayrun-project/jayrun/blob/main/tutorials/05_document_ingestion.ipynb) | Long-running jobs and transactional publication |
| [Adapter checkpointing](https://jayrun.readthedocs.io/en/latest/tutorials/checkpointed-adapter-finetuning.html) | [adapter_finetuning.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/adapter_finetuning.py) | [06_adapter_finetuning](https://github.com/jayrun-project/jayrun/blob/main/tutorials/06_adapter_finetuning.ipynb) | Model/optimizer/RNG checkpoints |
| [Scientific campaign](https://jayrun.readthedocs.io/en/latest/tutorials/adaptive-scientific-calibration.html) | [heat_calibration.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/heat_calibration.py) | [07_heat_calibration](https://github.com/jayrun-project/jayrun/blob/main/tutorials/07_heat_calibration.ipynb) | Adaptive control and reproducibility |

Each tutorial includes a small offline CPU path. See the [tutorial setup guide](https://jayrun.readthedocs.io/en/latest/tutorials/index.html) for dependencies and optional GPU/model workloads.

## Find your next step

| Task | Guide |
| --- | --- |
| Build, validate, submit and inspect a graph | [From declaration to execution](https://jayrun.readthedocs.io/en/latest/guides/workflow/index.html) |
| Resolve fan-out, fan-in and conditional routes | [Graph-definition resolutions](https://jayrun.readthedocs.io/en/latest/guides/graphs/resolutions.html) |
| Use context, execution, placement and runtime handles | [Component interfaces](https://jayrun.readthedocs.io/en/latest/guides/components/index.html) |
| Add reusable models or clients | [Resources](https://jayrun.readthedocs.io/en/latest/guides/graphs/resources.html) |
| Integrate services, remote work and checkpoints | [Application integration](https://jayrun.readthedocs.io/en/latest/guides/integration/index.html) |
| Check exact imports and contracts | [Public API](https://jayrun.readthedocs.io/en/latest/reference/imports.html) |

The [documentation sources](https://github.com/jayrun-project/jayrun/blob/main/docs/index.md) are included in this repository. Supported public imports come from `jayrun` and its documented public modules; `jayrun.core` and `jayrun.engine` are implementation details.

## Scope and project status

Jayrun manages graph execution and ownership; applications own network transport, authentication, external side effects and checkpoint contents. Placement accounts for declared capacity rather than performing device allocation. Cleanup releases framework references rather than guaranteeing an immediate drop in process memory. See [supported behavior and limitations](https://jayrun.readthedocs.io/en/latest/reference/limits.html).

Jayrun provides a tested foundation for graph execution, with ongoing improvements to reliability, usability and documentation. Report bugs and request features through [GitHub Issues](https://github.com/jayrun-project/jayrun/issues).

## License

[Apache License 2.0](https://github.com/jayrun-project/jayrun/blob/main/LICENSE). Copyright 2026 Masoud Yavari.
