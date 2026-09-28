"""Checkpointed low-rank language-model adaptation with a persistent training artifact.

The default small GRU is an offline lifecycle fixture, not evidence of LLM quality.
See peft_finetuning.py for an optional real pretrained-transformer integration.
"""
from __future__ import annotations

import copy
import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path

import torch
from torch import nn

from jayrun import (Artifact, ArtifactContext, ArtifactField, ArtifactFlow, BaseOperator,
                    ConfigContext, ConfigField, Data, Engine, GraphDefinition)
from jayrun.context import ContextState
from jayrun.placement import Backend, Device
from jayrun.settings import ArtifactPolicy, ContextSettings, EngineSettings, RuntimeDevice

DATA = Path(__file__).with_name("data")


@dataclass(frozen=True, slots=True)
class TokenDataset:
    train: torch.Tensor
    validation: torch.Tensor
    fingerprint: str


def dataset_from_tokens(train: torch.Tensor, validation: torch.Tensor) -> TokenDataset:
    if train.ndim != 2 or validation.ndim != 2 or train.shape[1] < 2 or validation.shape[1] < 2:
        raise ValueError("token batches must be nonempty 2D sequences of at least two tokens")
    if not len(train) or not len(validation):
        raise ValueError("both dataset splits must be nonempty")
    train, validation = train.cpu().long().contiguous(), validation.cpu().long().contiguous()
    digest = hashlib.sha256()
    for value in (train, validation):
        digest.update(str(tuple(value.shape)).encode()+b"\0"+value.numpy().tobytes())
    return TokenDataset(train, validation, digest.hexdigest())


def load_fixture(sequence_length: int = 32) -> TokenDataset:
    def tokenize(name: str) -> torch.Tensor:
        content = (DATA/name).read_text().encode("utf-8")
        tokens = torch.tensor(list(content), dtype=torch.long)
        count = len(tokens)//sequence_length
        return tokens[:count*sequence_length].reshape(count, sequence_length)
    return dataset_from_tokens(tokenize("support_train.txt"), tokenize("support_validation.txt"))


class TinyLanguageModel(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.embedding = nn.Embedding(256, 24)
        self.recurrent = nn.GRU(24, 32, batch_first=True)
        self.head = nn.Linear(32, 256)

    def forward(self, tokens: torch.Tensor) -> torch.Tensor:
        values, _ = self.recurrent(self.embedding(tokens))
        return self.head(values)


class LowRankHead(nn.Module):
    def __init__(self, base: nn.Linear, rank: int = 4) -> None:
        super().__init__()
        self.base = base.requires_grad_(False)
        self.down = nn.Linear(base.in_features, rank, bias=False)
        self.up = nn.Linear(rank, base.out_features, bias=False)
        nn.init.zeros_(self.up.weight)

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        return self.base(values) + self.up(self.down(values))


@dataclass(slots=True)
class TrainingState:
    model: nn.Module
    optimizer: torch.optim.AdamW
    scheduler: torch.optim.lr_scheduler.StepLR
    generator: torch.Generator
    identity: dict[str, str | int]
    step: int = 0
    examples_seen: int = 0


def make_state(model: nn.Module, *, seed: int, identity: dict[str, str | int]) -> TrainingState:
    parameters = [p for p in model.parameters() if p.requires_grad]
    if not parameters:
        raise ValueError("model has no trainable adapter parameters")
    optimizer = torch.optim.AdamW(parameters, lr=.01, weight_decay=.01)
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=10, gamma=.9)
    return TrainingState(model, optimizer, scheduler,
                         torch.Generator().manual_seed(seed), dict(identity))


def loss_on(model: nn.Module, sequences: torch.Tensor) -> torch.Tensor:
    output = model(sequences[:, :-1])
    logits = output if isinstance(output, torch.Tensor) else output.logits
    return nn.functional.cross_entropy(logits.reshape(-1, logits.shape[-1]),
                                        sequences[:, 1:].reshape(-1))


def new_fixture_state(seed: int = 7) -> TrainingState:
    data = load_fixture()
    # Small base preparation happens before Jayrun scheduling; it is not a pretrained LLM.
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = TinyLanguageModel()
        optimizer = torch.optim.AdamW(model.parameters(), lr=.01)
        for _ in range(8):
            optimizer.zero_grad(set_to_none=True)
            loss = loss_on(model, data.train[:4]); loss.backward(); optimizer.step()
        model.requires_grad_(False)
        model.head = LowRankHead(model.head)
    return make_state(model, seed=seed, identity={"kind": "offline GRU fixture", "seed": seed, "rank": 4})


def train_updates(state: TrainingState, dataset: TokenDataset, updates: int,
                  batch_size: int = 4) -> float:
    if updates < 1 or batch_size < 1:
        raise ValueError("updates and batch_size must be positive")
    device = next(state.model.parameters()).device
    state.model.train()
    total = 0.0
    for _ in range(updates):
        indices = torch.randint(len(dataset.train), (batch_size,), generator=state.generator)
        sequences = dataset.train[indices].to(device)
        state.optimizer.zero_grad(set_to_none=True)
        loss = loss_on(state.model, sequences)
        if not torch.isfinite(loss):
            raise ValueError("non-finite loss; restore a checkpoint before retrying")
        loss.backward()
        nn.utils.clip_grad_norm_([p for p in state.model.parameters() if p.requires_grad],
                                 1.0, error_if_nonfinite=True)
        state.optimizer.step(); state.scheduler.step()
        state.step += 1; state.examples_seen += len(indices)
        total += float(loss.detach().cpu())
    return total/updates


def validation_loss(state: TrainingState, dataset: TokenDataset) -> float:
    state.model.eval()
    device = next(state.model.parameters()).device
    with torch.inference_mode():
        return float(loss_on(state.model, dataset.validation.to(device)).cpu())


def move_state(state: TrainingState, device: torch.device) -> None:
    """Rebind the optimizer after initial placement; keep its already-trained state."""
    optimizer_state, scheduler_state = state.optimizer.state_dict(), state.scheduler.state_dict()
    state.model.to(device)
    state.optimizer = torch.optim.AdamW([p for p in state.model.parameters() if p.requires_grad], lr=.01)
    state.optimizer.load_state_dict(optimizer_state)
    state.scheduler = torch.optim.lr_scheduler.StepLR(state.optimizer, step_size=10, gamma=.9)
    state.scheduler.load_state_dict(scheduler_state)


class TrainBlock(BaseOperator):
    requirements = ("torch",)

    def __init__(self, *, state: Artifact, dataset: Artifact,
                 outputs: tuple[Artifact, ...]) -> None:
        super().__init__()
        self.state, self.dataset = ArtifactField(required=True), ArtifactField(required=True)
        self.total_updates = ConfigField(value_type=int, required=True)
        self.device_kind = ConfigField(value_type=str, required=False, default="cpu")
        self.reservation_gb = ConfigField(value_type=float, required=False, default=1.0)
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> Data:
        state: TrainingState = self.state.value
        dataset: TokenDataset = self.dataset.value
        placement = self.state.placement
        if self.device_kind.value == "cuda" and placement.device is Device.CPU:
            placement = self.placement.cuda(memory_gb=self.reservation_gb.value)
            move_state(state, torch.device("cuda", placement.device_id))
        count = min(3, self.total_updates.value-state.step)
        if count > 0:
            train_updates(state, dataset, count)
        self.context.record("training", {"updates": state.step,
                                         "validation_loss": validation_loss(state, dataset),
                                         "examples_seen": state.examples_seen})
        if state.step >= self.total_updates.value:
            self.context.stop()
        return Data(value=state, placement=placement)


def build_graph():
    state, dataset = Artifact(name="training_state"), Artifact(name="tokens")
    train = TrainBlock(state=state, dataset=dataset, outputs=(state,))
    state_flow, data_flow = ArtifactFlow(train, artifact=state), ArtifactFlow(train, artifact=dataset)
    graph_1 = GraphDefinition(state_flow, data_flow, entry_flows=(state_flow, data_flow))
    graph_1.confirm()
    return graph_1, state, dataset, train


def run_training(state: TrainingState, dataset: TokenDataset, *, total_updates: int,
                 device: str = "cpu", reservation_gb: float = 1.0) -> TrainingState:
    if total_updates < state.step or total_updates < 1 or device not in {"cpu", "cuda"}:
        raise ValueError("invalid update target or device")
    settings = EngineSettings(max_workers=1, max_tasks=2)
    if device == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but is unavailable")
        free, _ = torch.cuda.mem_get_info(0)
        capacity = free/1e9*.8
        if reservation_gb > capacity or reservation_gb <= 0:
            raise ValueError("requested reservation exceeds this tutorial's 80% free-memory budget")
        settings = EngineSettings(max_workers=1, max_tasks=2, runtime_devices=(
            RuntimeDevice(device=Device.GPU, backends=(Backend.CUDA,),
                          device_id=0, memory_limit_gb=capacity),))
    graph, artifact, tokens, train = build_graph()
    inputs, configs = ArtifactContext(), ConfigContext()
    inputs.set({artifact: state, tokens: dataset})
    configs.set({train.total_updates: total_updates, train.device_kind: device,
                 train.reservation_gb: reservation_gb})
    with Engine(settings) as engine:
        run = engine.submit(graph, inputs, configs, settings=ContextSettings(
            max_iterations=None, record_history_limit=4,
            artifact_policy=ArtifactPolicy(release_entry_artifacts=True)))
        run.wait(timeout=600)
        if run.state is not ContextState.FINISHED:
            raise RuntimeError(str(run.report.data.failure))
        return run.artifact(artifact).value


def save_checkpoint(state: TrainingState, dataset: TokenDataset, path: Path) -> None:
    """Application checkpoint; not a Jayrun serialization format or database record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = {"format": 1, "identity": state.identity, "dataset": dataset.fingerprint,
                  "model": state.model.state_dict(), "optimizer": state.optimizer.state_dict(),
                  "scheduler": state.scheduler.state_dict(), "generator": state.generator.get_state(),
                  "step": state.step, "examples_seen": state.examples_seen}
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            torch.save(checkpoint, stream)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def restore_checkpoint(state: TrainingState, dataset: TokenDataset, path: Path) -> TrainingState:
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if checkpoint["format"] != 1 or checkpoint["identity"] != state.identity:
        raise ValueError("checkpoint model identity does not match")
    if checkpoint["dataset"] != dataset.fingerprint:
        raise ValueError("checkpoint dataset fingerprint does not match")
    move_state(state, torch.device("cpu"))
    state.model.load_state_dict(checkpoint["model"])
    state.optimizer.load_state_dict(checkpoint["optimizer"])
    state.scheduler.load_state_dict(checkpoint["scheduler"])
    state.generator.set_state(checkpoint["generator"])
    state.step, state.examples_seen = checkpoint["step"], checkpoint["examples_seen"]
    return state


def run_demo(*, output_directory: Path | None = None) -> dict[str, object]:
    dataset, initial = load_fixture(), new_fixture_state()
    before = validation_loss(initial, dataset)
    def fresh() -> TrainingState:
        return make_state(copy.deepcopy(initial.model), seed=7, identity=initial.identity)
    direct = fresh()
    train_updates(direct, dataset, 12)
    uninterrupted = run_training(fresh(), dataset, total_updates=12)
    partial = run_training(fresh(), dataset, total_updates=6)
    with tempfile.TemporaryDirectory(prefix="jayrun-adapter-") as temporary:
        folder = output_directory or Path(temporary)
        folder.mkdir(parents=True, exist_ok=True)
        checkpoint = folder/"training_checkpoint.pt"
        save_checkpoint(partial, dataset, checkpoint)
        resumed = restore_checkpoint(fresh(), dataset, checkpoint)
        resumed = run_training(resumed, dataset, total_updates=12)
        for name, value in uninterrupted.model.state_dict().items():
            torch.testing.assert_close(value, resumed.model.state_dict()[name], rtol=0, atol=0)
            torch.testing.assert_close(value, direct.model.state_dict()[name], rtol=0, atol=0)
        adapter = {name: value.detach().cpu().clone() for name, value in resumed.model.named_parameters()
                   if value.requires_grad}
        for name, value in initial.model.named_parameters():
            if not value.requires_grad:
                torch.testing.assert_close(value, resumed.model.state_dict()[name], rtol=0, atol=0)
        torch.save({"identity": resumed.identity, "adapter": adapter,
                    "dataset": dataset.fingerprint}, folder/"adapter.pt")
        result = {"model": initial.identity, "dataset_sha256": dataset.fingerprint,
                  "updates": resumed.step, "examples_seen": resumed.examples_seen,
                  "validation_loss_before": before, "validation_loss_after": validation_loss(resumed, dataset),
                  "checkpoint_matches_uninterrupted": True, "matches_direct_baseline": True,
                  "frozen_parameters_unchanged": True, "trainable_parameters": sum(v.numel() for v in adapter.values())}
        import json
        (folder/"result.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("adapter_results"))
    args = parser.parse_args()
    torch.set_num_threads(1)
    print(json.dumps(run_demo(output_directory=args.output), indent=2))
