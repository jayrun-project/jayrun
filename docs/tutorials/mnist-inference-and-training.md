```{eval-rst}
.. meta::
   :description: Use Jayrun with PyTorch for MNIST inference and supervised training. Explore shared inference resources, mutable training artifacts and iteration.
```

(tutorial-mnist-inference-and-training)=
# MNIST Inference and Supervised Training

These two lessons compare shared read-only inference resources with independent mutable training artifacts. Start with inference, then continue to supervision. PyTorch performs model mathematics; Jayrun manages resource lifetimes, execution, iteration, and scoped control. You should know a basic PyTorch inference/training loop and [artifact/resource lifetimes](../start/data-and-lifetimes.md).

## Choose the execution profile

Follow [tutorial setup](index.md#prepare-your-environment), then run:

```bash
python -m tutorials.mnist_inference
python -m tutorials.mnist_training
```

Both default to synthetic lifecycle fixtures, **not MNIST**. Actual dataset evaluation is opt-in; CUDA also needs an available GPU:

```bash
python -m tutorials.mnist_inference --real-mnist --device cpu
python -m tutorials.mnist_training --real-mnist --device cuda
```

Set `MNIST_DIR` to reuse a dataset cache. Use `03_mnist_inference.ipynb` and `04_mnist_training.ipynb` for the guided cells below. Start each notebook in a fresh kernel; the Python snippets use Jupyter top-level `await`.

## Share a read-only model for inference

### 1. Inspect the resource binding

ModelResource owns loading, device selection, and teardown. InferBatch declares a ResourceField and consumes image values from each run. The builder binds the field before confirmation. The field allows parallel use because this example's model is used read-only; the flag does not add synchronization to an arbitrary model.

<!-- notebook: 03_mnist_inference.ipynb#inspect-builder -->
```python
import asyncio
import inspect
import tempfile
import torch
from pathlib import Path
from jayrun import ArtifactContext, Engine
from jayrun.context import ContextState
from tutorials import mnist_inference as lesson
from tutorials.mnist_data import Classifier, load_data

print(inspect.getsource(lesson.ModelResource))
print(inspect.getsource(lesson.build_graph))
```

(submit-two-contexts-to-the-same-graph)=
### 2. Run two batches with one shared model

For this wiring exercise we save a randomly initialized classifier: its predictions are not useful accuracy evidence. The Engine can reuse the same compatible resource across both submissions. Each run supplies a different batch and keeps its own result. Teardown occurs through Engine ownership; merely finishing a batch does not unload the cache.

<!-- notebook: 03_mnist_inference.ipynb#shared-inference -->
```python
def infer_two_batches():
    data = load_data(training_samples=64, validation_samples=32)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(7)
        model = Classifier().eval()
    batches = data.validation_images.split(16)
    with tempfile.TemporaryDirectory() as temporary:
        checkpoint = Path(temporary) / "model.pt"
        torch.save(model.state_dict(), checkpoint)
        graph, images = lesson.build_graph(checkpoint)
        with Engine() as engine:
            runs = [engine.submit(graph, ArtifactContext({images: batch})) for batch in batches]
            predictions = []
            for run in runs:
                run.wait(timeout=30)
                if run.state is not ContextState.FINISHED:
                    raise RuntimeError(str(run.report.data.failure))
                predictions.extend(run.artifact(images).value)
    with torch.inference_mode():
        expected = model(data.validation_images).argmax(1).tolist()
    assert predictions == expected
    return {"contexts": len(runs), "predictions": len(predictions), "matches_direct": True}

shared = await asyncio.to_thread(infer_two_batches)
print(shared)
assert shared == {"contexts": 2, "predictions": 32, "matches_direct": True}
```

### 3. Run the complete inference demonstration

The complete demonstration prepares a centroid classifier and checks eight batches against direct predictions. contexts counts submitted batches; predictions counts individual samples; matches_direct_baseline checks integration equivalence. accuracy describes only the selected dataset/model pair.

<!-- notebook: 03_mnist_inference.ipynb#complete-inference -->
```python
REAL_MNIST = False  # True explicitly downloads the real dataset.
DEVICE = "cpu"       # Use "cuda" only with an available GPU and suitable PyTorch.
result = await asyncio.to_thread(lesson.run_demo, real_mnist=REAL_MNIST, device=DEVICE)
print({key: result[key] for key in ("dataset", "device", "contexts", "predictions", "matches_direct_baseline", "accuracy")})
assert result["contexts"] == 8 and result["predictions"] == 256
assert result["matches_direct_baseline"]
```

### Try it yourself

Change split(16) to split(8) in the wiring exercise. Expect four contexts and still 32 predictions, with the same direct result; update the expected contexts count in the summary assertion. Reuse requires a compatible resource type, configuration, and sharing policy; separate Engines have separate ownership.

The complete real-data path creates a trusted state-dict checkpoint from its centroid model. Declared GPU capacity is admission accounting, not allocation or sharding. Requested unavailable CUDA is an error. Do not interpret the fixture's accuracy as MNIST accuracy.

## Supervise, replace, and promote

### 1. Inspect one training iteration

TrainEpoch consumes dataset and TrainingState, then outputs the updated state under the same artifact identity. One graph iteration performs one epoch. The optimizer is created once and retained inside TrainingState so momentum survives later iterations. A pause requests a lifecycle boundary; it does not release the model or its placement.

<!-- notebook: 04_mnist_training.ipynb#inspect-training -->
```python
import asyncio
import inspect
from jayrun import ArtifactContext, ConfigContext, Engine
from jayrun.context import ContextState
from jayrun.settings import ContextSettings
from tutorials import mnist_training as lesson
from tutorials.mnist_data import load_data

print(inspect.getsource(lesson.TrainEpoch))
print(inspect.getsource(lesson.build_training_graph))
```

### 2. Pause one run, inspect it, then Stop

Submit a small run with no fixed iteration limit and a pause at epoch two. After PAUSED, the latest record should show epoch=2. Stop prevents another graph iteration and drains accepted work, producing FINISHED with stop_requested. Stop already handles a paused run; a separate resume is unnecessary here.

<!-- notebook: 04_mnist_training.ipynb#pause-and-stop -->
```python
def inspect_pause_boundary():
    data = load_data(training_samples=64, validation_samples=32)
    graph, dataset, state, train = lesson.build_training_graph()
    with Engine() as engine:
        run = engine.submit(
            graph, ArtifactContext({dataset: data, state: lesson.new_state(11)}),
            ConfigContext({train.pause_at: (2,)}),
            settings=ContextSettings(max_iterations=None, record_history_limit=4),
        )
        try:
            run.wait(ContextState.PAUSED, timeout=30)
            record = run.records("training")[-1].value
            assert record["epoch"] == 2
            print("At review:", dict(record))
            run.stop()
            run.wait(timeout=30)
            assert run.state is ContextState.FINISHED and run.report.data.stop_requested
            return {"state": run.state.value, "epoch": run.artifact(state).value.epoch,
                    "stop_requested": run.report.data.stop_requested}
        finally:
            if not run.state.is_terminal:
                run.abort()

boundary = await asyncio.to_thread(inspect_pause_boundary)
print(boundary)
assert boundary == {"state": "finished", "epoch": 2, "stop_requested": True}
```

### 3. Understand the selection sequence

The complete example starts two trials and compares them at epoch two. It holds the best, aborts the other, waits for finalization, then submits a replacement. A second comparison promotes the best to epoch four; the last selection requests Stop.

SelectTrials runs with Supervisor(training_graph), so it can inspect and control that graph's runs. The surrounding application submits the replacement: a Supervisor does not gain Controller submission authority. Read the selection code with that division of responsibility in mind.

<!-- notebook: 04_mnist_training.ipynb#inspect-selection -->
```python
print(inspect.getsource(lesson.SelectTrials))
```

<!-- notebook: 04_mnist_training.ipynb#complete-supervision -->
```python
REAL_MNIST = False
DEVICE = "cpu"
result = await asyncio.to_thread(lesson.run_demo, real_mnist=REAL_MNIST, device=DEVICE)
print(result)
assert result["trials"] == 3
assert sorted(result["outcomes"]) == ["aborted", "aborted", "finished"]
assert result["winner_epoch"] == 4 and result["stop_requested"]
```

### Try it yourself

Change the small pause exercise to pause at epoch three and update its expected epoch. Inspect how the optimizer update count changes. To continue instead of finishing at the boundary, call resume and provide a later pause or finite iteration limit so the run still terminates.

The full selection keeps at most two live models per cohort. Wait for aborted trials before replacing them because paused runs retain capacity. The reservation is not measured VRAM enforcement. Equal epoch budgets make the comparison meaningful within this example, but fixture accuracy is not real-MNIST model quality.

## Read the canonical implementations

[mnist_inference.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/mnist_inference.py) binds the shared model; [mnist_training.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/mnist_training.py) supplies the training and selection graphs. The complete application orchestration connects three training submissions and three graph-scoped selection runs:

```{literalinclude} ../../tutorials/mnist_training.py
:language: python
:pyobject: run_demo
```

Continue with [adapter checkpointing](checkpointed-adapter-finetuning.md) to save and restore mutable training state.
