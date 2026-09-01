from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from typing import TypeAlias

from ..resource.placement import Backend, Device


ExceptionType: TypeAlias = type[Exception]


class RuntimeMode(Enum):
    """Select production or diagnostic recording behavior."""

    PRODUCTION = "production"
    DEBUG = "debug"


class FailureMode(Enum):
    """Control whether an engine continues after a context failure."""

    FAIL_FAST = "fail_fast"
    CONTINUE = "continue"


@dataclass(frozen=True, slots=True)
class RuntimeDevice:
    """Describe one device whose capacity Jayrun may reserve.

    CPU is always available and does not accept accelerator attributes. Managed
    accelerators require a backend, device ID, and memory capacity.

    Args:
        device: Device family.
        backends: Supported accelerator backends.
        device_id: Runtime-visible accelerator index.
        memory_limit_gb: Reservable device memory in decimal gigabytes.
        exclusive_only: Require every reservation on this device to be exclusive.
    """

    device: Device = Device.CPU
    backends: tuple[Backend, ...] = ()
    device_id: int | None = None
    memory_limit_gb: int | float | None = None
    exclusive_only: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.device, Device):
            raise TypeError("device must be a Device instance")
        if not isinstance(self.backends, tuple):
            raise TypeError("backends must be a tuple")
        if any(not isinstance(backend, Backend) for backend in self.backends):
            raise TypeError("backends must contain only Backend instances")
        if len(set(self.backends)) != len(self.backends):
            raise ValueError("backends cannot contain duplicates")
        if isinstance(self.device_id, bool) or (
            self.device_id is not None and not isinstance(self.device_id, int)
        ):
            raise TypeError("device_id must be an int or None")
        if self.device_id is not None and self.device_id < 0:
            raise ValueError("device_id must be non-negative")
        if self.memory_limit_gb is not None:
            if isinstance(self.memory_limit_gb, bool) or not isinstance(
                self.memory_limit_gb,
                (int, float),
            ):
                raise TypeError("memory_limit_gb must be an int or float")
            if self.memory_limit_gb <= 0:
                raise ValueError("memory_limit_gb must be greater than zero")
            if isinstance(self.memory_limit_gb, float) and not isfinite(
                self.memory_limit_gb
            ):
                raise ValueError("memory_limit_gb must be finite")
        if not isinstance(self.exclusive_only, bool):
            raise TypeError("exclusive_only must be a bool")
        if self.device is Device.CPU:
            if self.backends:
                raise ValueError("CPU device cannot declare accelerator backends")
            if self.device_id is not None:
                raise ValueError("CPU device cannot have a device ID")
            if self.exclusive_only:
                raise ValueError("CPU device cannot require exclusive reservations")
            return
        if not self.backends:
            raise ValueError("managed accelerator requires at least one backend")
        if self.device_id is None:
            raise ValueError("managed accelerator requires a device ID")
        if self.memory_limit_gb is None:
            raise ValueError("managed accelerator requires memory capacity")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Define which execution failures are retried.

    Args:
        max_attempts: Total attempts including the initial execution.
        retry_on: Exception classes eligible for retry. When ``max_attempts`` is
            greater than one and this tuple is empty, all :class:`Exception`
            subclasses are retried.
    """

    max_attempts: int = 1
    retry_on: tuple[ExceptionType, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.max_attempts, bool) or not isinstance(
            self.max_attempts,
            int,
        ):
            raise TypeError("max_attempts must be an int")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be greater than zero")
        if not isinstance(self.retry_on, tuple):
            raise TypeError("retry_on must be a tuple of exception classes")
        retry_on = tuple(dict.fromkeys(self.retry_on))
        for exception_type in retry_on:
            if not isinstance(exception_type, type):
                raise TypeError("retry_on must contain exception classes")
            if not issubclass(exception_type, Exception):
                raise TypeError("retry_on must contain Exception subclasses")
        if self.max_attempts == 1 and retry_on:
            raise ValueError("retry_on cannot be specified when max_attempts is one")
        if self.max_attempts > 1 and not retry_on:
            retry_on = (Exception,)
        object.__setattr__(self, "retry_on", retry_on)


@dataclass(frozen=True, slots=True)
class EngineSettings:
    """Configure engine-wide execution, capacity, and reliability behavior.

    Args:
        runtime_mode: Production or diagnostic recording mode.
        failure_mode: Whether one failed context stops the runtime.
        retry_policy: Default retry policy for submitted contexts.
        max_workers: Maximum worker threads, or ``None`` for the runtime default.
        max_tasks: Maximum concurrently dispatched tasks, or ``None`` for the runtime
            default.
        runtime_devices: Managed device description or tuple of descriptions. A CPU
            device is added automatically when absent.
    """

    runtime_mode: RuntimeMode = RuntimeMode.PRODUCTION
    failure_mode: FailureMode = FailureMode.CONTINUE
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    max_workers: int | None = None
    max_tasks: int | None = None
    runtime_devices: RuntimeDevice | tuple[RuntimeDevice, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.runtime_mode, RuntimeMode):
            raise TypeError("runtime_mode must be a RuntimeMode instance")
        if not isinstance(self.failure_mode, FailureMode):
            raise TypeError("failure_mode must be a FailureMode instance")
        if not isinstance(self.retry_policy, RetryPolicy):
            raise TypeError("retry_policy must be a RetryPolicy instance")
        self._validate_positive_integer(self.max_workers, "max_workers")
        self._validate_positive_integer(self.max_tasks, "max_tasks")
        runtime_devices = self._normalize_devices(self.runtime_devices)
        self._validate_duplicate_devices(runtime_devices)
        if not any(device.device is Device.CPU for device in runtime_devices):
            runtime_devices = (*runtime_devices, RuntimeDevice())
        object.__setattr__(self, "runtime_devices", runtime_devices)

    @staticmethod
    def _validate_positive_integer(value: int | None, name: str) -> None:
        if isinstance(value, bool):
            raise TypeError(f"{name} must be an int or None")
        if value is None:
            return
        if not isinstance(value, int):
            raise TypeError(f"{name} must be an int or None")
        if value <= 0:
            raise ValueError(f"{name} must be greater than zero")

    @staticmethod
    def _normalize_devices(
        devices: RuntimeDevice | tuple[RuntimeDevice, ...],
    ) -> tuple[RuntimeDevice, ...]:
        if isinstance(devices, RuntimeDevice):
            return (devices,)
        if not isinstance(devices, tuple):
            raise TypeError("runtime_devices must be a RuntimeDevice or tuple")
        if any(not isinstance(device, RuntimeDevice) for device in devices):
            raise TypeError("runtime_devices must contain RuntimeDevice instances")
        return devices

    @staticmethod
    def _validate_duplicate_devices(
        devices: tuple[RuntimeDevice, ...],
    ) -> None:
        managed_devices: set[tuple[Device, int]] = set()
        cpu_count = 0
        for runtime_device in devices:
            if runtime_device.device is Device.CPU:
                cpu_count += 1
                if cpu_count > 1:
                    raise ValueError("runtime devices cannot contain duplicate CPU")
                continue
            device_id = runtime_device.device_id
            if device_id is None:
                raise ValueError("managed accelerator requires a device ID")
            key = (runtime_device.device, device_id)
            if key in managed_devices:
                raise ValueError("runtime devices cannot contain duplicates")
            managed_devices.add(key)
