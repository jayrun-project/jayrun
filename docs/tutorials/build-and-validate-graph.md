```{eval-rst}
.. meta::
   :description: Validate a NumPy and PyTorch computation graph with Jayrun. Diagnose a producer and consumer dtype mismatch, then execute the corrected graph.
```

(tutorial-build-and-validate-graph)=
# Build and Validate a Graph

Learn to diagnose a declared dtype mismatch, confirm a corrected graph, and submit values for execution. You should already know basic Python and what NumPy arrays and PyTorch tensors are; no training expertise is needed. The tiny model only gives us a concrete payload to pass between steps.

## Run it

Follow [tutorial setup](index.md#prepare-your-environment), then run from the repository root:

```bash
python -m tutorials.build_graph
```

Open `tutorials/01_build_graph.ipynb` for the guided lesson. The Python snippets below are consecutive notebook cells: run them in Jupyter with top-level `await`. For a terminal run, use the module command above.

## 1. Follow the two flows

The dataset flows through **PrepareDataset → TrainModel**. A model flows through **TrainModel → ScaleModel**. TrainModel waits for both inputs. An Artifact names a data position; its value belongs to a submission. An operator that outputs the same artifact replaces that value along its flow.

The builder declares both entry flows because the application supplies both the initial table and the initial model. Inspect it before executing anything.

<!-- notebook: 01_build_graph.ipynb#inspect-builder -->
```python
import asyncio
import inspect
import numpy as np
import torch
from jayrun import ArtifactContext, Engine
from jayrun.context import ContextState
from tutorials import build_graph as lesson

print(inspect.getsource(lesson.build_graph))
```

## 2. Diagnose a declaration without running it

PrepareDataset promises the dtype selected by the builder. TrainModel requires float32. Choose float64 and inspect the report: exactly one producer/consumer edge should be incompatible. Validation compares declared properties; it does not examine actual input arrays.

<!-- notebook: 01_build_graph.ipynb#validate -->
```python
bad, _, _ = lesson.build_graph(torch.float64)
validation = bad.validate()
print("Valid:", validation.valid)
print("Mismatched edges:", len(validation.mismatched_edges))
assert not validation.valid and len(validation.mismatched_edges) == 1

graph, dataset, model = lesson.build_graph(torch.float32)
assert graph.validate().valid
graph.confirm()
print("Corrected graph confirmed:", graph.confirmed)
```

## 3. Supply values and inspect the outcome

The table has 784 feature columns and one label column. ArtifactContext maps the two entry identities to a table and a classifier. Constructors declare fields; Jayrun binds artifact arguments to fields by name and output tuples by position. The Engine returns a ContextRun, whose final state must be checked before reading a result.

Jupyter owns an event loop, so the synchronous Engine block runs through asyncio.to_thread. This is orchestration code using the existing tutorial operators.

<!-- notebook: 01_build_graph.ipynb#execute -->
```python
def execute_corrected_graph():
    rng = np.random.default_rng(42)
    table = np.column_stack((rng.normal(size=(24, 784)), np.arange(24) % 10))
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(42)
        classifier = torch.nn.Linear(784, 10)
    inputs = ArtifactContext({dataset: table, model: classifier})
    with Engine() as engine:
        run = engine.submit(graph, inputs)
        run.wait(timeout=30)
        if run.state is not ContextState.FINISHED:
            raise RuntimeError(str(run.report.data.failure))
        return run.artifact(model).value

result = await asyncio.to_thread(execute_corrected_graph)
print("Result type:", type(result).__name__)
assert isinstance(result, lesson.TemperatureScaledModel)
```

## 4. Try another declaration

Predict what happens if the producer declares float16. Run the cell to check your prediction. Then change float16 to float32: the mismatch count should become zero. A fixed declaration still does not prove model quality or runtime payload correctness.

<!-- notebook: 01_build_graph.ipynb#experiment -->
```python
alternative, _, _ = lesson.build_graph(torch.float16)
print("Alternative mismatches:", len(alternative.validate().mismatched_edges))
```

You have separated declaration, validation, confirmation, submission, and result inspection. The complete CLI demonstration also returns mismatches_detected=1, corrected_valid=True, and result_type="TemperatureScaledModel". Continue to the image lesson for conditional routes and reusable resources.

## Read the canonical implementation

The complete [build_graph.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/build_graph.py) supplies the operators and application helpers used above. This excerpt shows graph wiring:

```{literalinclude} ../../tutorials/build_graph.py
:language: python
:pyobject: build_graph
```

Continue with [the tutorial collection](index.md) or [supported behavior and limitations](../reference/limits.md).
