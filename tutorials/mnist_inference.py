"""Shared read-only inference model, declared placement, and per-run predictions."""
from __future__ import annotations

import tempfile
from pathlib import Path

import torch
from jayrun import (Artifact, ArtifactContext, ArtifactField, ArtifactFlow, BaseOperator,
                    BaseResource, ConfigField, Data, Engine, GraphDefinition, ResourceField)
from jayrun.context import ContextState
from tutorials.mnist_data import Classifier, engine_settings, load_data


class ModelResource(BaseResource):
    requirements = ("torch",)

    def __init__(self, *, checkpoint: str, device: str = "cpu") -> None:
        super().__init__()
        self.checkpoint = ConfigField(value_type=str, required=False, default=checkpoint)
        self.device_kind = ConfigField(value_type=str, required=False, default=device)

    def setup(self) -> Data:
        with torch.random.fork_rng(devices=[]):
            model = Classifier()
        model.load_state_dict(torch.load(self.checkpoint.value, map_location="cpu", weights_only=True))
        model.eval().requires_grad_(False)
        if self.device_kind.value == "cuda":
            placement = self.placement.cuda(memory_gb=.15)
            model.to(torch.device("cuda", placement.device_id))
            return Data(value=model, placement=placement)
        return Data(value=model)

    def teardown(self, data: Data) -> None:
        data.value.to("cpu")


class InferBatch(BaseOperator):
    requirements = ("torch",)

    def __init__(self, *, images: Artifact, outputs: tuple[Artifact, ...]) -> None:
        super().__init__()
        self.images = ArtifactField(required=True)
        self.model = ResourceField(required=True, parallel_safe=True)
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> list[int]:
        model = self.model.value
        device = next(model.parameters()).device
        with torch.inference_mode():
            return model(self.images.value.to(device)).argmax(1).cpu().tolist()


def build_graph(checkpoint: Path, device: str = "cpu"):
    images = Artifact(name="images")
    infer = InferBatch(images=images, outputs=(images,))
    flow = ArtifactFlow(infer, artifact=images)
    graph = GraphDefinition(flow, entry_flows=(flow,))
    graph.bind_resources({infer.model: ModelResource(checkpoint=str(checkpoint), device=device)}); graph.confirm()
    return graph, images


def run_demo(*, real_mnist: bool = False, device: str = "cpu") -> dict[str, object]:
    settings = engine_settings(device)  # Reject unavailable requested hardware before downloading.
    data = load_data(real_mnist=real_mnist, training_samples=1024, validation_samples=256)
    values = data.training_images.flatten(1)
    centroids = torch.stack([values[data.training_labels == digit].mean(0) for digit in range(10)])
    with torch.random.fork_rng(devices=[]):
        model = Classifier().eval()
    with torch.no_grad():
        model.linear.weight.copy_(centroids)
        model.linear.bias.copy_(-.5*centroids.square().sum(1))
    batches = data.validation_images.split(32)
    with tempfile.TemporaryDirectory(prefix="jayrun-inference-") as folder:
        checkpoint = Path(folder)/"centroid_model.pt"
        torch.save(model.state_dict(), checkpoint)
        graph, images = build_graph(checkpoint, device)
        with Engine(settings) as engine:
            runs = []
            for batch in batches:
                artifacts = ArtifactContext(); artifacts.set({images: batch})
                runs.append(engine.submit(graph, artifacts))
            predictions = []
            for run in runs:
                run.wait(timeout=60)
                if run.state is not ContextState.FINISHED:
                    raise RuntimeError(str(run.report.data.failure))
                predictions.extend(run.artifact(images).value)
    with torch.inference_mode():
        expected = model(data.validation_images).argmax(1).tolist()
    assert predictions == expected
    accuracy = float((torch.tensor(predictions) == data.validation_labels).float().mean())
    return {"dataset": data.source, "device": device, "contexts": len(runs),
            "predictions": len(predictions), "matches_direct_baseline": True,
            "accuracy": accuracy}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-mnist", action="store_true")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    args = parser.parse_args()
    torch.set_num_threads(1)
    print(run_demo(real_mnist=args.real_mnist, device=args.device))
