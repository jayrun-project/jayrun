"""Real MNIST loader and an explicitly labelled offline lifecycle fixture."""
from __future__ import annotations

import gzip
import os
import struct
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch import nn

from jayrun.placement import Backend, Device
from jayrun.settings import EngineSettings, RuntimeDevice


@dataclass(frozen=True, slots=True)
class Dataset:
    training_images: torch.Tensor
    training_labels: torch.Tensor
    validation_images: torch.Tensor
    validation_labels: torch.Tensor
    source: str


class Classifier(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.linear = nn.Linear(784, 10)

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        return self.linear(images.flatten(1))


def load_data(*, real_mnist: bool = False, training_samples: int = 1024,
              validation_samples: int = 256, cache: Path | None = None) -> Dataset:
    if not 10 <= training_samples <= 60_000 or not 10 <= validation_samples <= 10_000:
        raise ValueError("sample counts must be within the MNIST split sizes and at least 10")
    if not real_mnist:
        generator = torch.Generator().manual_seed(41)
        prototypes = torch.eye(10).repeat(1, 79)[:, :784]
        def split(size: int) -> tuple[torch.Tensor, torch.Tensor]:
            labels = torch.arange(size) % 10
            images = prototypes[labels] + torch.rand((size, 784), generator=generator) * .05
            return images.reshape(size, 28, 28), labels
        train, labels = split(training_samples)
        valid, targets = split(validation_samples)
        return Dataset(train, labels, valid, targets, "synthetic lifecycle fixture; not MNIST")

    folder = cache or Path(os.environ.get("MNIST_DIR", Path.home()/".cache/jayrun/mnist"))
    folder.mkdir(parents=True, exist_ok=True)
    names = ("train-images-idx3-ubyte.gz", "train-labels-idx1-ubyte.gz",
             "t10k-images-idx3-ubyte.gz", "t10k-labels-idx1-ubyte.gz")
    arrays = []
    for name in names:
        path = folder/name
        if not path.is_file():
            with tempfile.NamedTemporaryFile(dir=folder, delete=False) as stream:
                temporary = Path(stream.name)
            try:
                url = "https://storage.googleapis.com/cvdf-datasets/mnist/" + name
                with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as out:
                    while block := response.read(1024*1024):
                        out.write(block)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        with gzip.open(path, "rb") as stream:
            magic = struct.unpack(">I", stream.read(4))[0]
            dimensions = magic & 255
            if magic >> 8 != 8 or dimensions not in (1, 3):
                raise ValueError(f"invalid MNIST IDX header: {path}")
            shape = struct.unpack(">" + "I"*dimensions, stream.read(4*dimensions))
            arrays.append(np.frombuffer(stream.read(), dtype=np.uint8).reshape(shape).copy())
    return Dataset(torch.from_numpy(arrays[0][:training_samples]).float()/255,
                   torch.from_numpy(arrays[1][:training_samples]).long(),
                   torch.from_numpy(arrays[2][:validation_samples]).float()/255,
                   torch.from_numpy(arrays[3][:validation_samples]).long(), "MNIST")


def engine_settings(device: str = "cpu") -> EngineSettings:
    if device not in {"cpu", "cuda"}:
        raise ValueError("device must be cpu or cuda")
    if device == "cpu":
        return EngineSettings(max_workers=2, max_tasks=4)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable; no silent CPU fallback")
    free, _ = torch.cuda.mem_get_info(0)
    if free < 600_000_000:
        raise RuntimeError("this tutorial requires at least 0.6 GB free on CUDA device 0")
    return EngineSettings(max_workers=2, max_tasks=4,
        runtime_devices=(RuntimeDevice(device=Device.GPU, backends=(Backend.CUDA,),
                                       device_id=0, memory_limit_gb=0.5),))
