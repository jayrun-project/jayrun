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
    ArtifactContext,
    Engine,
    ConfigField,
)
from jayrun.properties import (
    BackendProperty,
    DTypeProperty,
    DeviceProperty,
    ShapeProperty,
    TypeProperty,
)


class TemperatureScaledModel(nn.Module):
    def __init__(self, model: nn.Module, temperature: float) -> None:
        super().__init__()
        self.model = model
        self.temperature = temperature

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.model(inputs) / self.temperature

class PrepareDataset(BaseOperator):
    requirements = ("numpy", "torch")

    def __init__(
        self,
        *,
        dataset: Artifact,
        dtype: torch.dtype = torch.float32,
        outputs: tuple[Artifact | None, ...],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.dtype = ConfigField(value_type=str, required=False, default=str(dtype).removeprefix("torch."))
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
                    DTypeProperty(dtype),
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
        return torch.from_numpy(prepared).to(getattr(torch, self.dtype.value))

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

def build_graph(dtype: torch.dtype = torch.float32):
    dataset = Artifact(name="dataset")
    model = Artifact(name="model")

    prepare = PrepareDataset(
        dataset=dataset,
        dtype=dtype,
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

    graph = GraphDefinition(
        dataset_flow,
        model_flow,
        entry_flows=(dataset_flow, model_flow),
    )
    return graph, dataset, model


def run_demo() -> dict[str, object]:
    """Detect a declaration mismatch, then execute the corrected graph."""
    bad, _, _ = build_graph(torch.float64)
    mismatch = bad.validate()
    assert not mismatch.valid and len(mismatch.mismatched_edges) == 1
    graph, dataset, model = build_graph()
    assert graph.validate().valid
    graph.confirm()
    rng = np.random.default_rng(42)
    table = np.column_stack((rng.normal(size=(24, 784)), np.arange(24) % 10))
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(42)
        classifier = nn.Linear(784, 10)
    inputs = ArtifactContext()
    inputs.set({dataset: table, model: classifier})
    with Engine() as engine:
        run = engine.submit(graph, inputs)
        run.wait(timeout=30)
        if run.state.value != "finished":
            raise RuntimeError(str(run.report.data.failure))
        result = run.artifact(model).value
        assert isinstance(result, TemperatureScaledModel)
    return {"mismatches_detected": 1, "corrected_valid": True,
            "result_type": type(result).__name__, "graph_id": graph.graph_id}


if __name__ == "__main__":
    print(run_demo())
