from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from queue import Empty, SimpleQueue
from threading import Lock
from weakref import ReferenceType, WeakMethod, finalize, ref

from ..settings.engine import RuntimeDevice
from .device_allocator import DeviceAllocator
from .placement import (
    Backend,
    Device,
    Placement,
    PlacementGroup,
    PlacementLocation,
    _PlacementLease,
)
from .placement_request import (
    PlacementReconciliation,
    PlacementRequest,
    PlacementState,
)


_SessionKey = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class _DeviceAllocation:
    allocator: DeviceAllocator
    memory_bytes: int
    exclusive: bool


@dataclass(slots=True)
class _PlacementRecord:
    lease_ref: ReferenceType[_PlacementLease]
    location_refs: dict[int, ReferenceType[PlacementLocation]]
    allocations: tuple[_DeviceAllocation, ...]
    owner: _SessionKey


@dataclass(frozen=True, slots=True)
class PlacementEvictionTarget:
    device_id: int
    exclusive: bool
    required_bytes: int
    reservations: tuple[tuple[int, int], ...]


class PlacementController:
    def __init__(
        self,
        runtime_devices: tuple[RuntimeDevice, ...],
        capacity_released: Callable[[], None] | None = None,
    ) -> None:
        self._lock = Lock()
        self._routes: dict[
            tuple[Device, Backend],
            tuple[DeviceAllocator, ...],
        ] = {}
        self._allocators: tuple[DeviceAllocator, ...] = ()
        self._placements: dict[int, _PlacementRecord] = {}
        self._placement_ids: dict[int, int] = {}
        self._reservation_ids = count()
        self._released_reservations: SimpleQueue[int] = SimpleQueue()
        self._capacity_released: ReferenceType[Callable[[], None]] | None = None
        if capacity_released is not None:
            self._capacity_released = (
                WeakMethod(capacity_released)
                if getattr(capacity_released, "__self__", None) is not None
                else ref(capacity_released)
            )
        self._grants: dict[PlacementRequest, PlacementGroup] = {}
        self._register_devices(runtime_devices)

    def reserve(
        self,
        request: PlacementRequest,
    ) -> tuple[PlacementState, PlacementGroup | None]:
        self._validate_request(request)
        with self._lock:
            grant = self._grants.pop(request, None)
            if grant is not None:
                return PlacementState.SUCCESS, grant
            self._collect_released()
            return self._reserve(request)

    def resolve(
        self,
        requests: tuple[PlacementRequest, ...],
    ) -> tuple[PlacementRequest, ...]:
        if not requests:
            return ()
        if any(not isinstance(request, PlacementRequest) for request in requests):
            raise TypeError("requests must contain PlacementRequest instances")
        with self._lock:
            self._collect_released()
            ready: list[PlacementRequest] = []
            for request in requests:
                if request in self._grants:
                    ready.append(request)
                    continue
                state, placement = self._reserve(request)
                if state is not PlacementState.SUCCESS:
                    continue
                if placement is None:
                    raise RuntimeError(
                        "successful placement reservation returned no placement"
                    )
                self._grants[request] = placement
                ready.append(request)
            return tuple(ready)

    def recover_stuck(
        self,
        requests: tuple[PlacementRequest, ...],
    ) -> PlacementReconciliation:
        if not requests:
            return PlacementReconciliation()
        if any(not isinstance(request, PlacementRequest) for request in requests):
            raise TypeError("requests must contain PlacementRequest instances")
        with self._lock:
            self._collect_released()
            pending = tuple(
                request
                for request in requests
                if request not in self._grants
                and self._reservation_candidates(request)[0]
                is PlacementState.UNAVAILABLE
            )
            cycle = self._find_wait_cycle(pending)
            if not cycle:
                return PlacementReconciliation()
            order = {
                self._session_key(request): index
                for index, request in enumerate(pending)
            }
            request_by_owner = {
                self._session_key(request): request for request in pending
            }
            victims = self._select_victims(
                cycle=cycle,
                request_by_owner=request_by_owner,
                order=order,
            )
            if not victims:
                return PlacementReconciliation()
            revoked = tuple(
                request
                for request in pending
                if self._session_key(request) in victims
            )
            for victim in victims:
                self._revoke_session(victim)
            ready: list[PlacementRequest] = []
            for request in pending:
                if self._session_key(request) in victims:
                    continue
                state, placement = self._reserve(request)
                if state is not PlacementState.SUCCESS:
                    continue
                if placement is None:
                    raise RuntimeError(
                        "successful placement reservation returned no placement"
                    )
                self._grants[request] = placement
                ready.append(request)
            return PlacementReconciliation(
                ready=tuple(ready),
                revoked=revoked,
            )

    def cancel_request(self, request: PlacementRequest) -> None:
        self._validate_request(request)
        with self._lock:
            self._release_grant(request)
            self._collect_released()

    def cancel_context(self, context_id: int) -> None:
        if isinstance(context_id, bool) or not isinstance(context_id, int):
            raise TypeError("context_id must be an int")
        with self._lock:
            requests = tuple(
                request for request in self._grants if request.context_id == context_id
            )
            for request in requests:
                self._release_grant(request)
            self._collect_released()

    def eviction_targets(
        self,
        request: PlacementRequest,
    ) -> tuple[PlacementEvictionTarget, ...]:
        self._validate_request(request)
        with self._lock:
            self._collect_released()
            state, _ = self._reservation_candidates(request)
            if state is not PlacementState.UNAVAILABLE:
                return ()
            plan = self._first_structural_plan(request)
            if plan is None:
                return ()
            targets: list[PlacementEvictionTarget] = []
            for allocator, requested_memory in plan:
                records = self._records_for_allocator(allocator)
                reservations = tuple(
                    (reservation_id, allocation.memory_bytes)
                    for reservation_id, _, allocation in records
                )
                must_clear = (
                    allocator.requires_exclusive(request)
                    or any(allocation.exclusive for _, _, allocation in records)
                )
                required_bytes = (
                    allocator.reserved_bytes
                    if must_clear
                    else max(0, requested_memory - allocator.available_bytes)
                )
                if must_clear and reservations and required_bytes == 0:
                    required_bytes = 1
                if required_bytes == 0:
                    continue
                targets.append(
                    PlacementEvictionTarget(
                        device_id=allocator.device_id,
                        exclusive=must_clear,
                        required_bytes=required_bytes,
                        reservations=reservations,
                    )
                )
            targets.sort(
                key=lambda target: (
                    target.exclusive,
                    target.required_bytes,
                    target.device_id,
                )
            )
            return tuple(targets)

    def close(self) -> None:
        with self._lock:
            self._grants.clear()
            self._collect_released()
            self._placements.clear()
            self._placement_ids.clear()
            for allocator in self._allocators:
                allocator.reset()

    def _reserve(
        self,
        request: PlacementRequest,
    ) -> tuple[PlacementState, PlacementGroup | None]:
        state, plan = self._reservation_candidates(request)
        if state is not PlacementState.SUCCESS:
            return state, None
        allocations: list[_DeviceAllocation] = []
        try:
            for allocator, memory_bytes in plan:
                exclusive = allocator.requires_exclusive(request)
                if not allocator.reserve(request, memory_bytes):
                    self._rollback_allocations(allocations)
                    return PlacementState.UNAVAILABLE, None
                allocations.append(
                    _DeviceAllocation(
                        allocator=allocator,
                        memory_bytes=memory_bytes,
                        exclusive=exclusive,
                    )
                )
            return PlacementState.SUCCESS, self._create_group(request, allocations)
        except BaseException:
            self._rollback_allocations(allocations)
            raise

    def _reservation_candidates(
        self,
        request: PlacementRequest,
    ) -> tuple[PlacementState, tuple[tuple[DeviceAllocator, int], ...]]:
        structurally_possible = False
        for device_count in request.device_counts():
            memory = request.allocation_bytes(device_count)
            if self._match_allocators(request, memory, available=False) is None:
                continue
            structurally_possible = True
            plan = self._match_allocators(request, memory, available=True)
            if plan is not None:
                return PlacementState.SUCCESS, plan
        if structurally_possible:
            return PlacementState.UNAVAILABLE, ()
        return PlacementState.IMPOSSIBLE, ()

    def _first_structural_plan(
        self,
        request: PlacementRequest,
    ) -> tuple[tuple[DeviceAllocator, int], ...] | None:
        for device_count in request.device_counts():
            plan = self._match_allocators(
                request,
                request.allocation_bytes(device_count),
                available=False,
            )
            if plan is not None:
                return plan
        return None

    def _match_allocators(
        self,
        request: PlacementRequest,
        memory: tuple[int, ...],
        *,
        available: bool,
        released_owners: set[_SessionKey] | frozenset[_SessionKey] = frozenset(),
    ) -> tuple[tuple[DeviceAllocator, int], ...] | None:
        unused = set(self._supported_allocators(request))
        plan: list[tuple[DeviceAllocator, int]] = []
        for memory_bytes in sorted(memory, reverse=True):
            candidates = [
                allocator
                for allocator in unused
                if self._allocator_accepts(
                    allocator,
                    request,
                    memory_bytes,
                    available=available,
                    released_owners=released_owners,
                )
            ]
            if not candidates:
                return None
            allocator = min(
                candidates,
                key=lambda candidate: (
                    self._allocator_free_bytes(candidate, released_owners)
                    - memory_bytes,
                    candidate.device_id,
                ),
            )
            unused.remove(allocator)
            plan.append((allocator, memory_bytes))
        return tuple(plan)

    def _allocator_accepts(
        self,
        allocator: DeviceAllocator,
        request: PlacementRequest,
        memory_bytes: int,
        *,
        available: bool,
        released_owners: set[_SessionKey] | frozenset[_SessionKey],
    ) -> bool:
        if not allocator.can_satisfy(request, memory_bytes):
            return False
        if not available:
            return True
        records = tuple(
            (record, allocation)
            for _, record, allocation in self._records_for_allocator(allocator)
            if record.owner not in released_owners
        )
        if any(allocation.exclusive for _, allocation in records):
            return False
        if allocator.requires_exclusive(request):
            return not records
        reserved = sum(allocation.memory_bytes for _, allocation in records)
        return memory_bytes <= allocator.capacity_bytes - reserved

    def _allocator_free_bytes(
        self,
        allocator: DeviceAllocator,
        released_owners: set[_SessionKey] | frozenset[_SessionKey],
    ) -> int:
        return allocator.capacity_bytes - sum(
            allocation.memory_bytes
            for _, record, allocation in self._records_for_allocator(allocator)
            if record.owner not in released_owners
        )

    def _create_group(
        self,
        request: PlacementRequest,
        allocations: list[_DeviceAllocation],
    ) -> PlacementGroup:
        lease = _PlacementLease()
        placements = tuple(
            Placement(
                device=request.device,
                backend=request.backend,
                device_id=allocation.allocator.device_id,
                memory_bytes=allocation.memory_bytes,
                _lease=lease,
            )
            for allocation in allocations
        )
        group = PlacementGroup(
            placements=placements,
            group_memory_bytes=request.group_memory_bytes,
            per_device_memory_bytes=request.per_device_memory_bytes,
            prefer_max_devices=request.prefer_max_devices,
            _lease=lease,
        )
        reservation_id = next(self._reservation_ids)
        locations: tuple[PlacementLocation, ...] = (group, *placements)
        location_refs = {id(location): ref(location) for location in locations}
        try:
            self._placements[reservation_id] = _PlacementRecord(
                lease_ref=ref(lease),
                location_refs=location_refs,
                allocations=tuple(allocations),
                owner=self._session_key(request),
            )
            for location in locations:
                self._placement_ids[id(location)] = reservation_id
            finalize(
                lease,
                self._release_later,
                self._released_reservations,
                self._capacity_released,
                reservation_id,
            )
        except BaseException:
            self._placements.pop(reservation_id, None)
            for object_id in location_refs:
                if self._placement_ids.get(object_id) == reservation_id:
                    del self._placement_ids[object_id]
            raise
        return group

    @staticmethod
    def _rollback_allocations(allocations: list[_DeviceAllocation]) -> None:
        for allocation in reversed(allocations):
            allocation.allocator.release(
                allocation.memory_bytes,
                exclusive=allocation.exclusive,
            )

    def _release_group(self, placement: PlacementGroup) -> None:
        reservation_id = self._placement_ids.get(id(placement))
        if reservation_id is None:
            return
        record = self._placements.get(reservation_id)
        if record is None:
            return
        location_ref = record.location_refs.get(id(placement))
        if location_ref is None or location_ref() is not placement:
            return
        self._release_reservation(reservation_id)

    def _release_grant(self, request: PlacementRequest) -> None:
        placement = self._grants.pop(request, None)
        if placement is not None:
            self._release_group(placement)

    def _revoke_session(self, owner: _SessionKey) -> None:
        for request in tuple(self._grants):
            if self._session_key(request) == owner:
                self._release_grant(request)
        reservation_ids = tuple(
            reservation_id
            for reservation_id, record in self._placements.items()
            if record.owner == owner
        )
        for reservation_id in reservation_ids:
            self._release_reservation(reservation_id)

    def _release_reservation(self, reservation_id: int) -> None:
        record = self._placements.get(reservation_id)
        if record is None:
            return
        self._rollback_allocations(list(record.allocations))
        del self._placements[reservation_id]
        for object_id in record.location_refs:
            if self._placement_ids.get(object_id) == reservation_id:
                del self._placement_ids[object_id]

    def _records_for_allocator(
        self,
        allocator: DeviceAllocator,
    ) -> tuple[tuple[int, _PlacementRecord, _DeviceAllocation], ...]:
        return tuple(
            (reservation_id, record, allocation)
            for reservation_id, record in self._placements.items()
            for allocation in record.allocations
            if allocation.allocator is allocator
        )

    def _find_wait_cycle(
        self,
        requests: tuple[PlacementRequest, ...],
    ) -> tuple[_SessionKey, ...]:
        if len(requests) < 2:
            return ()
        request_by_owner = {
            self._session_key(request): request for request in requests
        }
        holders = {record.owner for record in self._placements.values()}
        waiting_holders = set(request_by_owner).intersection(holders)
        if len(waiting_holders) < 2:
            return ()
        order = {
            self._session_key(request): index
            for index, request in enumerate(requests)
        }
        graph: dict[_SessionKey, tuple[_SessionKey, ...]] = {}
        for owner in waiting_holders:
            request = request_by_owner[owner]
            blockers: set[_SessionKey] = set()
            plan = self._first_structural_plan(request) or ()
            for allocator, memory_bytes in plan:
                if self._allocator_accepts(
                    allocator,
                    request,
                    memory_bytes,
                    available=True,
                    released_owners=frozenset(),
                ):
                    continue
                blockers.update(
                    record.owner
                    for _, record, _ in self._records_for_allocator(allocator)
                    if record.owner in waiting_holders and record.owner != owner
                )
            graph[owner] = tuple(sorted(blockers, key=order.__getitem__))
        ordered = sorted(waiting_holders, key=order.__getitem__)
        visited: set[_SessionKey] = set()
        finished: list[_SessionKey] = []
        for start in ordered:
            if start in visited:
                continue
            stack = [(start, False)]
            while stack:
                owner, expanded = stack.pop()
                if expanded:
                    finished.append(owner)
                    continue
                if owner in visited:
                    continue
                visited.add(owner)
                stack.append((owner, True))
                stack.extend(
                    (blocker, False)
                    for blocker in reversed(graph.get(owner, ()))
                    if blocker not in visited
                )
        reverse_graph: dict[_SessionKey, list[_SessionKey]] = {
            owner: [] for owner in ordered
        }
        for owner, blockers in graph.items():
            for blocker in blockers:
                reverse_graph[blocker].append(owner)
        visited.clear()
        components: list[tuple[_SessionKey, ...]] = []
        for start in reversed(finished):
            if start in visited:
                continue
            component: list[_SessionKey] = []
            stack = [start]
            visited.add(start)
            while stack:
                member = stack.pop()
                component.append(member)
                for predecessor in reverse_graph[member]:
                    if predecessor in visited:
                        continue
                    visited.add(predecessor)
                    stack.append(predecessor)
            if len(component) > 1:
                components.append(tuple(sorted(component, key=order.__getitem__)))
        if components:
            return min(components, key=lambda component: order[component[0]])
        return ()

    def _select_victims(
        self,
        cycle: tuple[_SessionKey, ...],
        request_by_owner: dict[_SessionKey, PlacementRequest],
        order: dict[_SessionKey, int],
    ) -> frozenset[_SessionKey]:
        owners = sorted(cycle, key=order.__getitem__)
        for winner in owners:
            victims: set[_SessionKey] = set()
            request = request_by_owner[winner]
            candidates = sorted(
                (candidate for candidate in owners if candidate != winner),
                key=lambda candidate: (
                    self._release_benefit(request, candidate),
                    order[candidate],
                ),
                reverse=True,
            )
            for candidate in candidates:
                victims.add(candidate)
                if self._can_reserve_after_release(request, victims):
                    return frozenset(victims)
        return frozenset()

    def _release_benefit(
        self,
        request: PlacementRequest,
        owner: _SessionKey,
    ) -> int:
        capable = set(self._supported_allocators(request))
        return sum(
            allocation.memory_bytes
            for record in self._placements.values()
            if record.owner == owner
            for allocation in record.allocations
            if allocation.allocator in capable
        )

    def _can_reserve_after_release(
        self,
        request: PlacementRequest,
        released_owners: set[_SessionKey] | frozenset[_SessionKey],
    ) -> bool:
        return any(
            self._match_allocators(
                request,
                request.allocation_bytes(device_count),
                available=True,
                released_owners=released_owners,
            )
            is not None
            for device_count in request.device_counts()
        )

    @staticmethod
    def _release_later(
        released_reservations: SimpleQueue[int],
        capacity_released: ReferenceType[Callable[[], None]] | None,
        reservation_id: int,
    ) -> None:
        released_reservations.put(reservation_id)
        if capacity_released is None:
            return
        callback = capacity_released()
        if callback is None:
            return
        try:
            callback()
        except BaseException:
            pass

    def _supported_allocators(
        self,
        request: PlacementRequest,
    ) -> tuple[DeviceAllocator, ...]:
        allocators = self._routes.get((request.device, request.backend), ())
        return tuple(
            allocator for allocator in allocators if allocator.supports(request)
        )

    def _collect_released(self) -> bool:
        released = False
        while True:
            try:
                reservation_id = self._released_reservations.get_nowait()
            except Empty:
                return released
            self._release_reservation(reservation_id)
            released = True

    @staticmethod
    def _session_key(request: PlacementRequest) -> _SessionKey:
        return (
            request.context_id,
            request.step_reference.step_index,
            request.iteration,
            request.execution,
        )

    def reservation_id(self, placement: PlacementLocation) -> int | None:
        if not isinstance(placement, (Placement, PlacementGroup)):
            raise TypeError("placement must be a Placement or PlacementGroup instance")
        with self._lock:
            reservation_id = self._placement_ids.get(id(placement))
            if reservation_id is None:
                return None
            record = self._placements.get(reservation_id)
            if record is None:
                return None
            location_ref = record.location_refs.get(id(placement))
            if location_ref is None or location_ref() is not placement:
                return None
            return reservation_id

    def _register_devices(
        self,
        runtime_devices: tuple[RuntimeDevice, ...],
    ) -> None:
        routes: dict[
            tuple[Device, Backend],
            list[DeviceAllocator],
        ] = defaultdict(list)
        allocators: list[DeviceAllocator] = []
        device_keys: set[tuple[Device, int]] = set()
        for runtime_device in runtime_devices:
            if runtime_device.device is Device.CPU:
                continue
            if runtime_device.device_id is None:
                raise ValueError("managed device requires a device ID")
            device_key = (runtime_device.device, runtime_device.device_id)
            if device_key in device_keys:
                raise ValueError("managed devices cannot contain duplicates")
            device_keys.add(device_key)
            allocator = DeviceAllocator(runtime_device)
            allocators.append(allocator)
            for backend in runtime_device.backends:
                routes[(runtime_device.device, backend)].append(allocator)
        self._allocators = tuple(allocators)
        self._routes = {
            route: tuple(route_allocators) for route, route_allocators in routes.items()
        }

    @staticmethod
    def _validate_request(request: PlacementRequest) -> None:
        if not isinstance(request, PlacementRequest):
            raise TypeError("request must be a PlacementRequest instance")

    @property
    def placement_count(self) -> int:
        with self._lock:
            self._collect_released()
            return len(self._placements)

    @property
    def granted_count(self) -> int:
        with self._lock:
            self._collect_released()
            return len(self._grants)
