"""Independent model/optimizer artifacts and graph-scoped adaptive supervision."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import torch
from jayrun import (Artifact, ArtifactContext, ArtifactField, ArtifactFlow, BaseOperator,
                    ConfigContext, ConfigField, Data, Engine, GraphDefinition, Supervisor)
from jayrun.context import ContextState
from jayrun.placement import Device
from jayrun.settings import ArtifactPolicy, ContextSettings
from tutorials.mnist_data import Classifier, Dataset, engine_settings, load_data


@dataclass(slots=True)
class TrainingState:
    model: Classifier
    seed: int
    learning_rate: float
    optimizer: torch.optim.SGD | None = None
    epoch: int = 0
    updates: int = 0
    accuracy: float = 0.0
    loss: float = 0.0


def new_state(seed: int = 1, learning_rate: float = .05) -> TrainingState:
    if learning_rate <= 0:
        raise ValueError("learning_rate must be positive")
    # Construct on the caller thread before scheduling; no worker changes global RNG.
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = Classifier()
    return TrainingState(model, seed, learning_rate)


def train_epoch(state: TrainingState, data: Dataset, *, batch_size: int = 64) -> None:
    """Ordinary PyTorch code, also used by the direct baseline."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if state.optimizer is None:
        state.optimizer = torch.optim.SGD(state.model.parameters(), lr=state.learning_rate,
                                          momentum=.9)
    device = next(state.model.parameters()).device
    order = torch.randperm(len(data.training_images),
                           generator=torch.Generator().manual_seed(state.seed*1000 + state.epoch))
    state.model.train()
    total = 0.0
    for indices in order.split(batch_size):
        images, labels = data.training_images[indices].to(device), data.training_labels[indices].to(device)
        state.optimizer.zero_grad(set_to_none=True)
        loss = torch.nn.functional.cross_entropy(state.model(images), labels)
        loss.backward()
        state.optimizer.step()
        state.updates += 1
        total += float(loss.detach().cpu())*len(indices)
    state.model.eval()
    correct = 0
    with torch.inference_mode():
        for images, labels in zip(data.validation_images.split(batch_size),
                                 data.validation_labels.split(batch_size)):
            predictions = state.model(images.to(device)).argmax(1).cpu()
            correct += int((predictions == labels).sum())
    state.epoch += 1
    state.loss = total/len(data.training_images)
    state.accuracy = correct/len(data.validation_images)


class TrainEpoch(BaseOperator):
    requirements = ("torch",)

    def __init__(self, *, dataset: Artifact, state: Artifact,
                 outputs: tuple[Artifact, ...]) -> None:
        super().__init__()
        self.dataset, self.state = ArtifactField(required=True), ArtifactField(required=True)
        self.device_kind = ConfigField(value_type=str, required=False, default="cpu")
        self.pause_at = ConfigField(value_type=tuple, required=False, default=())
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> Data:
        state: TrainingState = self.state.value
        placement = self.state.placement
        if self.device_kind.value == "cuda" and placement.device is Device.CPU:
            placement = self.placement.cuda(memory_gb=.15)
            state.model.to(torch.device("cuda", placement.device_id))
        train_epoch(state, self.dataset.value)
        self.context.record("training", {"epoch": state.epoch, "loss": state.loss,
                                         "accuracy": state.accuracy, "updates": state.updates})
        if state.epoch in self.pause_at.value:
            self.context.pause(None)
        return Data(value=state, placement=placement)


class SelectTrials(BaseOperator):
    def __init__(self, *, trigger: Artifact, outputs: tuple[Artifact, ...]) -> None:
        super().__init__()
        self.trigger = ArtifactField(required=True)
        self.mode = ConfigField(value_type=str, required=True)
        self.expected_epoch = ConfigField(value_type=int, required=True)
        self.outputs = (ArtifactField(required=True),)

    async def execute(self) -> dict[str, object]:
        candidates = tuple(run for run in self.runtime.unfinished_contexts if not run.state.is_terminal)
        if not candidates:
            raise RuntimeError("no live training candidates")
        await asyncio.gather(*(run.wait_async(ContextState.PAUSED, timeout=120) for run in candidates))
        for run in candidates:
            records = run.records("training")
            if run.state is not ContextState.PAUSED or not records:
                raise RuntimeError("candidate terminated before selection")
            if records[-1].value["epoch"] != self.expected_epoch.value:
                raise RuntimeError("candidate has the wrong comparison budget")
        ranked = sorted(candidates, key=lambda run: (
            -run.records("training")[-1].value["accuracy"],
            run.records("training")[-1].value["loss"], run.context_id))
        winner, *losers = ranked
        for run in losers:
            run.abort()
        mode = self.mode.value
        if mode == "promote":
            winner.resume()
        elif mode == "finish":
            winner.stop()  # Stop drains a paused iteration; no redundant resume.
        elif mode != "hold":
            raise ValueError("mode must be hold, promote, or finish")
        return {"winner": winner.context_id, "aborted": [run.context_id for run in losers],
                "mode": mode}


def build_training_graph():
    dataset, state = Artifact(name="dataset"), Artifact(name="training_state")
    train = TrainEpoch(dataset=dataset, state=state, outputs=(state,))
    data_flow, state_flow = ArtifactFlow(train, artifact=dataset), ArtifactFlow(train, artifact=state)
    graph_1 = GraphDefinition(data_flow, state_flow, entry_flows=(data_flow, state_flow))
    graph_1.confirm()
    return graph_1, dataset, state, train


def build_selection_graph():
    trigger = Artifact(name="selection")
    select = SelectTrials(trigger=trigger, outputs=(trigger,))
    flow = ArtifactFlow(select, artifact=trigger)
    graph_2 = GraphDefinition(flow, entry_flows=(flow,))
    graph_2.confirm()
    return graph_2, trigger, select


def run_demo(*, real_mnist: bool = False, device: str = "cpu") -> dict[str, object]:
    data = load_data(real_mnist=real_mnist, training_samples=1024, validation_samples=256)
    graph, dataset, state_artifact, train = build_training_graph()
    selection_graph, trigger, select = build_selection_graph()
    runs = []
    settings = ContextSettings(max_iterations=None, record_history_limit=4,
        artifact_policy=ArtifactPolicy(retained_artifacts=(state_artifact,), release_entry_artifacts=True))
    with Engine(engine_settings(device)) as engine:
        def submit(state: TrainingState):
            artifacts, configs = ArtifactContext(), ConfigContext()
            artifacts.set({dataset: data, state_artifact: state})
            configs.set({train.device_kind: device, train.pause_at: (2, 4)})
            run = engine.submit(graph, artifacts, configs, settings=settings)
            runs.append(run)
            return run

        def choose(mode: str, epoch: int) -> dict[str, object]:
            artifacts, configs = ArtifactContext(), ConfigContext()
            artifacts.set({trigger: True})
            configs.set({select.mode: mode, select.expected_epoch: epoch})
            supervisor = engine.submit(selection_graph, artifacts, configs, authority=Supervisor(graph))
            supervisor.wait(timeout=180)
            if supervisor.state is not ContextState.FINISHED:
                raise RuntimeError(str(supervisor.report.data.failure))
            return supervisor.artifact(trigger).value

        try:
            submit(new_state(1, .05)); submit(new_state(2, .02))
            held = choose("hold", 2)
            # Await discarded models before adding a replacement; paused models retain placement.
            for run in runs:
                if run.context_id in held["aborted"]:
                    run.wait(timeout=30)
            submit(new_state(3, .04))
            promoted = choose("promote", 2)
            for run in runs:
                if run.context_id in promoted["aborted"]:
                    run.wait(timeout=30)
            final = choose("finish", 4)
            for run in runs:
                run.wait(timeout=60)
            winner = next(run for run in runs if run.context_id == final["winner"])
            result: TrainingState = winner.artifact(state_artifact).value
            assert winner.state is ContextState.FINISHED and winner.report.data.stop_requested
            assert result.epoch == 4 and result.optimizer is not None
            return {"dataset": data.source, "device": device, "trials": len(runs),
                    "outcomes": [run.state.value for run in runs],
                    "winner_epoch": result.epoch, "accuracy": result.accuracy,
                    "optimizer_updates": result.updates, "stop_requested": True}
        finally:
            for run in runs:
                if not run.state.is_terminal:
                    run.abort()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-mnist", action="store_true")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    args = parser.parse_args()
    torch.set_num_threads(1)
    print(run_demo(real_mnist=args.real_mnist, device=args.device))
