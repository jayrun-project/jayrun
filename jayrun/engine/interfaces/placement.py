from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..resource.placement import Backend, Device, Placement, PlacementGroup
from ..resource.placement_request import (
    PlacementImpossible,
    PlacementRequest,
    PlacementState,
    PlacementUnavailable,
    requested_bytes,
)

if TYPE_CHECKING:
    from ..recorders.execution.recorder import ExecutionRecorder
    from ..resource.resource_manager import ResourceManager


@dataclass(slots=True, eq=False)
class _PlacementCall:
    request: PlacementRequest
    state: PlacementState
    placements: PlacementGroup | None


class PlacementInterface:
    """Reserve accelerator capacity from inside an operator or resource.

    Make placement calls before side effects: if capacity is temporarily unavailable,
    Jayrun may restart the invocation from the beginning after reconciliation.
    """

    def __init__(
        self,
        resource_manager: ResourceManager,
        recorder: ExecutionRecorder,
    ) -> None:
        self._recorder = recorder
        self._reserve_placement = resource_manager.reserve_placement
        self._calls: list[_PlacementCall] = []
        self._request_cursor = 0
        self._pending_request: PlacementRequest | None = None

    def reserve(
        self,
        *,
        device: Device,
        backend: Backend,
        memory_gb: int | float,
        exclusive: bool = False,
        device_id: int | None = None,
    ) -> Placement:
        """Reserve capacity on one accelerator device.

        Args:
            device: Requested device family.
            backend: Required accelerator backend.
            memory_gb: Memory to reserve in decimal gigabytes.
            exclusive: Require exclusive use of the device.
            device_id: Optional exact device index.
        """
        placements = self._reserve(
            device=device,
            backend=backend,
            group_memory_gb=memory_gb,
            per_device_memory_gb=0,
            min_devices=1,
            max_devices=1,
            prefer_max_devices=False,
            exclusive=exclusive,
            device_id=device_id,
        )
        if len(placements) != 1:
            raise RuntimeError(
                "single-device request returned an invalid placement count"
            )
        return placements.primary

    def reserve_group(
        self,
        *,
        device: Device,
        backend: Backend,
        group_memory_gb: int | float = 0,
        per_device_memory_gb: int | float = 0,
        max_devices: int,
        min_devices: int = 1,
        prefer_max_devices: bool = False,
        exclusive: bool = False,
    ) -> PlacementGroup:
        """Reserve a homogeneous group of accelerator devices.

        ``group_memory_gb`` may be distributed across the group, while
        ``per_device_memory_gb`` is required on every selected device.
        """
        return self._reserve(
            device=device,
            backend=backend,
            group_memory_gb=group_memory_gb,
            per_device_memory_gb=per_device_memory_gb,
            min_devices=min_devices,
            max_devices=max_devices,
            prefer_max_devices=prefer_max_devices,
            exclusive=exclusive,
            device_id=None,
        )

    def cuda(
        self,
        memory_gb: int | float,
        *,
        exclusive: bool = False,
        device_id: int | None = None,
    ) -> Placement:
        """Reserve one CUDA GPU; shorthand for :meth:`reserve`."""
        return self.reserve(
            device=Device.GPU,
            backend=Backend.CUDA,
            memory_gb=memory_gb,
            exclusive=exclusive,
            device_id=device_id,
        )

    def cuda_group(
        self,
        *,
        group_memory_gb: int | float = 0,
        per_device_memory_gb: int | float = 0,
        max_devices: int,
        min_devices: int = 1,
        prefer_max_devices: bool = False,
        exclusive: bool = False,
    ) -> PlacementGroup:
        """Reserve a CUDA GPU group; shorthand for :meth:`reserve_group`."""
        return self.reserve_group(
            device=Device.GPU,
            backend=Backend.CUDA,
            group_memory_gb=group_memory_gb,
            per_device_memory_gb=per_device_memory_gb,
            min_devices=min_devices,
            max_devices=max_devices,
            prefer_max_devices=prefer_max_devices,
            exclusive=exclusive,
        )

    def _reserve(
        self,
        *,
        device: Device,
        backend: Backend,
        group_memory_gb: int | float,
        per_device_memory_gb: int | float,
        min_devices: int,
        max_devices: int,
        prefer_max_devices: bool,
        exclusive: bool,
        device_id: int | None,
    ) -> PlacementGroup:
        request = PlacementRequest(
            context_id=self._recorder.context_id,
            step_reference=self._recorder.step_reference,
            iteration=self._recorder.iteration,
            execution=self._recorder.execution,
            request_index=self._request_cursor,
            device=device,
            backend=backend,
            group_memory_bytes=requested_bytes(
                group_memory_gb,
                allow_zero=True,
            ),
            per_device_memory_bytes=requested_bytes(
                per_device_memory_gb,
                allow_zero=True,
            ),
            min_devices=min_devices,
            max_devices=max_devices,
            prefer_max_devices=prefer_max_devices,
            exclusive=exclusive,
            device_id=device_id,
        )
        call = self._resolve_call(request)
        return self._resolve_result(call)

    def _resolve_call(self, request: PlacementRequest) -> _PlacementCall:
        request_index = self._request_cursor
        self._request_cursor += 1
        if request_index == len(self._calls):
            state, placements = self._reserve_placement(request)
            call = _PlacementCall(
                request=request,
                state=state,
                placements=placements,
            )
            self._calls.append(call)
            return call
        if request_index > len(self._calls):
            raise RuntimeError("placement request cursor is inconsistent")
        call = self._calls[request_index]
        if call.request != request:
            raise RuntimeError("placement request changed between execution attempts")
        if call.request is self._pending_request:
            state, placements = self._reserve_placement(call.request)
            call.state = state
            call.placements = placements
            if state is not PlacementState.UNAVAILABLE:
                self._pending_request = None
        return call

    def _resolve_result(
        self,
        call: _PlacementCall,
    ) -> PlacementGroup:
        match call.state:
            case PlacementState.SUCCESS:
                if not call.placements:
                    raise RuntimeError(
                        "successful placement request returned no placements"
                    )
                return call.placements
            case PlacementState.UNAVAILABLE:
                if call.placements is not None:
                    raise RuntimeError(
                        "unavailable placement request returned placements"
                    )
                raise PlacementUnavailable(call.request)
            case PlacementState.IMPOSSIBLE:
                if call.placements is not None:
                    raise RuntimeError(
                        "impossible placement request returned placements"
                    )
                raise PlacementImpossible(call.request)
            case _:
                raise RuntimeError(f"unsupported placement state: {call.state!r}")

    def _restart(self, pending_request: PlacementRequest) -> None:
        if not any(call.request is pending_request for call in self._calls):
            raise ValueError(
                "pending request does not belong to this placement interface"
            )
        self._request_cursor = 0
        self._pending_request = pending_request

    def _clear(self) -> None:
        self._calls.clear()
        self._request_cursor = 0
        self._pending_request = None

    @property
    def placement_requests(self) -> tuple[PlacementRequest, ...]:
        return tuple(call.request for call in self._calls)
