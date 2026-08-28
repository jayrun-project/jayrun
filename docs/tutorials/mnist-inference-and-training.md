(tutorial-mnist-inference-and-training)=
# Run MNIST Inference and Supervised Training on CUDA

This tutorial moves a realistic PyTorch workflow into Jayrun in two parts.

Part I serves concurrent MNIST inference requests with one model shared by every context. Part II launches independent training trials, pauses them at comparable milestones, removes weak trials, creates replacements, and continues only the best model.

The PyTorch code remains ordinary PyTorch. Jayrun takes responsibility for graph structure, runtime ownership, CUDA capacity, concurrent contexts, iteration, supervision, and cleanup.

By the end, you will have used the same core abstractions for both serving and training:

| Concern | Inference | Training |
| --- | --- | --- |
| Dataset input | Artifact | Artifact |
| Model owner | Shared resource | Individual context artifact |
| CUDA lease follows | Resource data | Model artifact data |
| Repeated work | Many submitted contexts | Indefinite context iteration |
| Coordination | Engine scheduling | Supervising contexts |
| Result | Predictions | Winning placed model |

:::{note}
This chapter uses real MNIST tensors, PyTorch, and CUDA. A CUDA-enabled PyTorch installation and one CUDA device are required. Dataset downloading and checkpoint creation are ordinary application concerns, so the snippets assume that MNIST arrays and a checkpoint path are already available.
:::

## The workflow we are migrating

A conventional implementation usually accumulates several responsibilities in one training script:

1. load a model onto a GPU;
2. serve batches through that model;
3. construct many training trials with different parameters;
4. track every trial's iteration and metrics;
5. stop weak trials and create replacements;
6. retain the winning model;
7. release GPU memory even when work fails.

Jayrun separates those responsibilities by ownership. A shared inference model belongs to a resource. A training model belongs to one context as an artifact. A supervising context makes decisions about other contexts, while the application remains responsible for submitting new work.

That distinction is the central idea of the tutorial.

## Configure CUDA capacity once

Both parts use an engine that knows which devices it may manage:

```python
import torch

from jayrun import Engine
from jayrun.context import ContextState
from jayrun.placement import Backend, Device
from jayrun.settings import EngineSettings, RuntimeDevice


if not torch.cuda.is_available():
    raise RuntimeError("CUDA-enabled PyTorch is required")

total_memory_gb = (
    torch.cuda.get_device_properties(0).total_memory / 1_000_000_000
)

engine_settings = EngineSettings(
    max_workers=8,
    max_tasks=48,
    runtime_devices=(
        RuntimeDevice(device=Device.CPU),
        RuntimeDevice(
            device=Device.GPU,
            backends=(Backend.CUDA,),
            device_id=0,
            memory_limit_gb=total_memory_gb * 0.75,
        ),
    ),
)
```

The managed limit is intentionally smaller than physical GPU memory. Jayrun can coordinate declared reservations inside that budget while leaving capacity for CUDA, PyTorch, and the surrounding process.

The reservation describes scheduling capacity; PyTorch still performs the actual tensor allocation.

## Part I: inference with one shared model

Inference requests should not load an identical checkpoint into GPU memory repeatedly. We therefore make the model a resource owned by the engine runtime.

The declaration progresses in the same order as the data:

1. define the model resource;
2. define operators;
3. connect artifact flows;
4. create the graph and bind the resource;
5. submit independent inference contexts.

### 1. Define the PyTorch model

```python
from torch import nn


class MnistClassifier(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.classifier = nn.Linear(784, 10)

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        return self.classifier(images.flatten(1))
```

Jayrun does not require a framework-specific model base class. The model remains a normal `nn.Module`.

### 2. Put the shared model in a resource

```python
from jayrun import BaseResource, ConfigField, Data


class MnistModelResource(BaseResource):
    requirements = ("torch",)

    def __init__(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
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

Three details matter here:

1. `self.placement.cuda(...)` reserves CUDA capacity through Jayrun.
2. `Data(value=model, placement=placement)` attaches the lease to the resource value. The placement therefore lives as long as the cached model data.
3. `setup()` and `teardown()` define one runtime-managed lifecycle instead of one lifecycle per inference request.

### 3. Define the inference operators

The graph prepares a NumPy batch, runs CUDA inference, and converts the result into ordinary Python values.

```python
import numpy as np

from jayrun import (
    Artifact,
    ArtifactField,
    BaseOperator,
    ResourceField,
)


class PrepareImages(BaseOperator):
    requirements = ("numpy", "torch")

    def __init__(
        self,
        *,
        images: Artifact,
        outputs: tuple[Artifact | None, ...],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.images = ArtifactField(required=True)
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> torch.Tensor:
        return torch.from_numpy(
            np.asarray(self.images.value, dtype=np.uint8)
        ).float().div_(255.0)


class PredictDigits(BaseOperator):
    requirements = ("torch",)

    def __init__(
        self,
        *,
        images: Artifact,
        outputs: tuple[Artifact | None, ...],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
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
    requirements = ("torch",)

    def __init__(
        self,
        *,
        predictions: Artifact,
        outputs: tuple[Artifact | None, ...],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.predictions = ArtifactField(required=True)
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> list[int]:
        return [int(value) for value in self.predictions.value.tolist()]
```

`parallel_safe=True` tells Jayrun that concurrent executions may acquire the cached resource. This is appropriate because the model is in evaluation mode and inference does not mutate it. It is an explicit promise made by the component author; it does not make arbitrary model code thread-safe.

### 4. Build artifact flows

Each flow identifies the operators that consume one artifact:

```python
from jayrun import ArtifactFlow


raw_images = Artifact(name="raw_images")
image_batch = Artifact(name="image_batch")
predictions = Artifact(name="predictions")

prepare_images = PrepareImages(
    images=raw_images,
    outputs=(image_batch,),
    name="prepare_images",
)
predict_digits = PredictDigits(
    images=image_batch,
    outputs=(predictions,),
    name="predict_digits",
)
format_predictions = FormatPredictions(
    predictions=predictions,
    outputs=(predictions,),
    name="format_predictions",
)

raw_images_flow = ArtifactFlow(prepare_images, artifact=raw_images)
image_batch_flow = ArtifactFlow(predict_digits, artifact=image_batch)
predictions_flow = ArtifactFlow(
    format_predictions,
    artifact=predictions,
)
```

The declarations describe this data path:

```text
raw_images -> image_batch -> predictions -> formatted predictions
```

Only `raw_images` comes from the submitting application. The final regeneration of `predictions` becomes the retained output.

### 5. Create the graph and bind the resource

```python
from jayrun import ConfigContext, GraphDefinition


inference_graph = GraphDefinition(
    raw_images_flow,
    image_batch_flow,
    predictions_flow,
    entry_flows=(raw_images_flow,),
)

model_resource = MnistModelResource(name="mnist_model")
inference_graph.bind_resources(
    {predict_digits.model: model_resource}
)

inference_configs = ConfigContext(
    graph=inference_graph,
    name="inference_configs",
)
inference_configs.set(
    {
        model_resource.checkpoint_path: str(checkpoint_path),
        model_resource.memory_gb: 0.15,
    }
)
```

Binding connects the operator's model port to the shared declaration. The configuration tells the resource what to load and how much managed CUDA capacity to reserve.

### 6. Submit concurrent inference contexts

```python
from jayrun import ArtifactContext


with Engine(engine_settings) as engine:
    context_ids = []

    for images in validation_batches:
        artifacts = ArtifactContext(graph=inference_graph)
        artifacts.set({raw_images: images})
        context_ids.append(
            engine.submit(artifacts, inference_configs)
        )

    prediction_batches = []
    for context_id in context_ids:
        snapshot = engine.wait(
            context_id,
            state=ContextState.FINISHED,
        )
        if snapshot is None or snapshot.failure is not None:
            raise RuntimeError(f"inference failed: {context_id}")
        prediction_batches.append(
            snapshot.artifact(predictions).value
        )
        engine.delete(context_id)
```

Every submission owns its input batch and retained predictions. All submissions acquire the same cached CUDA model, so model setup and teardown belong to the engine runtime rather than to individual requests.

## Part II: supervised iterative training

Training needs different ownership. Every trial mutates its own model, so sharing one model resource would be incorrect. The dataset and model are entry artifacts, and each context receives a distinct model instance.

The training procedure is:

1. submit several trials with different learning rates and seeds;
2. let every trial iterate without a predefined maximum;
3. publish validation accuracy and pause at iteration 10;
4. submit a supervisor that ranks the trials and aborts the lower half;
5. wait for those aborted trials to become terminal;
6. submit replacement trials with parameters derived from the survivors;
7. select one winner and resume it;
8. pause again at iteration 20, request stop, and retain the winning model.

### 1. Define the context-owned values

```python
from dataclasses import dataclass
from uuid import uuid4


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
        self.instance_id = uuid4().hex
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

`instance_id` is not required by Jayrun. It makes model ownership easy to observe: every context starts with a unique model and retains that identity through every iteration.

### 2. Train one iteration and preserve placement

One invocation of the operator performs one epoch. Jayrun repeats the graph, so iteration policy is separate from model code.

```python
from jayrun import Data


class TrainMnistEpoch(BaseOperator):
    requirements = ("torch",)

    def __init__(
        self,
        *,
        dataset: Artifact,
        model: Artifact,
        outputs: tuple[Artifact | None, ...],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.dataset = ArtifactField(required=True)
        self.model = ArtifactField(required=True)
        self.learning_rate = ConfigField(value_type=float, required=True)
        self.batch_size = ConfigField(value_type=int, required=True)
        self.memory_gb = ConfigField(value_type=float, required=True)
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> Data:
        dataset = self.dataset.value
        model = self.model.value
        previous = self.context.get_value("training_iteration")
        iteration = 1 if previous is None else int(previous) + 1
        placement = self.model.placement

        if placement.device is Device.CPU:
            placement = self.placement.cuda(
                memory_gb=self.memory_gb.value
            )
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

        for indices in torch.randperm(
            len(dataset.training_images)
        ).split(self.batch_size.value):
            images = dataset.training_images[indices].to(device)
            labels = dataset.training_labels[indices].to(device)
            optimizer.zero_grad(set_to_none=True)
            loss_value = nn.functional.cross_entropy(
                model(images),
                labels,
            )
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
                    (model(images).argmax(dim=1) == labels).sum().cpu()
                )

        progress = TrialProgress(
            iteration=iteration,
            accuracy=correct / len(dataset.validation_images),
            loss=total_loss / len(dataset.training_images),
            learning_rate=self.learning_rate.value,
            device=str(device),
        )
        self.context.store("training_iteration", iteration)
        self.runtime.store(
            (PROGRESS_KEY, self.context.id),
            progress,
        )

        if iteration in (SELECTION_ITERATION, FINAL_ITERATION):
            self.context.pause(None)

        return Data(value=model, placement=placement)
```

The returned `Data` is essential. It regenerates the model artifact while preserving the CUDA lease. On the first iteration, the operator reserves placement and transfers the model. Later iterations receive the same placed artifact and reuse the same lease.

The operator publishes progress in runtime-scoped storage because the supervisor belongs to a different context. Context-scoped storage tracks the local iteration counter; runtime-scoped storage exposes comparable metrics to authorized supervisors.

At iterations 10 and 20, `pause(None)` requests an indefinite pause. This creates a stable decision point: the model remains retained and placed while the supervisor inspects it.

### 3. Build the training graph

```python
from jayrun import GraphDefinition


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

Both artifacts are entries:

- the dataset is the input used by every epoch;
- the model is the independently initialized state owned by one trial.

The operator regenerates `model`, so the most recent trained model is the graph output carried into the next iteration.

### 4. Enable indefinite iteration

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

`max_iterations=None` means Jayrun does not impose a numeric iteration limit. It does not mean the trial cannot be controlled. The trial pauses at declared milestones, and a supervisor later requests `resume`, `abort`, or `stop`.

The artifact policy retains only the model result. Entry artifacts may be released when they are no longer required, reducing retained state after finalization.

### 5. Create one submission per parameter set

```python
from jayrun import ArtifactContext, ConfigContext


def create_trial_submission(
    dataset_value: MnistDataset,
    learning_rate: float,
    memory_gb: float,
) -> tuple[ArtifactContext, ConfigContext]:
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
        }
    )
    return artifacts, configs
```

The model is constructed before submission and placed in the `ArtifactContext`. This makes ownership unambiguous: each submitted context receives one unique model artifact, and its placement follows that artifact.

### 6. Define a supervising operator

The supervisor waits until all candidates are paused at the same iteration. It ranks them by validation accuracy, then applies a selection policy.

```python
import asyncio
import time
from enum import Enum

class SelectionMode(Enum):
    HOLD = "hold"
    PROMOTE = "promote"
    FINALIZE = "finalize"


class SelectTrials(BaseOperator):
    def __init__(
        self,
        *,
        candidates: Artifact,
        outputs: tuple[Artifact | None, ...],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.candidates = ArtifactField(required=True)
        self.selection_iteration = ConfigField(
            value_type=int,
            required=True,
        )
        self.selection_mode = ConfigField(
            value_type=SelectionMode,
            required=True,
        )
        self.timeout_seconds = ConfigField(
            value_type=float,
            required=True,
        )
        self.outputs = (ArtifactField(required=True),)

    async def execute(self) -> tuple[int, ...]:
        candidate_ids = self.candidates.value
        deadline = time.monotonic() + self.timeout_seconds.value

        while time.monotonic() < deadline:
            progress_by_context = {}
            paused_context_ids = set(self.runtime.paused_context_ids)

            for context_id in candidate_ids:
                record = self.runtime.get_record(
                    (PROGRESS_KEY, context_id)
                )

                if (
                    context_id not in paused_context_ids
                    or record is None
                    or record.value.iteration
                    != self.selection_iteration.value
                ):
                    break

                progress_by_context[context_id] = record.value
            else:
                if len(progress_by_context) == len(candidate_ids):
                    break

            await asyncio.sleep(0.01)
        else:
            raise TimeoutError("trials did not reach the selection point")

        ranking = sorted(
            progress_by_context.items(),
            key=lambda item: (item[1].accuracy, -item[1].loss),
            reverse=True,
        )
        mode = self.selection_mode.value
        retained_count = len(ranking) // 2 if mode is SelectionMode.HOLD else 1
        retained_ids = tuple(
            context_id
            for context_id, _ in ranking[:retained_count]
        )

        for context_id, _ in ranking[retained_count:]:
            self.runtime.abort(context_id)

        if mode is SelectionMode.PROMOTE:
            self.runtime.resume(retained_ids[0])
        elif mode is SelectionMode.FINALIZE:
            self.runtime.stop(retained_ids[0])
            self.runtime.resume(retained_ids[0])

        return retained_ids
```

This operator uses only `self.runtime` and immutable snapshots. It cannot submit replacement trials. That boundary is intentional: supervising contexts observe and control registered contexts, while the application decides what new work to originate.

The three modes have distinct meanings:

| Mode | Decision at the milestone |
| --- | --- |
| `HOLD` | Abort the lower half and leave the survivors paused. |
| `PROMOTE` | Abort every candidate except the winner, then resume the winner. |
| `FINALIZE` | Request stop for the winner and resume it so the paused iteration can finalize orderly. |

`stop` means stop iteration. `abort` means stop dispatching additional work and drain the context. They are not interchangeable.

### 7. Build the supervisor graph

```python
candidates = Artifact(name="candidates")
select_trials = SelectTrials(
    candidates=candidates,
    outputs=(candidates,),
    name="select_trials",
)
selection_flow = ArtifactFlow(
    select_trials,
    artifact=candidates,
)
selection_graph = GraphDefinition(
    selection_flow,
    entry_flows=(selection_flow,),
)
```

The supervisor is an ordinary Jayrun graph. The special authority comes from the settings used when its context is submitted.

### 8. Submit the search procedure

The following helpers keep application orchestration readable:

```python
def submit_trial(
    engine: Engine,
    dataset_value: MnistDataset,
    learning_rate: float,
    memory_gb: float,
) -> int:
    artifacts, configs = create_trial_submission(
        dataset_value,
        learning_rate,
        memory_gb,
    )
    return engine.submit(
        artifacts,
        configs,
        context_settings=training_settings,
    )


def submit_selection(
    engine: Engine,
    candidate_ids: tuple[int, ...],
    iteration: int,
    mode: SelectionMode,
) -> int:
    artifacts = ArtifactContext(graph=selection_graph)
    artifacts.set({candidates: candidate_ids})
    configs = ConfigContext(graph=selection_graph)
    configs.set(
        {
            select_trials.selection_iteration: iteration,
            select_trials.selection_mode: mode,
            select_trials.timeout_seconds: 120.0,
        }
    )
    return engine.submit(
        artifacts,
        configs,
        context_settings=ContextSettings(supervising=True),
    )
```

Now the whole search reads as a sequence of decisions:

```python
initial_learning_rates = (0.003, 0.01, 0.03, 0.08)

with Engine(engine_settings) as engine:
    initial_ids = tuple(
        submit_trial(
            engine,
            dataset_value,
            learning_rate,
            model_reservation_gb,
        )
        for learning_rate in initial_learning_rates
    )

    hold_id = submit_selection(
        engine,
        initial_ids,
        SELECTION_ITERATION,
        SelectionMode.HOLD,
    )
    hold = engine.wait(
        hold_id,
        state=ContextState.FINISHED,
    )
    survivors = hold.artifact(candidates).value

    aborted_ids = tuple(
        context_id
        for context_id in initial_ids
        if context_id not in survivors
    )
    for context_id in aborted_ids:
        engine.wait(
            context_id,
            state=ContextState.ABORTED,
        )

    replacement_rates = (0.024, 0.036)
    replacement_ids = tuple(
        submit_trial(
            engine,
            dataset_value,
            learning_rate,
            model_reservation_gb,
        )
        for learning_rate in replacement_rates
    )

    promotion_id = submit_selection(
        engine,
        survivors + replacement_ids,
        SELECTION_ITERATION,
        SelectionMode.PROMOTE,
    )
    promotion = engine.wait(
        promotion_id,
        state=ContextState.FINISHED,
    )
    winner_id = promotion.artifact(candidates).value[0]

    finalizer_id = submit_selection(
        engine,
        (winner_id,),
        FINAL_ITERATION,
        SelectionMode.FINALIZE,
    )
    engine.wait(
        finalizer_id,
        state=ContextState.FINISHED,
    )

    winner = engine.wait(
        winner_id,
        state=ContextState.STOPPED,
    )
    winning_model = winner.artifact(model)
```

Waiting for the aborted contexts before submitting replacements is useful for two reasons. It confirms the lifecycle decision, and it allows their artifact-owned placement leases to become releasable before new models request CUDA capacity.

The application never runs a manual epoch loop, and it never moves another context's model directly. It submits declarative inputs and parameters; the training context owns iteration and placement; the supervisor owns selection decisions.

## What Jayrun is doing for you

The final design replaces incidental orchestration code with explicit runtime concepts:

| Conventional responsibility | Jayrun expression |
| --- | --- |
| Load one serving model | `BaseResource.setup()` |
| Reuse it across requests | Bound `ResourceField` |
| Attach model to CUDA capacity | `Data(..., placement=placement)` |
| Execute one epoch repeatedly | `max_iterations=None` |
| Preserve each trial's model | Context-owned model artifact |
| Publish comparable metrics | `self.runtime.store(...)` |
| Pause at a decision point | `self.context.pause(None)` |
| Inspect other trials | Supervising context snapshots |
| Prune weak trials | `self.runtime.abort(...)` |
| Continue a winner | `self.runtime.resume(...)` |
| Finish indefinite iteration | `self.runtime.stop(...)` |
| Reclaim runtime-owned state | Context deletion and engine shutdown |

The important benefit is not fewer lines inside the neural network. It is that ownership and lifecycle become visible in the program:

- the inference model clearly belongs to the runtime;
- each training model clearly belongs to one context;
- each CUDA lease follows the value that needs it;
- every selection occurs at an explicit, inspectable milestone;
- every terminal result is available through a context snapshot.

## Where to go next

Use these chapters when you want the complete contract behind a specific part of the example:

- {doc}`Resources <../concepts/resources>` for shared resource identity and teardown;
- {doc}`Placement and Capacity <../runtime/placement-and-capacity>` for reservation and lease behavior;
- {doc}`Execution Settings <../settings/execution-settings>` for iteration and retry policy;
- {doc}`Runtime Interface <../interfaces/runtime>` for supervision capabilities and lifecycle requests;
- {doc}`Engine and Context Lifecycle <../runtime/engine-and-context-lifecycle>` for waiting, deletion, and shutdown.
