from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from inspect import isawaitable
from threading import Lock
from typing import TYPE_CHECKING

from ...core.context.runtime_data import Data
from ..base.runtime_module import RuntimeModule
from ..context.resource_key import ResourceKey
from ..messages.commands.reconcile_contexts import ReconcileContextsCommand
from .cached_resource import CachedResource
from .placement import PlacementGroup
from .placement_controller import (
    PlacementController,
    PlacementEvictionTarget,
)
from .placement_request import (
    PlacementReconciliation,
    PlacementRequest,
    PlacementState,
)

if TYPE_CHECKING:
    from ..context.execution_proxy import ResourceTeardownProxy


@dataclass(frozen=True, slots=True)
class _EvictionPlan:
    resource_keys: tuple[ResourceKey, ...]
    released_bytes: int
    device_id: int


class ResourceManager(RuntimeModule):
    def initialize(self) -> None:
        self._closed = False
        self._cached_resources: dict[ResourceKey, CachedResource] = {}
        self._reconciliation_pending = False
        self._reconciliation_lock = Lock()
        self._placement_controller = PlacementController(
            runtime_devices=self._engine_runtime.engine_settings.runtime_devices,
            capacity_released=self._request_reconciliation,
        )

    def lookup(self, key: ResourceKey) -> bool | None:
        self._validate_key(key)
        cached_resource = self._cached_resources.get(key)
        if cached_resource is None:
            return False
        if cached_resource.can_be_acquired:
            return True
        return None

    def register(self, key: ResourceKey) -> None:
        self._validate_key(key)
        self._validate_parallel_safe(key)
        if key in self._cached_resources:
            raise ValueError(f"resource is already registered: {key!r}")
        self._cached_resources[key] = CachedResource(parallel_safe=key.parallel_safe)

    def cancel_registration(self, key: ResourceKey) -> None:
        self._validate_key(key)
        cached_resource = self._cached_resources.get(key)
        if cached_resource is None:
            return
        cached_resource.cancel_registration()
        del self._cached_resources[key]

    def load_data(
        self,
        key: ResourceKey,
        data: Data,
        proxy: ResourceTeardownProxy,
    ) -> None:
        self._validate_key(key)
        self._get_resource(key).mark_loaded(
            data=data,
            teardown_proxy=proxy,
        )
        self._request_reconciliation()

    def pin(self, key: ResourceKey) -> None:
        self._validate_key(key)
        self._get_resource(key).pin()

    def unpin(self, key: ResourceKey) -> None:
        self._validate_key(key)
        self._get_resource(key).unpin()

    def acquire(self, key: ResourceKey) -> Data:
        self._validate_key(key)
        return self._get_resource(key).acquire()

    def release(self, key: ResourceKey) -> None:
        self._validate_key(key)
        cached_resource = self._get_resource(key)
        was_acquirable = cached_resource.can_be_acquired
        cached_resource.release()
        if not was_acquirable and cached_resource.can_be_acquired:
            self._request_reconciliation()

    async def unload(self, key: ResourceKey) -> None:
        self._validate_key(key)
        cached_resource = self._get_resource(key)
        teardown_proxy = cached_resource.begin_unload()
        data = cached_resource.data
        if data is None:
            cached_resource.restore_ready()
            raise RuntimeError("loaded resource has no data")
        try:
            await self._teardown(teardown_proxy, data)
        except BaseException:
            cached_resource.restore_ready()
            raise
        del self._cached_resources[key]

    def reserve_placement(
        self,
        request: PlacementRequest,
    ) -> tuple[PlacementState, PlacementGroup | None]:
        try:
            return self._placement_controller.reserve(request)
        except BaseException as failure:
            try:
                self._engine_runtime.gateway.notify_failed_state(failure)
            except BaseException as reporting_failure:
                failure.add_note(
                    f"placement failure reporting also failed: {reporting_failure!r}"
                )
            raise

    async def reconcile_placements(
        self,
        requests: tuple[PlacementRequest, ...],
    ) -> PlacementReconciliation:
        with self._reconciliation_lock:
            self._reconciliation_pending = False
        if not requests:
            return PlacementReconciliation()
        ready = list(self._placement_controller.resolve(requests))
        ready_requests = set(ready)
        for request in requests:
            if request in ready_requests:
                continue
            plan = self._create_eviction_plan(request)
            if plan is None:
                continue
            for key in plan.resource_keys:
                await self.unload(key)
            notices = self._placement_controller.resolve((request,))
            ready.extend(notices)
            ready_requests.update(notices)
        waiting = tuple(
            request for request in requests if request not in ready_requests
        )
        recovered = self._placement_controller.recover_stuck(waiting)
        ready.extend(recovered.ready)
        return PlacementReconciliation(
            ready=tuple(ready),
            revoked=recovered.revoked,
        )

    def _request_reconciliation(self) -> None:
        try:
            with self._reconciliation_lock:
                if self._reconciliation_pending:
                    return
                self._reconciliation_pending = True
            accepted = self._engine_runtime.messenger.submit_after(
                ReconcileContextsCommand(identity=self.identity),
                delay=0,
            )
            if not accepted:
                with self._reconciliation_lock:
                    self._reconciliation_pending = False
        except BaseException as failure:
            with self._reconciliation_lock:
                self._reconciliation_pending = False
            try:
                self._engine_runtime.gateway.notify_failed_state(failure)
            except BaseException:
                pass

    def cancel_placement_request(self, request: PlacementRequest) -> None:
        self._placement_controller.cancel_request(request)

    def cancel_context_placements(self, context_id: int) -> None:
        self._placement_controller.cancel_context(context_id)

    async def close(self) -> None:
        if getattr(self, "_closed", False):
            return
        cached_resources = getattr(self, "_cached_resources", {})
        failures: list[BaseException] = []
        for key in tuple(cached_resources):
            cached_resource = cached_resources[key]
            if not cached_resource.can_be_closed:
                failures.append(RuntimeError(f"cannot close active resource: {key!r}"))
                continue
            try:
                if cached_resource.can_cancel_registration:
                    cached_resource.cancel_registration()
                    del self._cached_resources[key]
                else:
                    await self.unload(key)
            except BaseException as failure:
                failures.append(failure)
        placement_controller = getattr(self, "_placement_controller", None)
        if not cached_resources and placement_controller is not None:
            try:
                placement_controller.close()
            except BaseException as failure:
                failures.append(failure)
            else:
                self._closed = True
        elif placement_controller is None:
            self._closed = True
        if failures:
            raise BaseExceptionGroup("resource manager shutdown failed", failures)

    async def _teardown(
        self,
        proxy: ResourceTeardownProxy,
        data: Data,
    ) -> None:
        result = proxy.teardown(proxy, data)
        if isawaitable(result):
            await result

    def _create_eviction_plan(
        self,
        request: PlacementRequest,
    ) -> _EvictionPlan | None:
        resources = self._evictable_resources_by_placement()
        plans = tuple(
            plan
            for target in self._placement_controller.eviction_targets(request)
            if (plan := self._plan_target_eviction(target, resources)) is not None
        )
        if not plans:
            return None

        return min(
            plans,
            key=lambda plan: (
                len(plan.resource_keys),
                plan.released_bytes,
                plan.device_id,
            ),
        )

    def _evictable_resources_by_placement(
        self,
    ) -> dict[int, list[tuple[datetime, datetime, ResourceKey]]]:
        resources: dict[
            int,
            list[tuple[datetime, datetime, ResourceKey]],
        ] = {}
        for key, cached_resource in self._cached_resources.items():
            if not cached_resource.can_be_unloaded:
                continue
            reservation_id = self._placement_controller.reservation_id(
                cached_resource.placement
            )
            if reservation_id is None:
                continue
            resources.setdefault(reservation_id, []).append(
                (*cached_resource.eviction_sort_key, key),
            )
        return resources

    def _plan_target_eviction(
        self,
        target: PlacementEvictionTarget,
        resources: dict[int, list[tuple[datetime, datetime, ResourceKey]]],
    ) -> _EvictionPlan | None:
        reservations = dict(target.reservations)
        if target.exclusive:
            if not reservations or any(
                placement_id not in resources for placement_id in reservations
            ):
                return None
            selected_ids = tuple(reservations)
        else:
            candidates = sorted(
                (
                    min(
                        resources[placement_id],
                        key=lambda entry: (entry[0], entry[1]),
                    ),
                    placement_id,
                    memory_bytes,
                )
                for placement_id, memory_bytes in reservations.items()
                if placement_id in resources
            )
            selected: list[int] = []
            released_bytes = 0
            for _, placement_id, memory_bytes in candidates:
                selected.append(placement_id)
                released_bytes += memory_bytes
                if released_bytes >= target.required_bytes:
                    break
            if released_bytes < target.required_bytes:
                return None
            selected_ids = tuple(selected)
        resource_keys = tuple(
            entry[2]
            for placement_id in selected_ids
            for entry in sorted(
                resources[placement_id],
                key=lambda value: (value[0], value[1]),
            )
        )
        return _EvictionPlan(
            resource_keys=resource_keys,
            released_bytes=sum(reservations[value] for value in selected_ids),
            device_id=target.device_id,
        )

    def _get_resource(self, key: ResourceKey) -> CachedResource:
        cached_resource = self._cached_resources.get(key)
        if cached_resource is None:
            raise KeyError(f"unknown resource: {key!r}")
        return cached_resource

    @staticmethod
    def _validate_key(key: ResourceKey) -> None:
        if not isinstance(key, ResourceKey):
            raise TypeError("key must be a ResourceKey instance")

    @staticmethod
    def _validate_parallel_safe(key: ResourceKey) -> None:
        if not isinstance(key.parallel_safe, bool):
            raise TypeError("parallel_safe must be a bool")

    @property
    def placement_count(self) -> int:
        return self._placement_controller.placement_count

    @property
    def granted_placement_count(self) -> int:
        return self._placement_controller.granted_count
