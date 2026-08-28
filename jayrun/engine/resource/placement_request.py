from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import Enum

from ..context.step_reference import StepReference
from .placement import Backend, Device

_BYTES_PER_GB = Decimal(1_000_000_000)


class PlacementState(Enum):
    SUCCESS = "success"
    UNAVAILABLE = "unavailable"
    IMPOSSIBLE = "impossible"


def capacity_bytes(memory_gb: int | float) -> int:
    return _memory_bytes(memory_gb, ROUND_FLOOR)


def requested_bytes(
    memory_gb: int | float,
    *,
    allow_zero: bool = False,
) -> int:
    if not isinstance(allow_zero, bool):
        raise TypeError("allow_zero must be a bool")
    if allow_zero and memory_gb == 0 and not isinstance(memory_gb, bool):
        return 0
    return _memory_bytes(memory_gb, ROUND_CEILING)


def _memory_bytes(
    memory_gb: int | float,
    rounding: str,
) -> int:
    if isinstance(memory_gb, bool) or not isinstance(memory_gb, (int, float)):
        raise TypeError("memory_gb must be an int or float")
    memory = Decimal(str(memory_gb))
    if not memory.is_finite():
        raise ValueError("memory_gb must be finite")
    if memory <= 0:
        raise ValueError("memory_gb must be greater than zero")
    value = memory * _BYTES_PER_GB
    memory_bytes = int(value.to_integral_value(rounding=rounding))
    if memory_bytes < 1:
        raise ValueError("memory_gb must represent at least one byte")
    return memory_bytes


@dataclass(frozen=True, slots=True, eq=True)
class PlacementRequest:
    context_id: int
    step_reference: StepReference
    iteration: int
    execution: int
    request_index: int
    device: Device
    backend: Backend
    group_memory_bytes: int
    per_device_memory_bytes: int
    max_devices: int = 1
    exclusive: bool = False
    device_id: int | None = None
    min_devices: int = 1
    prefer_max_devices: bool = False

    @property
    def is_resource(self) -> bool:
        return self.step_reference.step_kind == "resource"

    def __post_init__(self) -> None:
        if isinstance(self.context_id, bool) or not isinstance(self.context_id, int):
            raise TypeError("context_id must be an int")
        if self.context_id < 0:
            raise ValueError("context_id must be non-negative")
        if not isinstance(self.step_reference, StepReference):
            raise TypeError("step_reference must be a StepReference instance")
        if isinstance(self.iteration, bool) or not isinstance(self.iteration, int):
            raise TypeError("iteration must be an int")
        if self.iteration < 0:
            raise ValueError("iteration must be non-negative")
        if isinstance(self.execution, bool) or not isinstance(self.execution, int):
            raise TypeError("execution must be an int")
        if self.execution < 1:
            raise ValueError("execution must be greater than zero")
        if isinstance(self.request_index, bool) or not isinstance(
            self.request_index,
            int,
        ):
            raise TypeError("request_index must be an int")
        if self.request_index < 0:
            raise ValueError("request_index must be non-negative")
        if not isinstance(self.device, Device):
            raise TypeError("device must be a Device instance")
        if self.device is Device.CPU:
            raise ValueError("CPU placement does not require a reservation")
        if not isinstance(self.backend, Backend):
            raise TypeError("backend must be a Backend instance")
        self._validate_memory(self.group_memory_bytes, "group_memory_bytes")
        self._validate_memory(
            self.per_device_memory_bytes,
            "per_device_memory_bytes",
        )
        if isinstance(self.max_devices, bool) or not isinstance(
            self.max_devices,
            int,
        ):
            raise TypeError("max_devices must be an int")
        if self.max_devices < 1:
            raise ValueError("max_devices must be greater than zero")
        if isinstance(self.min_devices, bool) or not isinstance(
            self.min_devices,
            int,
        ):
            raise TypeError("min_devices must be an int")
        if self.min_devices < 1:
            raise ValueError("min_devices must be greater than zero")
        if self.min_devices > self.max_devices:
            raise ValueError("min_devices cannot exceed max_devices")
        if not isinstance(self.exclusive, bool):
            raise TypeError("exclusive must be a bool")
        if not isinstance(self.prefer_max_devices, bool):
            raise TypeError("prefer_max_devices must be a bool")
        if (
            self.group_memory_bytes == 0
            and self.per_device_memory_bytes == 0
            and not self.exclusive
        ):
            raise ValueError(
                "a non-exclusive placement request must reserve memory"
            )
        if isinstance(self.device_id, bool) or (
            self.device_id is not None and not isinstance(self.device_id, int)
        ):
            raise TypeError("device_id must be an int or None")
        if self.device_id is not None and self.device_id < 0:
            raise ValueError("device_id must be non-negative")
        if self.device_id is not None and (
            self.min_devices != 1 or self.max_devices != 1
        ):
            raise ValueError(
                "device_id requires min_devices and max_devices to be one"
            )

    @staticmethod
    def _validate_memory(value: int, name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an int")
        if value < 0:
            raise ValueError(f"{name} must be non-negative")

    def device_counts(self) -> tuple[int, ...]:
        counts = tuple(range(self.min_devices, self.max_devices + 1))
        return tuple(reversed(counts)) if self.prefer_max_devices else counts

    def allocation_bytes(self, device_count: int) -> tuple[int, ...]:
        if isinstance(device_count, bool) or not isinstance(device_count, int):
            raise TypeError("device_count must be an int")
        if not self.min_devices <= device_count <= self.max_devices:
            raise ValueError("device_count is outside the requested range")
        shared, remainder = divmod(self.group_memory_bytes, device_count)
        return tuple(
            self.per_device_memory_bytes
            + shared
            + (1 if index < remainder else 0)
            for index in range(device_count)
        )

@dataclass(frozen=True, slots=True)
class PlacementReconciliation:
    ready: tuple[PlacementRequest, ...] = ()
    revoked: tuple[PlacementRequest, ...] = ()


class PlacementError(Exception):
    pass


class PlacementUnavailable(PlacementError):
    def __init__(self, request: PlacementRequest) -> None:
        super().__init__("Placement is currently unavailable")
        self._request = request

    @property
    def request(self) -> PlacementRequest:
        return self._request


class PlacementImpossible(PlacementError):
    def __init__(self, request: PlacementRequest) -> None:
        super().__init__("Placement request cannot be satisfied")
        self._request = request

    @property
    def request(self) -> PlacementRequest:
        return self._request
