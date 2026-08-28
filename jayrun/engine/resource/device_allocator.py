from __future__ import annotations

from typing import TYPE_CHECKING

from .placement_request import PlacementRequest, capacity_bytes

if TYPE_CHECKING:
    from ..settings.engine import RuntimeDevice


class DeviceAllocator:
    def __init__(self, runtime_device: RuntimeDevice) -> None:
        if runtime_device.memory_limit_gb is None:
            raise ValueError("managed device requires declared memory capacity")
        if runtime_device.device_id is None:
            raise ValueError("managed device requires a device ID")
        self._runtime_device = runtime_device
        self._capacity_bytes = capacity_bytes(runtime_device.memory_limit_gb)
        self._reserved_bytes = 0
        self._exclusive_reservation = False

    def supports(self, request: PlacementRequest) -> bool:
        self._validate_request(request)
        if request.device is not self._runtime_device.device:
            return False
        if request.backend not in self._runtime_device.backends:
            return False
        return request.device_id in {None, self.device_id}

    def can_satisfy(
        self,
        request: PlacementRequest,
        memory_bytes: int,
    ) -> bool:
        self._validate_request(request)
        self._validate_memory(memory_bytes)
        return self.supports(request) and memory_bytes <= self._capacity_bytes

    def requires_exclusive(self, request: PlacementRequest) -> bool:
        self._validate_request(request)
        return self._runtime_device.exclusive_only or request.exclusive

    def can_reserve(
        self,
        request: PlacementRequest,
        memory_bytes: int,
    ) -> bool:
        self._validate_request(request)
        self._validate_memory(memory_bytes)
        if not self.can_satisfy(request, memory_bytes):
            return False
        if self._exclusive_reservation:
            return False
        if self.requires_exclusive(request):
            return not self.occupied
        return memory_bytes <= self.available_bytes

    def reserve(
        self,
        request: PlacementRequest,
        memory_bytes: int,
    ) -> bool:
        self._validate_request(request)
        self._validate_memory(memory_bytes)
        if not self.can_reserve(request, memory_bytes):
            return False
        self._reserved_bytes += memory_bytes
        self._exclusive_reservation = self.requires_exclusive(request)
        return True

    def release(self, memory_bytes: int, *, exclusive: bool) -> None:
        if isinstance(memory_bytes, bool) or not isinstance(memory_bytes, int):
            raise TypeError("memory_bytes must be an int")
        if memory_bytes < 0:
            raise ValueError("memory_bytes must be non-negative")
        if not isinstance(exclusive, bool):
            raise TypeError("exclusive must be a bool")
        if memory_bytes > self._reserved_bytes:
            raise RuntimeError("released capacity exceeds reserved capacity")
        if exclusive is not self._exclusive_reservation:
            raise RuntimeError("released reservation mode is inconsistent")
        self._reserved_bytes -= memory_bytes
        if exclusive:
            if self._reserved_bytes != 0:
                raise RuntimeError("exclusive reservation capacity is inconsistent")
            self._exclusive_reservation = False

    def reset(self) -> None:
        self._reserved_bytes = 0
        self._exclusive_reservation = False

    @staticmethod
    def _validate_request(request: PlacementRequest) -> None:
        if not isinstance(request, PlacementRequest):
            raise TypeError("request must be a PlacementRequest instance")

    @staticmethod
    def _validate_memory(memory_bytes: int) -> None:
        if isinstance(memory_bytes, bool) or not isinstance(memory_bytes, int):
            raise TypeError("memory_bytes must be an int")
        if memory_bytes < 0:
            raise ValueError("memory_bytes must be non-negative")

    @property
    def occupied(self) -> bool:
        return self._reserved_bytes > 0 or self._exclusive_reservation

    @property
    def available_bytes(self) -> int:
        if self._exclusive_reservation:
            return 0
        return self._capacity_bytes - self._reserved_bytes

    @property
    def capacity_bytes(self) -> int:
        return self._capacity_bytes

    @property
    def reserved_bytes(self) -> int:
        return self._reserved_bytes

    @property
    def exclusively_reserved(self) -> bool:
        return self._exclusive_reservation

    @property
    def device_id(self) -> int:
        device_id = self._runtime_device.device_id
        if device_id is None:
            raise RuntimeError("managed device has no device ID")
        return device_id
