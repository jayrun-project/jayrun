from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import TypeAlias, overload


class Device(Enum):
    """Device families understood by the placement scheduler."""

    CPU = "cpu"
    GPU = "gpu"
    TPU = "tpu"


class Backend(Enum):
    """Accelerator software backends understood by the placement scheduler."""

    CUDA = "cuda"
    MPS = "mps"
    OPENCL = "opencl"
    ROCM = "rocm"
    XLA = "xla"
    XPU = "xpu"


@dataclass(slots=True, weakref_slot=True, eq=False)
class _PlacementLease:
    pass


@dataclass(frozen=True, slots=True, weakref_slot=True, eq=False)
class Placement:
    """Location and capacity reservation for one device.

    CPU placements are unreserved and have no backend or device ID. Accelerator
    placements returned by the runtime carry an internal lease that keeps their
    capacity reserved while the placement remains live.

    Args:
        device: Device family.
        backend: Accelerator backend, or ``None`` for CPU.
        device_id: Runtime-visible accelerator index, or ``None`` for CPU.
        memory_bytes: Bytes reserved on the accelerator.
    """

    device: Device
    backend: Backend | None = None
    device_id: int | None = None
    memory_bytes: int = 0
    _lease: _PlacementLease | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.device, Device):
            raise TypeError("device must be a Device instance")
        if self.backend is not None and not isinstance(self.backend, Backend):
            raise TypeError("backend must be a Backend instance")
        if isinstance(self.device_id, bool) or (
            self.device_id is not None and not isinstance(self.device_id, int)
        ):
            raise TypeError("device_id must be an int or None")
        if self.device_id is not None and self.device_id < 0:
            raise ValueError("device_id must be non-negative")
        if isinstance(self.memory_bytes, bool) or not isinstance(
            self.memory_bytes,
            int,
        ):
            raise TypeError("memory_bytes must be an int")
        if self.memory_bytes < 0:
            raise ValueError("memory_bytes must be non-negative")
        if self._lease is not None and not isinstance(
            self._lease,
            _PlacementLease,
        ):
            raise TypeError("placement lease is invalid")
        if self.device is Device.CPU:
            if self.backend is not None or self.device_id is not None:
                raise ValueError("CPU placement cannot have a backend or device ID")
            if self.memory_bytes != 0 or self._lease is not None:
                raise ValueError("CPU placement cannot own reserved capacity")
            return
        if self.backend is None:
            raise ValueError("accelerator placement requires a backend")
        if self.device_id is None:
            raise ValueError("accelerator placement requires a device ID")

    @property
    def placements(self) -> tuple[Placement, ...]:
        """One-element tuple containing this placement."""
        return (self,)

    @property
    def primary(self) -> Placement:
        """This placement, for parity with :class:`PlacementGroup`."""
        return self

    @property
    def device_ids(self) -> tuple[int, ...]:
        """Reserved accelerator device ID, or an empty tuple for CPU."""
        if self.device_id is None:
            return ()
        return (self.device_id,)

    @property
    def reserved_memory_bytes(self) -> int:
        """Total bytes reserved by this placement."""
        return self.memory_bytes


@dataclass(frozen=True, slots=True, weakref_slot=True, eq=False)
class PlacementGroup(Sequence[Placement]):
    """Homogeneous reservation spanning multiple accelerator devices.

    Args:
        placements: Reserved placements in primary-first order.
        group_memory_bytes: Memory budget distributed across the group.
        per_device_memory_bytes: Additional bytes reserved on every device.
        prefer_max_devices: Whether allocation favored more devices over tighter
            packing.
    """

    placements: tuple[Placement, ...]
    group_memory_bytes: int = 0
    per_device_memory_bytes: int = 0
    prefer_max_devices: bool = False
    _lease: _PlacementLease | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.placements, tuple):
            raise TypeError("placements must be a tuple")
        if not self.placements:
            raise ValueError("placements cannot be empty")
        if any(not isinstance(value, Placement) for value in self.placements):
            raise TypeError("placements must contain Placement instances")
        if any(value.device is Device.CPU for value in self.placements):
            raise ValueError("placement groups cannot contain CPU placements")
        if len({value.device_id for value in self.placements}) != len(
            self.placements
        ):
            raise ValueError("placement groups cannot contain duplicate devices")
        primary = self.placements[0]
        if any(
            value.device is not primary.device or value.backend is not primary.backend
            for value in self.placements[1:]
        ):
            raise ValueError("placement groups must be homogeneous")
        self._validate_memory(self.group_memory_bytes, "group_memory_bytes")
        self._validate_memory(
            self.per_device_memory_bytes,
            "per_device_memory_bytes",
        )
        if not isinstance(self.prefer_max_devices, bool):
            raise TypeError("prefer_max_devices must be a bool")
        expected_memory = self.group_memory_bytes + (
            len(self.placements) * self.per_device_memory_bytes
        )
        if self.reserved_memory_bytes != expected_memory:
            raise ValueError("placement group memory allocation is inconsistent")
        if self._lease is None:
            if any(value._lease is not None for value in self.placements):
                raise ValueError("placement group lease is inconsistent")
        elif any(value._lease is not self._lease for value in self.placements):
            raise ValueError("placement group members must share one lease")

    @staticmethod
    def _validate_memory(value: int, name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an int")
        if value < 0:
            raise ValueError(f"{name} must be non-negative")

    def __len__(self) -> int:
        return len(self.placements)

    def __iter__(self) -> Iterator[Placement]:
        return iter(self.placements)

    @overload
    def __getitem__(self, index: int) -> Placement:
        ...

    @overload
    def __getitem__(self, index: slice) -> tuple[Placement, ...]:
        ...

    def __getitem__(self, index: int | slice) -> Placement | tuple[Placement, ...]:
        return self.placements[index]

    @property
    def primary(self) -> Placement:
        """First placement in the group."""
        return self.placements[0]

    @property
    def device(self) -> Device:
        """Shared device family."""
        return self.primary.device

    @property
    def backend(self) -> Backend:
        """Shared accelerator backend."""
        backend = self.primary.backend
        if backend is None:
            raise RuntimeError("accelerator placement has no backend")
        return backend

    @property
    def device_ids(self) -> tuple[int, ...]:
        """Reserved device IDs in placement order."""
        return tuple(
            placement.device_id
            for placement in self.placements
            if placement.device_id is not None
        )

    @property
    def reserved_memory_bytes(self) -> int:
        """Total bytes reserved across the group."""
        return sum(value.memory_bytes for value in self.placements)


#: A single-device placement or a homogeneous multi-device placement group.
PlacementLocation: TypeAlias = Placement | PlacementGroup


#: Canonical unreserved CPU placement.
CPU_PLACEMENT = Placement(device=Device.CPU)
