(tutorial-build-and-validate-graph)=
# Build and Validate a Graph

This tutorial builds one realistic PyTorch graph and validates it before execution. It covers the complete declaration flow:

1. define operators and their artifact contracts;
2. create artifacts and operator instances;
3. connect `ArtifactFlow` objects;
4. create a `GraphDefinition`;
5. validate and inspect the graph;
6. correct a detected mismatch.

The graph prepares a NumPy classification dataset, trains an existing PyTorch model, and wraps the model with temperature scaling. It intentionally contains one common integration error: preprocessing produces `float64`, while training requires `float32`.

## Install the dependencies

```bash
python -m pip install "jayrun[plotting]" numpy torch
```

## 1. Define the model wrapper

```python
from __future__ import annotations

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from jayrun import (
    Artifact,
    ArtifactField,
    ArtifactFlow,
    BaseOperator,
    GraphDefinition,
)
from jayrun.properties import (
    BackendProperty,
    DTypeProperty,
    DeviceProperty,
    ShapeProperty,
    TypeProperty,
)
from jayrun.validation import GraphValidator


class TemperatureScaledModel(nn.Module):
    def __init__(self, model: nn.Module, temperature: float) -> None:
        super().__init__()
        self.model = model
        self.temperature = temperature

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.model(inputs) / self.temperature
```

This is ordinary PyTorch code. Jayrun does not require a framework-specific model class.

## 2. Define the operators

`PrepareDataset` accepts a NumPy table with 784 feature columns and one target column. `torch.from_numpy()` preserves NumPy's usual `float64` dtype.

```python
class PrepareDataset(BaseOperator):
    requirements = ("numpy", "torch")

    def __init__(
        self,
        *,
        dataset: Artifact,
        outputs: tuple[Artifact | None, ...],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.dataset = ArtifactField(
            required=True,
            properties=(
                TypeProperty(np.ndarray),
                ShapeProperty((None, 785)),
            ),
        )
        self.outputs = (
            ArtifactField(
                required=True,
                properties=(
                    TypeProperty(torch.Tensor),
                    DTypeProperty(torch.float64),
                    ShapeProperty((None, 785)),
                    DeviceProperty("cpu"),
                    BackendProperty("torch"),
                ),
            ),
        )

    def execute(self) -> torch.Tensor:
        values = self.dataset.value
        features = values[:, :-1]
        targets = values[:, -1:]
        normalized = (features - features.mean(0)) / (
            features.std(0) + 1e-8
        )
        prepared = np.concatenate((normalized, targets), axis=1)
        return torch.from_numpy(prepared)
```

`TrainModel` requires `float32`. Its contract therefore disagrees with the producer even though both operators use `torch.Tensor` with the same shape.

```python
class TrainModel(BaseOperator):
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
        self.dataset = ArtifactField(
            required=True,
            properties=(
                TypeProperty(torch.Tensor),
                DTypeProperty(torch.float32),
                ShapeProperty((None, 785)),
                DeviceProperty("cpu"),
                BackendProperty("torch"),
            ),
        )
        self.model = ArtifactField(
            required=True,
            properties=(TypeProperty(nn.Module),),
        )
        self.outputs = (
            ArtifactField(
                required=True,
                properties=(TypeProperty(nn.Module),),
            ),
        )

    def execute(self) -> nn.Module:
        dataset = self.dataset.value
        model = self.model.value
        features = dataset[:, :-1]
        targets = dataset[:, -1].long()
        optimizer = torch.optim.SGD(model.parameters(), lr=0.01)
        optimizer.zero_grad(set_to_none=True)
        loss = F.cross_entropy(model(features), targets)
        loss.backward()
        optimizer.step()
        return model
```

`ScaleModel` accepts and returns `nn.Module`, so the model path remains compatible.

```python
class ScaleModel(BaseOperator):
    requirements = ("torch",)

    def __init__(
        self,
        *,
        model: Artifact,
        outputs: tuple[Artifact | None, ...],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.model = ArtifactField(
            required=True,
            properties=(TypeProperty(nn.Module),),
        )
        self.outputs = (
            ArtifactField(
                required=True,
                properties=(TypeProperty(nn.Module),),
            ),
        )

    def execute(self) -> nn.Module:
        return TemperatureScaledModel(self.model.value, temperature=1.5)
```

The artifact fields describe compatibility independently from the execution methods. Validation can therefore detect this integration error without running NumPy or PyTorch work.

## 3. Create the artifacts and operators

```python
dataset = Artifact(name="dataset")
model = Artifact(name="model")

prepare = PrepareDataset(
    dataset=dataset,
    outputs=(dataset,),
    name="prepare_dataset",
)
train = TrainModel(
    dataset=dataset,
    model=model,
    outputs=(model,),
    name="train_model",
)
scale = ScaleModel(
    model=model,
    outputs=(model,),
    name="scale_model",
)
```

The application supplies the initial dataset and model. Each operator regenerates the artifact it transforms.

## 4. Connect the artifact flows

```python
dataset_flow = ArtifactFlow(
    prepare,
    train,
    artifact=dataset,
)
model_flow = ArtifactFlow(
    train,
    scale,
    artifact=model,
)
```

An `ArtifactFlow` lists the operators that consume its artifact, in consumption order:

- `prepare` and `train` consume `dataset`;
- `train` and `scale` consume `model`.

The flows describe artifact paths rather than a flat list of every operator in the graph.

## 5. Create the graph

```python
graph = GraphDefinition(
    dataset_flow,
    model_flow,
    entry_flows=(dataset_flow, model_flow),
)
```

Both flows are entries because the application supplies both initial values. `scale` regenerates `model` after its last consumption, so the resulting model becomes the graph exit.

## 6. Validate and inspect the graph

```python
validator = GraphValidator(graph)
validation = validator.validate()

assert not validation.valid
assert len(validation.mismatched_edges) == 1

validator.report.print()
validator.plot.save("plot_property_mismatch.html")
```

The graph structure is coherent, but one artifact edge is incompatible:

| Edge | Produced | Required | Result |
| --- | --- | --- | --- |
| `prepare_dataset -> train_model` | `torch.float64` | `torch.float32` | Mismatch |
| `train_model -> scale_model` | `nn.Module` | `nn.Module` | Match |

The same validation result powers programmatic inspection, text reporting, and plotting.

```{raw} html
<iframe
    src="../_static/plot_property_mismatch.html"
    title="Interactive graph-validation result"
    style="width: 100%; height: 900px; border: 1px solid #d1d5db; border-radius: 6px; background: #ffffff;"
    loading="lazy"
></iframe>
```

## 7. Correct the contract

The producer should return the dtype required by training:

```python
prepared = np.concatenate(
    (normalized, targets),
    axis=1,
).astype(np.float32)

return torch.from_numpy(prepared)
```

Change the corresponding output declaration to:

```python
DTypeProperty(torch.float32)
```

The producer and consumer contracts now agree, so validation succeeds. Keep the property metadata aligned with the value the operator actually returns; removing metadata merely hides the error.

Continue with {doc}`Denoise Images with FastAPI <denoise-images-with-fastapi>` to place a graph inside an asynchronous web application and select execution routes per request.
