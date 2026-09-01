(tutorial-mnist-inference-and-training)=
# Run MNIST Inference and Supervised Training on CUDA

This tutorial moves two realistic PyTorch workloads into Jayrun:

1. concurrent inference contexts share one runtime-owned CUDA model;
2. independent training contexts own their models, iterate indefinitely, pause at comparable milestones, and are selected by supervising graphs.

The neural-network code remains ordinary PyTorch. Jayrun handles ownership, graph execution, CUDA reservations, iteration, supervision, waiting, and cleanup.

| Concern | Inference | Training |
| --- | --- | --- |
| Dataset | Artifact per request | Artifact per trial |
| Model | Shared resource | Context-owned artifact |
| CUDA lease follows | Resource `Data` | Model artifact `Data` |
| Repetition | Many submissions | Whole-graph iteration |
| Result | Prediction artifact | Winning model artifact |

:::{note}
The snippets require CUDA-enabled PyTorch and one CUDA device. Loading MNIST arrays and creating the inference checkpoint are ordinary application concerns and are omitted here.
:::

## Configure managed CUDA capacity

Tell Jayrun which capacity it may schedule. Keeping the managed limit below physical memory leaves room for CUDA and the rest of the process.

```python
import torch

from jayrun import Engine
from jayrun.context import ContextRun, ContextState
from jayrun.placement import Backend, Device
from jayrun.settings import EngineSettings, RuntimeDevice


if not torch.cuda.is_available():
    raise RuntimeError("CUDA-enabled PyTorch is required")

total_gb = (
    torch.cuda.get_device_properties(0).total_memory / 1_000_000_000
)

engine_settings = EngineSettings(
    max_workers=8,
    max_tasks=16,
    runtime_devices=(
        RuntimeDevice(device=Device.CPU),
        RuntimeDevice(
            device=Device.GPU,
            backends=(Backend.CUDA,),
            device_id=0,
            memory_limit_gb=total_gb * 0.75,
        ),
    ),
)
```

Jayrun reserves scheduling capacity. PyTorch still allocates and moves tensors.

## Part I: share one inference model

Repeatedly loading the same checkpoint wastes time and GPU memory. A `BaseResource` gives the model one runtime-managed lifecycle.

### 1. Define the model and resource

```python
from torch import nn

from jayrun import BaseResource, ConfigField, Data


class MnistClassifier(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.classifier = nn.Linear(784, 10)

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        return self.classifier(images.flatten(1))


class MnistModelResource(BaseResource):
    requirements = ("torch",)

    def __init__(self, *, name=None, description=None) -> None:
        super().__init__(name=name, description=description)
        self.checkpoint_path = ConfigField(value_type=str, required=True)
        self.memory_gb = ConfigField(value_type=float, required=True)

    def setup(self) -> Data:
        placement = self.placement.cuda(memory_gb=self.memory_gb.value)
        device = torch.device("cuda", placement.device_id)

        state = torch.load(
            self.checkpoint_path.value,
            map_location="cpu",
            weights_only=True,
        )
        model = MnistClassifier()
        model.load_state_dict(state)
        model.to(device).eval()
        return Data(value=model, placement=placement)

    def teardown(self, data: Data) -> None:
        data.value.to("cpu")
        torch.cuda.empty_cache()
```

The returned `Data` associates the model with its placement lease. Jayrun can cache that value, reuse it across matching contexts, and tear it down during shutdown.

### 2. Define the inference operators

```python
import numpy as np

from jayrun import (
    Artifact,
    ArtifactField,
    BaseOperator,
    ResourceField,
)


class PrepareImages(BaseOperator):
    def __init__(self, *, images, outputs, name=None, description=None):
        super().__init__(name=name, description=description)
        self.images = ArtifactField(required=True)
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> torch.Tensor:
        return torch.from_numpy(
            np.asarray(self.images.value, dtype=np.uint8)
        ).float().div_(255.0)


class PredictDigits(BaseOperator):
    def __init__(self, *, images, outputs, name=None, description=None):
        super().__init__(name=name, description=description)
        self.images = ArtifactField(required=True)
        self.model = ResourceField(required=True, parallel_safe=True)
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> torch.Tensor:
        placement = self.model.placement
        device = torch.device("cuda", placement.device_id)
        images = self.images.value.to(device, non_blocking=True)

        with torch.inference_mode():
            logits = self.model.value(images)

        return logits.argmax(dim=1).cpu()


class FormatPredictions(BaseOperator):
    def __init__(self, *, predictions, outputs, name=None, description=None):
        super().__init__(name=name, description=description)
        self.predictions = ArtifactField(required=True)
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> list[int]:
        return [int(value) for value in self.predictions.value.tolist()]
```

`parallel_safe=True` is an explicit promise that concurrent inference may use the cached model. Jayrun does not make mutable model code thread-safe automatically.

### 3. Build and configure the graph

```python
from jayrun import ArtifactFlow, ConfigContext, GraphDefinition


raw_images = Artifact(name="raw_images")
image_batch = Artifact(name="image_batch")
predictions = Artifact(name="predictions")

prepare = PrepareImages(
    images=raw_images,
    outputs=(image_batch,),
    name="prepare_images",
)
predict = PredictDigits(
    images=image_batch,
    outputs=(predictions,),
    name="predict_digits",
)
format_predictions = FormatPredictions(
    predictions=predictions,
    outputs=(predictions,),
    name="format_predictions",
)

raw_flow = ArtifactFlow(prepare, artifact=raw_images)
batch_flow = ArtifactFlow(predict, artifact=image_batch)
prediction_flow = ArtifactFlow(format_predictions, artifact=predictions)

inference_graph = GraphDefinition(
    raw_flow,
    batch_flow,
    prediction_flow,
    entry_flows=(raw_flow,),
)

model_resource = MnistModelResource(name="mnist_model")
inference_graph.bind_resources({predict.model: model_resource})

inference_configs = ConfigContext(graph=inference_graph)
inference_configs.set(
    {
        model_resource.checkpoint_path: str(checkpoint_path),
        model_resource.memory_gb: 0.15,
    }
)
```

Only `raw_images` is supplied per request. The final `predictions` value is the graph exit.

### 4. Submit concurrent batches

```python
from jayrun import ArtifactContext


with Engine(engine_settings) as engine:
    runs = []

    for images in validation_batches:
        artifacts = ArtifactContext(graph=inference_graph)
        artifacts.set({raw_images: images})
        runs.append(engine.submit(artifacts, inference_configs))

    engine.wait(tuple(runs), timeout=60)

prediction_batches = []
for run in runs:
    if run.state is not ContextState.FINISHED:
        raise RuntimeError("inference failed") from run.report.failure
    prediction_batches.append(run.artifact(predictions).value)
```

Every context owns its input and output artifacts. All of them acquire the same runtime-owned model. The tuple wait shares one timeout budget, and the returned `ContextRun`s remain readable after engine shutdown.

## Part II: supervise iterative training

Training reverses model ownership: every trial mutates its own model, so the model must be a context artifact rather than a shared resource.

The procedure is:

1. submit four trials with different learning rates and model seeds;
2. let each graph iterate with `max_iterations=None`;
3. publish progress and pause at iteration 10;
4. submit a supervisor that aborts the lower half and leaves survivors paused;
5. wait for aborted runs to finalize, then submit replacement trials;
6. submit another supervisor that selects and resumes one winner;
7. at iteration 20, submit a finalizer that stops iteration and resumes the paused winner;
8. read the retained, placed model from the winning run.

### 1. Define context-owned values

```python
from dataclasses import dataclass
from enum import Enum


PROGRESS_KEY = "mnist_trial_progress"
SELECTION_ITERATION = 10
FINAL_ITERATION = 20


@dataclass(frozen=True, slots=True)
class MnistDataset:
    training_images: torch.Tensor
    training_labels: torch.Tensor
    validation_images: torch.Tensor
    validation_labels: torch.Tensor


class TrainableMnistClassifier(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.layers = nn.Sequential(
            nn.Flatten(),
            nn.Linear(784, 128),
            nn.ReLU(),
            nn.Linear(128, 10),
        )

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        return self.layers(images)


@dataclass(frozen=True, slots=True)
class TrialProgress:
    iteration: int
    accuracy: float
    loss: float
    learning_rate: float
    device: str
```

The dataset can be shared by the application as an immutable value, but every submission receives a separately initialized model object.

### 2. Train exactly one graph iteration

One invocation performs one epoch, publishes progress into its own context, and returns the updated model with its placement.

```python
class TrainMnistEpoch(BaseOperator):
    requirements = ("torch",)

    def __init__(self, *, dataset, model, outputs, name=None, description=None):
        super().__init__(name=name, description=description)
        self.dataset = ArtifactField(required=True)
        self.model = ArtifactField(required=True)
        self.learning_rate = ConfigField(value_type=float, required=True)
        self.batch_size = ConfigField(value_type=int, required=True)
        self.memory_gb = ConfigField(value_type=float, required=True)
        self.pause_iterations = ConfigField(value_type=tuple, required=True)
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> Data:
        dataset = self.dataset.value
        model = self.model.value
        previous = self.context.get_value("training_iteration")
        iteration = 1 if previous is None else int(previous) + 1
        placement = self.model.placement

        if placement.device is Device.CPU:
            placement = self.placement.cuda(memory_gb=self.memory_gb.value)
            device = torch.device("cuda", placement.device_id)
            model.to(device)
        else:
            device = torch.device("cuda", placement.device_id)

        optimizer = torch.optim.SGD(
            model.parameters(),
            lr=self.learning_rate.value,
        )
        model.train()
        total_loss = 0.0

        permutation = torch.randperm(len(dataset.training_images))
        for indices in permutation.split(self.batch_size.value):
            images = dataset.training_images[indices].to(device)
            labels = dataset.training_labels[indices].to(device)
            optimizer.zero_grad(set_to_none=True)
            loss_value = nn.functional.cross_entropy(model(images), labels)
            loss_value.backward()
            optimizer.step()
            total_loss += float(loss_value.detach().cpu()) * len(indices)

        model.eval()
        correct = 0
        with torch.inference_mode():
            for start in range(
                0,
                len(dataset.validation_images),
                self.batch_size.value,
            ):
                images = dataset.validation_images[
                    start : start + self.batch_size.value
                ].to(device)
                labels = dataset.validation_labels[
                    start : start + self.batch_size.value
                ].to(device)
                correct += int(
                    (model(images).argmax(1) == labels).sum().cpu()
                )

        progress = TrialProgress(
            iteration=iteration,
            accuracy=correct / len(dataset.validation_images),
            loss=total_loss / len(dataset.training_images),
            learning_rate=self.learning_rate.value,
            device=str(device),
        )
        self.context.store("training_iteration", iteration)
        self.context.store(PROGRESS_KEY, progress)

        if iteration in self.pause_iterations.value:
            self.context.pause()

        return Data(value=model, placement=placement)
```

On the first iteration, the model reserves CUDA placement and moves to that device. Returning `Data(value=model, placement=placement)` makes the lease follow the artifact. Later iterations receive the placed artifact and reuse the reservation.

Progress is stored in the worker's own context. An authorized supervisor reads it from the worker's `ContextRun`; there is no separate runtime-wide key store.

### 3. Build the training graph

```python
dataset = Artifact(name="dataset")
model = Artifact(name="model")

train_epoch = TrainMnistEpoch(
    dataset=dataset,
    model=model,
    outputs=(model,),
    name="train_mnist_epoch",
)

dataset_flow = ArtifactFlow(train_epoch, artifact=dataset)
model_flow = ArtifactFlow(train_epoch, artifact=model)

training_graph = GraphDefinition(
    dataset_flow,
    model_flow,
    entry_flows=(dataset_flow, model_flow),
)
```

The dataset and model are both entry artifacts. Regenerating `model` carries the trained value into the next graph iteration and makes the final model an exit.

### 4. Make iteration supervisor-controlled

```python
from jayrun.settings import ArtifactPolicy, ContextSettings


training_settings = ContextSettings(
    artifact_policy=ArtifactPolicy(
        retain_all=False,
        retained_artifacts=(model,),
        release_entry_artifacts=True,
    ),
    max_iterations=None,
)
```

`max_iterations=None` removes a numeric limit; it does not remove lifecycle control. Trials pause at known milestones, and authorized runs later resume, stop iteration, or abort them.

Only the model is retained as a terminal artifact.

### 5. Create one submission per trial

```python
from jayrun import ArtifactContext, ConfigContext


def create_trial(
    dataset_value: MnistDataset,
    *,
    learning_rate: float,
    seed: int,
    memory_gb: float,
) -> tuple[ArtifactContext, ConfigContext]:
    torch.manual_seed(seed)

    artifacts = ArtifactContext(graph=training_graph)
    artifacts.set(
        {
            dataset: dataset_value,
            model: TrainableMnistClassifier(),
        }
    )

    configs = ConfigContext(graph=training_graph)
    configs.set(
        {
            train_epoch.learning_rate: learning_rate,
            train_epoch.batch_size: 128,
            train_epoch.memory_gb: memory_gb,
            train_epoch.pause_iterations: (
                SELECTION_ITERATION,
                FINAL_ITERATION,
            ),
        }
    )
    return artifacts, configs
```

Using full context objects keeps graph association and validation explicit. Each model is created before submission, so trial ownership is unambiguous.

### 6. Define the supervising graph

The supervisor receives its candidates from `self.runtime.contexts`. Jayrun has already restricted that tuple to the exact graph objects named at supervisor submission.

```python
class SelectionMode(Enum):
    HOLD = "hold"
    PROMOTE = "promote"
    FINALIZE = "finalize"


@dataclass(frozen=True, slots=True)
class TrialEvaluation:
    context_id: int
    progress: TrialProgress


@dataclass(frozen=True, slots=True)
class TrialSelection:
    mode: SelectionMode
    retained_context_ids: tuple[int, ...]
    aborted_context_ids: tuple[int, ...]
    ranking: tuple[TrialEvaluation, ...]


class SelectTrials(BaseOperator):
    def __init__(self, *, trigger, outputs, name=None, description=None):
        super().__init__(name=name, description=description)
        self.trigger = ArtifactField(required=True)
        self.selection_iteration = ConfigField(value_type=int, required=True)
        self.mode = ConfigField(value_type=SelectionMode, required=True)
        self.timeout_seconds = ConfigField(value_type=float, required=True)
        self.outputs = (ArtifactField(required=True),)

    async def execute(self) -> TrialSelection:
        candidates = self.runtime.contexts
        if not candidates:
            raise RuntimeError("no training contexts are available")

        await self.runtime.wait_async(
            candidates,
            ContextState.PAUSED,
            timeout=self.timeout_seconds.value,
        )

        for run in candidates:
            if run.state is not ContextState.PAUSED:
                raise RuntimeError(
                    f"trial {run.context_id} terminated before selection"
                )

        evaluations = []
        for run in candidates:
            progress = run.get_value(PROGRESS_KEY)
            if not isinstance(progress, TrialProgress):
                raise RuntimeError("trial did not publish progress")
            if progress.iteration != self.selection_iteration.value:
                raise RuntimeError("trial paused at the wrong iteration")
            evaluations.append(
                TrialEvaluation(run.context_id, progress)
            )

        ranking = tuple(
            sorted(
                evaluations,
                key=lambda item: (
                    item.progress.accuracy,
                    -item.progress.loss,
                ),
                reverse=True,
            )
        )

        retained_count = (
            max(1, len(ranking) // 2)
            if self.mode.value is SelectionMode.HOLD
            else 1
        )
        retained = ranking[:retained_count]
        discarded = ranking[retained_count:]
        runs_by_id = {run.context_id: run for run in candidates}

        for evaluation in discarded:
            runs_by_id[evaluation.context_id].abort()

        if self.mode.value is SelectionMode.PROMOTE:
            runs_by_id[retained[0].context_id].resume()
        elif self.mode.value is SelectionMode.FINALIZE:
            winner = runs_by_id[retained[0].context_id]
            winner.stop()
            winner.resume()

        return TrialSelection(
            mode=self.mode.value,
            retained_context_ids=tuple(
                item.context_id for item in retained
            ),
            aborted_context_ids=tuple(
                item.context_id for item in discarded
            ),
            ranking=ranking,
        )
```

The modes express three decisions:

| Mode | Action |
| --- | --- |
| `HOLD` | Abort the lower half and leave survivors paused |
| `PROMOTE` | Abort all but one candidate and resume the winner |
| `FINALIZE` | Stop future iteration and resume the paused winner so it can finalize |

Stop means stop iteration; abort means prevent further dispatch.

Build the supervisor as an ordinary graph:

```python
selection = Artifact(name="selection")
select_trials = SelectTrials(
    trigger=selection,
    outputs=(selection,),
    name="select_trials",
)
selection_flow = ArtifactFlow(select_trials, artifact=selection)
selection_graph = GraphDefinition(
    selection_flow,
    entry_flows=(selection_flow,),
)
```

### 7. Submit a supervisor

```python
def submit_supervisor(
    engine: Engine,
    *,
    iteration: int,
    mode: SelectionMode,
) -> ContextRun:
    artifacts = ArtifactContext(graph=selection_graph)
    artifacts.set({selection: True})

    configs = ConfigContext(graph=selection_graph)
    configs.set(
        {
            select_trials.selection_iteration: iteration,
            select_trials.mode: mode,
            select_trials.timeout_seconds: 120.0,
        }
    )

    return engine.submit(
        artifacts,
        configs,
        supervises=training_graph,
    )
```

`supervises=training_graph` grants access to all currently live contexts created from that exact graph object. The supervisor needs no candidate IDs in its configuration.

The supervisor cannot originate replacement trials. Its output is a decision; application code remains the clear submission authority.

### 8. Run the adaptive procedure

```python
initial_parameters = (
    (0.003, 101),
    (0.010, 102),
    (0.030, 103),
    (0.080, 104),
)

with Engine(engine_settings) as engine:
    initial_runs = []
    for learning_rate, seed in initial_parameters:
        artifacts, configs = create_trial(
            dataset_value,
            learning_rate=learning_rate,
            seed=seed,
            memory_gb=0.10,
        )
        initial_runs.append(
            engine.submit(
                artifacts,
                configs,
                context_settings=training_settings,
            )
        )

    first_supervisor = submit_supervisor(
        engine,
        iteration=SELECTION_ITERATION,
        mode=SelectionMode.HOLD,
    )
    first_supervisor.wait(timeout=130)
    first_selection = first_supervisor.artifact(selection).value

    aborted = tuple(
        run
        for run in initial_runs
        if run.context_id in first_selection.aborted_context_ids
    )
    engine.wait(aborted, timeout=120)

    best_rate = first_selection.ranking[0].progress.learning_rate
    replacement_runs = []
    for index, learning_rate in enumerate(
        (best_rate * 0.8, best_rate * 1.2)
    ):
        artifacts, configs = create_trial(
            dataset_value,
            learning_rate=learning_rate,
            seed=1000 + index,
            memory_gb=0.10,
        )
        replacement_runs.append(
            engine.submit(
                artifacts,
                configs,
                context_settings=training_settings,
            )
        )

    promotion = submit_supervisor(
        engine,
        iteration=SELECTION_ITERATION,
        mode=SelectionMode.PROMOTE,
    )
    promotion.wait(timeout=130)
    promotion_result = promotion.artifact(selection).value
    winner_id = promotion_result.retained_context_ids[0]

    all_trials = initial_runs + replacement_runs
    promotion_aborted = tuple(
        run
        for run in all_trials
        if run.context_id in promotion_result.aborted_context_ids
    )
    engine.wait(promotion_aborted, timeout=120)

    winner = next(
        run for run in all_trials if run.context_id == winner_id
    )

    finalizer = submit_supervisor(
        engine,
        iteration=FINAL_ITERATION,
        mode=SelectionMode.FINALIZE,
    )
    finalizer.wait(timeout=130)
    winner.wait(timeout=120)

    if winner.state is not ContextState.STOPPED:
        raise RuntimeError("winning trial did not stop cleanly")

    winning_model = winner.artifact(model)
```

Waiting for aborted runs before adding replacements is operationally useful: it confirms the decision and lets their model-owned placement leases be released before new models request CUDA capacity.

The winner ends in `STOPPED` because it completed after a stop-iteration request. `winning_model.placement` still identifies the CUDA reservation attached to the retained model result.

## Why this structure matters

| Responsibility | Jayrun expression |
| --- | --- |
| Load one serving model | `BaseResource.setup()` |
| Reuse it across requests | Bound `ResourceField` |
| Reserve CUDA capacity | `self.placement.cuda()` |
| Keep a lease with a value | `Data(value=..., placement=...)` |
| Repeat one training epoch | `ContextSettings(max_iterations=None)` |
| Keep each trial independent | Context-owned model artifact |
| Publish comparable progress | `self.context.store(...)` |
| Create a stable decision point | `self.context.pause()` |
| Observe selected graphs | `self.runtime.contexts` |
| Remove weak trials | `run.abort()` |
| Continue a winner | `run.resume()` |
| Finish indefinite iteration | `run.stop()` then `run.resume()` |
| Read the winning model | `winner.artifact(model)` |

The application no longer owns an epoch polling loop or manipulates another trial's model. Training contexts own iteration and placement; supervisors own graph-scoped decisions; application code owns new submissions.

For the underlying contracts, see {doc}`Resources <../concepts/resources>`, {doc}`Placement and Capacity <../runtime/placement-and-capacity>`, {doc}`Runtime Interface <../interfaces/runtime>`, and {doc}`Engine and Context Lifecycle <../runtime/engine-and-context-lifecycle>`.
