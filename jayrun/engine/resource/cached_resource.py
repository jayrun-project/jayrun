from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ...core.context.runtime_data import Data
from .placement import PlacementLocation
from .resource_state import ResourceState

if TYPE_CHECKING:
    from ..context.execution_proxy import ResourceTeardownProxy


@dataclass(slots=True)
class CachedResource:
    parallel_safe: bool
    state: ResourceState = ResourceState.LOADING
    data: Data | None = None
    created_at: datetime | None = None
    last_accessed_at: datetime | None = None
    access_count: int = 0
    active_user_count: int = 0
    pin_count: int = 0
    teardown_proxy: ResourceTeardownProxy | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.parallel_safe, bool):
            raise TypeError(
                f"'parallel_safe' must be a bool, got {type(self.parallel_safe).__name__!r}."
            )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @property
    def can_be_acquired(self) -> bool:
        if self.state is ResourceState.READY:
            return True
        if self.state is ResourceState.IN_USE:
            return self.parallel_safe
        return False

    @property
    def can_be_released(self) -> bool:
        return self.state is ResourceState.IN_USE and self.active_user_count > 0

    @property
    def can_be_pinned(self) -> bool:
        return self.can_be_acquired

    @property
    def can_be_unpinned(self) -> bool:
        return (
            self.state in {ResourceState.READY, ResourceState.IN_USE}
            and self.pin_count > 0
        )

    @property
    def can_be_unloaded(self) -> bool:
        return (
            self.state is ResourceState.READY
            and self.pin_count == 0
            and self.active_user_count == 0
        )

    @property
    def can_cancel_registration(self) -> bool:
        return self.state is ResourceState.LOADING

    @property
    def can_be_closed(self) -> bool:
        return self.can_cancel_registration or self.can_be_unloaded

    @property
    def placement(self) -> PlacementLocation:
        if self.data is None:
            raise RuntimeError("Loaded resource has no data.")
        return self.data.placement

    @property
    def eviction_sort_key(self) -> tuple[datetime, datetime]:
        if self.last_accessed_at is None or self.created_at is None:
            raise RuntimeError("Loaded resource has incomplete timestamps.")
        return self.last_accessed_at, self.created_at

    def cancel_registration(self) -> None:
        if not self.can_cancel_registration:
            raise RuntimeError("Only a loading resource registration can be cancelled.")

    def mark_loaded(
        self,
        *,
        data: Data,
        teardown_proxy: ResourceTeardownProxy,
    ) -> None:
        if self.state is not ResourceState.LOADING:
            raise RuntimeError("Only a loading resource can be marked as loaded.")

        if not isinstance(data, Data):
            raise TypeError("data must be a Data instance.")

        if not callable(getattr(teardown_proxy, "teardown", None)):
            raise TypeError("teardown_proxy must provide a callable teardown method.")

        now = self._now()
        self.data = data
        self.teardown_proxy = teardown_proxy
        self.created_at = now
        self.last_accessed_at = now
        self.pin_count = 1
        self.state = ResourceState.READY

    def pin(self) -> None:
        if not self.can_be_pinned:
            raise RuntimeError("Resource cannot be pinned.")

        self.pin_count += 1

    def unpin(self) -> None:
        if not self.can_be_unpinned:
            raise RuntimeError("Resource cannot be unpinned.")

        self.pin_count -= 1

    def acquire(self) -> Data:
        if not self.can_be_acquired:
            raise RuntimeError("Resource cannot be acquired.")

        if self.pin_count < 1:
            raise RuntimeError("Resource must be pinned before acquisition.")

        if self.data is None:
            raise RuntimeError("Ready resource has no data.")

        self.active_user_count += 1
        self.access_count += 1
        self.last_accessed_at = self._now()
        self.state = ResourceState.IN_USE

        return self.data

    def release(self) -> None:
        if not self.can_be_released:
            raise RuntimeError("Resource cannot be released.")

        if self.pin_count < 1:
            raise RuntimeError("Resource pin count is inconsistent.")

        self.active_user_count -= 1
        self.pin_count -= 1
        self.last_accessed_at = self._now()

        if self.active_user_count == 0:
            self.state = ResourceState.READY

    def begin_unload(self) -> ResourceTeardownProxy:
        if not self.can_be_unloaded:
            raise RuntimeError("Resource cannot be unloaded.")

        if self.teardown_proxy is None:
            raise RuntimeError("Loaded resource has no teardown proxy.")

        self.state = ResourceState.UNLOADING
        return self.teardown_proxy

    def restore_ready(self) -> None:
        if self.state is not ResourceState.UNLOADING:
            raise RuntimeError("Only an unloading resource can be restored.")

        self.state = ResourceState.READY
