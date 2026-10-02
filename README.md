# Jayrun

**Build, run, and inspect Python computation graphs with reusable resources and a live dashboard.**

Jayrun is a Python execution framework for pipelines, iterative experiments and application services. Define each step with a synchronous or asynchronous Python method. Jayrun passes artifact values between the steps and manages execution and resource lifetimes.

**Latest release:** [0.3.0](https://pypi.org/project/jayrun/0.3.0/)

[![PyPI version](https://img.shields.io/pypi/v/jayrun.svg)](https://pypi.org/project/jayrun/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![CI](https://github.com/jayrun-project/jayrun/actions/workflows/ci.yml/badge.svg)](https://github.com/jayrun-project/jayrun/actions/workflows/ci.yml)
[![Documentation](https://github.com/jayrun-project/jayrun/actions/workflows/docs.yml/badge.svg)](https://github.com/jayrun-project/jayrun/actions/workflows/docs.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/jayrun-project/jayrun/blob/main/LICENSE)

[Documentation](https://jayrun.readthedocs.io/en/latest/) · [Quick start](#quick-start) · [Explore the dashboard](https://jayrun.readthedocs.io/en/latest/guides/visualization/dashboard.html) · [Tutorials](#tutorials) · [API reference](https://jayrun.readthedocs.io/en/latest/reference/imports.html)

[![Jayrun dashboard listing running and paused contexts with graph versions, progress and iteration counts](https://raw.githubusercontent.com/jayrun-project/jayrun/main/docs/_static/screenshots/dashboard.png)](https://jayrun.readthedocs.io/en/latest/guides/visualization/dashboard.html)

*Follow running and paused work in the dashboard. Click to explore the offline preview and learn how to start your own.*

## What Jayrun does

- **Reuse expensive resources.** Share models, calibration data and clients across compatible runs, with managed acquisition and teardown.
- **Release intermediate data automatically.** Let Jayrun release consumed artifact values when execution no longer needs them. Retention policies and application references determine what stays alive.
- **Inspect and control execution.** Visualize graphs before running them, follow live work in the dashboard, and inspect captured results, timings and records afterward.

Declare a graph once, then submit it with different inputs and configuration. Graphs can include branches, conditional routes and iteration. They can also act as observers or controllers for other work—the dashboard itself is built as a graph.

See [the overview](https://jayrun.readthedocs.io/en/latest/start/overview.html) for applications and [data and lifetimes](https://jayrun.readthedocs.io/en/latest/start/data-and-lifetimes.html) for how artifacts, configuration and resources fit together. The example below introduces these ideas with a single calculation.

## Quick start

Install Jayrun with Python 3.11 or later:

```bash
python -m pip install jayrun
```

The only required third-party runtime dependency is `packaging`. Install `jayrun[yaml]` if you need YAML configuration support; workload libraries such as PyTorch are application dependencies.

Save this program as `first_graph.py` and run `python first_graph.py`. It declares a multiplication, confirms the graph, supplies input and configuration, and prints `21`:

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

`ArtifactContext` supplies the input value, and `ConfigContext` supplies the multiplication factor. The constructor declares fields; Jayrun automatically binds the `source` argument to `self.source` by name and the `outputs` tuple to `self.outputs` by position.

Each submission returns its own `ContextRun`. `run.wait()` waits for finalization, which can include failure, so the example checks the outcome before reading the result. Execution settings separately control policies such as retries and iteration limits.

The same confirmed graph can serve another submission. The [complete walkthrough](https://jayrun.readthedocs.io/en/latest/start/first-graph.html) explains each step, reads the recorded value and visualizes the finished run.

## Inspect your graphs and runs

Once you have a graph, save its structure with `graph.plot.save("graph.html")`. After execution, save the completed run with `run.plot.save("run.html")` to explore captured outcomes, timings, records and reports. Both create interactive HTML viewers that open in a browser, with no additional plotting package.

[![Split-and-join graph with an explicit Splitter, two processing branches and a Join operator](https://raw.githubusercontent.com/jayrun-project/jayrun/main/docs/_static/screenshots/split-and-join.png)](https://jayrun.readthedocs.io/en/latest/guides/visualization/graphs.html)

*A split-and-join graph with two processing branches. Click to explore the interactive declaration.*

For live work, use the [dashboard](https://jayrun.readthedocs.io/en/latest/guides/visualization/dashboard.html) shown above. You can also build your own monitoring or coordination graph using `self.runtime`; see the [Controller example](https://jayrun.readthedocs.io/en/latest/guides/runtime/controller.html). The [visualization and reporting guide](https://jayrun.readthedocs.io/en/latest/guides/evidence/plots.html) covers declarations, registries, completed runs and the dashboard.

To keep diagnostic history beyond an Engine session, pass `Database("execution.sqlite")` from `jayrun.persistence` to `Engine(database=...)`. The Engine owns the database lifecycle. After computation finishes, call `engine.database.flush()` to check that pending history was stored successfully. The [Persistence and Database guide](https://jayrun.readthedocs.io/en/latest/guides/evidence/persistence.html) shows how to write history and read it after the Engine closes. Stored history is separate from application checkpoints and arbitrary artifact storage.

## Tutorials

Ready for a larger workflow? Each tutorial includes a walkthrough, Python source and a notebook, with a small offline CPU path:

| Tutorial | What it demonstrates | Run it |
| --- | --- | --- |
| [Build and validate](https://jayrun.readthedocs.io/en/latest/tutorials/build-and-validate-graph.html) | Properties, diagnostics and corrected execution | [Python](https://github.com/jayrun-project/jayrun/blob/main/tutorials/build_graph.py) · [Notebook](https://github.com/jayrun-project/jayrun/blob/main/tutorials/01_build_graph.ipynb) |
| [Image service](https://jayrun.readthedocs.io/en/latest/tutorials/denoise-images-with-fastapi.html) | Async service, shared client and routing | [Python](https://github.com/jayrun-project/jayrun/blob/main/tutorials/denoise_images.py) · [Notebook](https://github.com/jayrun-project/jayrun/blob/main/tutorials/02_denoise_images.ipynb) |
| [Shared model inference](https://jayrun.readthedocs.io/en/latest/tutorials/mnist-inference-and-training.html#share-a-read-only-model-for-inference) | Read-only model reuse and placement | [Python](https://github.com/jayrun-project/jayrun/blob/main/tutorials/mnist_inference.py) · [Notebook](https://github.com/jayrun-project/jayrun/blob/main/tutorials/03_mnist_inference.ipynb) |
| [Supervised training](https://jayrun.readthedocs.io/en/latest/tutorials/mnist-inference-and-training.html#supervise-replace-and-promote) | Iteration, mutable state and scoped supervision | [Python](https://github.com/jayrun-project/jayrun/blob/main/tutorials/mnist_training.py) · [Notebook](https://github.com/jayrun-project/jayrun/blob/main/tutorials/04_mnist_training.ipynb) |
| [Document service](https://jayrun.readthedocs.io/en/latest/tutorials/document-ingestion.html) | Long-running jobs and transactional publication | [Python](https://github.com/jayrun-project/jayrun/blob/main/tutorials/document_ingestion.py) · [Notebook](https://github.com/jayrun-project/jayrun/blob/main/tutorials/05_document_ingestion.ipynb) |
| [Adapter checkpointing](https://jayrun.readthedocs.io/en/latest/tutorials/checkpointed-adapter-finetuning.html) | Model/optimizer/RNG checkpoints | [Python](https://github.com/jayrun-project/jayrun/blob/main/tutorials/adapter_finetuning.py) · [Notebook](https://github.com/jayrun-project/jayrun/blob/main/tutorials/06_adapter_finetuning.ipynb) |
| [Scientific campaign](https://jayrun.readthedocs.io/en/latest/tutorials/adaptive-scientific-calibration.html) | Adaptive control and reproducibility | [Python](https://github.com/jayrun-project/jayrun/blob/main/tutorials/heat_calibration.py) · [Notebook](https://github.com/jayrun-project/jayrun/blob/main/tutorials/07_heat_calibration.ipynb) |

See the [tutorial setup guide](https://jayrun.readthedocs.io/en/latest/tutorials/index.html) for dependencies and optional GPU/model workloads. For a specific task, follow the guides on [graph construction](https://jayrun.readthedocs.io/en/latest/guides/workflow/index.html), [resources](https://jayrun.readthedocs.io/en/latest/guides/graphs/resources.html), [component interfaces](https://jayrun.readthedocs.io/en/latest/guides/components/index.html) or [application integration](https://jayrun.readthedocs.io/en/latest/guides/integration/index.html).

## Community

Have a question or a workflow to share? Join [GitHub Discussions](https://github.com/jayrun-project/jayrun/discussions). Report bugs and request features through [GitHub Issues](https://github.com/jayrun-project/jayrun/issues); for bugs, include a small reproducible example and your Python and Jayrun versions.

You can also help by reporting confusing examples, suggesting documentation improvements or sharing how you use Jayrun. The [documentation sources](https://github.com/jayrun-project/jayrun/blob/main/docs/index.md) are included in this repository.

## Scope and project status

Jayrun manages graph execution and ownership. Applications supply network transport, authentication, external side effects and checkpoint contents. Placement accounts for declared capacity rather than allocating devices, and cleanup releases framework references rather than guaranteeing an immediate drop in process memory. See [supported behavior and limitations](https://jayrun.readthedocs.io/en/latest/reference/limits.html).

Jayrun provides a tested foundation for graph execution, with ongoing improvements to reliability, usability and documentation. Use imports from `jayrun` and its [documented public modules](https://jayrun.readthedocs.io/en/latest/reference/imports.html); `jayrun.core` and `jayrun.engine` are implementation details.

## License

[Apache License 2.0](https://github.com/jayrun-project/jayrun/blob/main/LICENSE). Copyright 2026 Masoud Yavari.
