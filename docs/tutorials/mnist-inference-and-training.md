```{eval-rst}
.. meta::
   :description: Use Jayrun with PyTorch for MNIST inference and supervised training. Explore shared inference resources, mutable training artifacts and iteration.
```

(tutorial-mnist-inference-and-training)=
# MNIST Inference and Supervised Training

These two tutorials demonstrate shared immutable inference resources and independent
mutable training artifacts. PyTorch owns the model mathematics; Jayrun owns resource
acquisition, placement admission, iteration, and scoped lifecycle control.

## Choose the execution profile

```bash
python -m tutorials.mnist_inference
python -m tutorials.mnist_training
python -m tutorials.mnist_inference --real-mnist --device cuda
python -m tutorials.mnist_training --real-mnist --device cuda
```

The first two commands use a **synthetic lifecycle fixture, not MNIST**. The latter two
download real MNIST and require an available CUDA device. Set `MNIST_DIR` to reuse an
existing cache. The notebooks are `03_mnist_inference.ipynb` and `04_mnist_training.ipynb`.

## Share a read-only model for inference

A centroid classifier is prepared from the training split and saved as a trusted
state-dict checkpoint. `ModelResource` loads it once, selects its device, and shares it
only for read-only inference. Every batch is compared with direct PyTorch predictions;
reported fixture accuracy is not evidence of useful MNIST accuracy.

```{literalinclude} ../../tutorials/mnist_inference.py
:language: python
:pyobject: ModelResource
```

## Keep optimizer state with each model

A `TrainingState` artifact owns its model and optimizer. The optimizer is created only
on the first epoch, after initial placement, and its momentum survives later graph
iterations. The input dataset is shared by convention as read-only; each trial gets a
separate mutable state.

```{literalinclude} ../../tutorials/mnist_training.py
:language: python
:pyobject: TrainingState
```

```{literalinclude} ../../tutorials/mnist_training.py
:language: python
:pyobject: TrainEpoch
```

## Supervise, replace, and promote

Two trials pause at epoch two. A graph-scoped `Supervisor` holds the best and aborts the
other. After that abort drains, the application submits one replacement. The supervisor
compares equal budgets, promotes one winner to epoch four, then requests Stop. A supervisor
controls runs but does not gain the controller's registered-submission capability; replacement
submission here is owned by the surrounding application.

```{literalinclude} ../../tutorials/mnist_training.py
:language: python
:pyobject: SelectTrials
```

Stop drains the accepted iteration and yields `ContextState.FINISHED` with
`run.report.data.stop_requested`. Stop resumes a paused run for drainage; a second explicit `resume()` is unnecessary.

## Capacity and verification boundaries

A paused trial retains its model/placement. This tutorial bounds each selection cohort
at two live models and waits for discarded runs before replacing them. It does not queue
more GPU-resident paused models than the barrier can admit. The 0.15 GB reservation per
small model is an admission declaration, not measured VRAM enforcement or automatic sharding.

To understand the training result, compare trials at equal epoch budgets and inspect their recorded accuracy and loss. Keep a discarded run's finalization separate from submitting its replacement so the old model has time to release its reservation. Use the real-MNIST commands above when you want to evaluate on the actual dataset.

## Canonical source

The complete runnable implementations are [mnist_inference.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/mnist_inference.py) and [mnist_training.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/mnist_training.py).
Use {doc}`the tutorial index <index>` for all notebooks and their execution requirements.
