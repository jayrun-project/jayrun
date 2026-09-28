from __future__ import annotations

import asyncio
import threading
from collections import deque
from collections.abc import AsyncIterator, Hashable, Iterator
from dataclasses import dataclass
from datetime import datetime

from .registry.context_state import ContextState
from .registry.context_state import ContextRequest
from .snapshot import ContextSnapshot
from .messages.origin import CommandOrigin
from .submission import _GraphScope, _SupervisionScope


@dataclass(frozen=True, slots=True)
class ContextStateChanged:
    """Committed lifecycle transition for one context.

    Attributes:
        context_id: Probabilistically unique 62-bit logical context identifier.
        graph_key: Registered graph key, or ``None`` for a local graph.
        graph_version: Version of the submitted graph.
        previous_state: State before the transition, or ``None`` when the context
            first becomes observable.
        current_state: State after the transition.
        revision: Context lifecycle revision associated with the transition.
        occurred_at: UTC time at which the transition was committed.
        snapshot: Complete context snapshot captured with the transition.
    """

    context_id: int
    graph_key: str | None
    graph_version: str
    previous_state: ContextState | None
    current_state: ContextState
    revision: int
    occurred_at: datetime
    snapshot: ContextSnapshot


@dataclass(frozen=True, slots=True)
class ContextStopRequested:
    """Stop accepted by the execution owner, independently of lifecycle state.

    ``actor``, ``revision`` and ``occurred_at`` identify the existing committed
    StopRequested history entry. Repeated Stop requests do not publish another
    acceptance. Unlike ContextControlRequested, this is an accepted fact, not
    forwarded intent. The snapshot retains the actual execution state; Stop
    prevents a new iteration but does not imply completion or cancel live work.

    When a committed remote snapshot first reveals acceptance, the event carries
    that snapshot (possibly already finalized) and the original entry identity.
    It does not reconstruct intermediate observations lost before synchronization.
    Normal observer scope and bounded-queue overflow rules apply.
    """

    context_id: int
    graph_key: str | None
    graph_version: str
    actor: CommandOrigin
    revision: int
    occurred_at: datetime
    snapshot: ContextSnapshot


@dataclass(frozen=True, slots=True)
class ContextValueStored:
    """Notification that a context value was committed.

    The event metadata identifies the new record while :attr:`snapshot` contains
    the complete committed context view, including the stored value.

    Attributes:
        context_id: Probabilistically unique 62-bit logical context identifier.
        graph_key: Registered graph key, or ``None`` for a local graph.
        graph_version: Version of the submitted graph.
        key: Key under which the context stored the value.
        record_index: One-based recording index within this context.
        step_name: Operator or resource step that stored the value.
        iteration: Context iteration that produced the value.
        execution: Execution number within the step session.
        occurred_at: UTC time at which the value record was created.
        snapshot: Complete context snapshot captured after storage committed.
    """

    context_id: int
    graph_key: str | None
    graph_version: str
    key: Hashable
    record_index: int
    step_name: str
    iteration: int
    execution: int
    occurred_at: datetime
    snapshot: ContextSnapshot


@dataclass(frozen=True, slots=True)
class ContextControlRequested:
    """Portable control intent for a context owned by another engine_id.

    Attributes:
        context_id: Probabilistically unique 62-bit logical context identifier.
        graph_key: Registered graph key, or ``None`` for local-only work.
        graph_version: Version of the context graph.
        request: Requested lifecycle operation; it is not yet committed state.
        occurred_at: UTC time at which the request was recorded.
        snapshot: Complete atomic context view carrying the request.
    """

    context_id: int
    graph_key: str | None
    graph_version: str
    request: ContextRequest
    occurred_at: datetime
    snapshot: ContextSnapshot


@dataclass(frozen=True, slots=True)
class ContextTransferred:
    """Committed change to the engine_id assigned to an ordinary context.

    Attributes:
        context_id: Probabilistically unique 62-bit logical context identifier.
        graph_key: Registered graph key, or ``None`` for local-only work.
        graph_version: Version of the context graph.
        previous_engine_id: Engine-incarnation identity before transfer.
        current_engine_id: Engine-incarnation identity after transfer.
        generation: New ownership generation fencing older owners.
        occurred_at: UTC time at which transfer committed.
        snapshot: Complete atomic context view after transfer.
    """

    context_id: int
    graph_key: str | None
    graph_version: str
    previous_engine_id: str
    current_engine_id: str
    generation: int
    occurred_at: datetime
    snapshot: ContextSnapshot


ContextEvent = (
    ContextStateChanged
    | ContextStopRequested
    | ContextValueStored
    | ContextControlRequested
    | ContextTransferred
)


class ObserverOverflowError(RuntimeError):
    """Raised when an observer did not consume its bounded queue in time."""


class ContextObserver(Iterator[ContextEvent], AsyncIterator[ContextEvent]):
    """Bounded destructive queue of context observation events.

    External code creates observers through :meth:`jayrun.Engine.observer`.
    Every supervising or controlling context instead receives one fixed queue as
    ``self.runtime.events``. Both :func:`next` and :func:`anext` remove and return
    the oldest event. If the queue fills, Jayrun clears and detaches it;
    subsequent consumption raises :class:`ObserverOverflowError`. Closing an
    observer wakes pending consumers and allows queued events to drain. During
    graceful shutdown, an authority-owned queue closes after ordinary work
    finalizes so a normal ``for`` or ``async for`` loop can return.
    """

    def __init__(self, hub: _ObservationHub, capacity: int) -> None:
        self._hub: _ObservationHub | None = hub
        self._capacity = capacity
        self._condition = threading.Condition()
        self._events: deque[ContextEvent] = deque()
        self._async_waiters: set[asyncio.Future[None]] = set()
        self._closed = False
        self._overflowed = False

    @property
    def capacity(self) -> int:
        """Maximum number of pending events before overflow."""
        return self._capacity

    @property
    def closed(self) -> bool:
        """Whether this observer has been closed or detached."""
        with self._condition:
            return self._closed or self._overflowed

    @property
    def overflowed(self) -> bool:
        """Whether this observer was detached because its queue filled."""
        with self._condition:
            return self._overflowed

    def close(self) -> None:
        """Detach this observer and wake any pending consumers."""
        with self._condition:
            if self._closed:
                return
            self._closed = True
            hub = self._hub
            self._hub = None
            waiters = self._wake_locked()
        if hub is not None:
            hub._discard(self)
        self._wake_async(waiters)

    def __next__(self) -> ContextEvent:
        with self._condition:
            while not self._events:
                if self._overflowed:
                    raise ObserverOverflowError(
                        f"observer queue exceeded its capacity of {self._capacity}"
                    )
                if self._closed:
                    raise StopIteration
                self._condition.wait()
            return self._events.popleft()

    async def __anext__(self) -> ContextEvent:
        loop = asyncio.get_running_loop()
        while True:
            with self._condition:
                if self._events:
                    return self._events.popleft()
                if self._overflowed:
                    raise ObserverOverflowError(
                        f"observer queue exceeded its capacity of {self._capacity}"
                    )
                if self._closed:
                    raise StopAsyncIteration
                waiter = loop.create_future()
                self._async_waiters.add(waiter)
            try:
                await waiter
            finally:
                with self._condition:
                    self._async_waiters.discard(waiter)

    def __iter__(self) -> ContextObserver:
        return self

    def __aiter__(self) -> ContextObserver:
        return self

    def __enter__(self) -> ContextObserver:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object,
    ) -> None:
        self.close()

    def _publish(self, event: ContextEvent) -> bool:
        with self._condition:
            if self._closed or self._overflowed:
                return False
            if len(self._events) >= self._capacity:
                self._events.clear()
                self._overflowed = True
                self._hub = None
                waiters = self._wake_locked()
                accepted = False
            else:
                self._events.append(event)
                waiters = self._wake_locked()
                accepted = True
        self._wake_async(waiters)
        return accepted

    def _close_from_hub(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._hub = None
            waiters = self._wake_locked()
        self._wake_async(waiters)

    def _wake_locked(self) -> tuple[asyncio.Future[None], ...]:
        self._condition.notify_all()
        return tuple(self._async_waiters)

    @staticmethod
    def _wake_async(waiters: tuple[asyncio.Future[None], ...]) -> None:
        failures: list[Exception] = []
        for waiter in waiters:
            loop = waiter.get_loop()
            try:
                loop.call_soon_threadsafe(ContextObserver._complete_waiter, waiter)
            except RuntimeError as failure:
                # A consumer loop may legitimately close after it registered a
                # waiter. Other scheduling failures are not evidence of closure.
                if not loop.is_closed():
                    failures.append(failure)
            except Exception as failure:
                failures.append(failure)
        if failures:
            # Attempt every independent waiter before reporting unexpected faults.
            raise ExceptionGroup("observer wakeup failed", failures)

    @staticmethod
    def _complete_waiter(waiter: asyncio.Future[None]) -> None:
        if not waiter.done():
            waiter.set_result(None)


@dataclass(frozen=True, slots=True)
class _ObserverRegistration:
    observer: ContextObserver
    owner_context_id: int | None
    graph_scope: _SupervisionScope


class _ObservationHub:
    _MAX_OBSERVERS = 64
    _DEFAULT_CAPACITY = 256

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._registrations: dict[ContextObserver, _ObserverRegistration] = {}
        self._closed = False

    def observer(
        self,
        *,
        capacity: int = _DEFAULT_CAPACITY,
        owner_context_id: int | None = None,
        graph_scope: _SupervisionScope = None,
    ) -> ContextObserver:
        if type(capacity) is not int:
            raise TypeError("capacity must be an int")
        if capacity < 1:
            raise ValueError("capacity must be greater than zero")
        with self._lock:
            if self._closed:
                raise RuntimeError("runtime observation is closed")
            if len(self._registrations) >= self._MAX_OBSERVERS:
                raise RuntimeError("runtime observer limit has been reached")
            observer = ContextObserver(self, capacity)
            self._registrations[observer] = _ObserverRegistration(
                observer=observer,
                owner_context_id=owner_context_id,
                graph_scope=graph_scope,
            )
            return observer

    def interested(self, context_id: int, graph_scope: _GraphScope) -> bool:
        """Whether a snapshot has a visible consumer at this observation boundary."""
        with self._lock:
            return not self._closed and any(
                self._visible(registration, context_id, graph_scope)
                for registration in self._registrations.values()
            )

    def publish(self, event: ContextEvent, graph_scope: _GraphScope) -> None:
        with self._lock:
            if self._closed:
                return
            registrations = tuple(self._registrations.values())
        detached = []
        for registration in registrations:
            if not self._visible(registration, event.context_id, graph_scope):
                continue
            if not registration.observer._publish(event):
                detached.append(registration.observer)
        if detached:
            with self._lock:
                for observer in detached:
                    self._registrations.pop(observer, None)

    def close_owner(self, context_id: int) -> None:
        with self._lock:
            observers = tuple(
                registration.observer
                for registration in self._registrations.values()
                if registration.owner_context_id == context_id
            )
            for observer in observers:
                self._registrations.pop(observer, None)
        for observer in observers:
            observer._close_from_hub()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            observers = tuple(self._registrations)
            self._registrations.clear()
        for observer in observers:
            observer._close_from_hub()

    def _discard(self, observer: ContextObserver) -> None:
        with self._lock:
            self._registrations.pop(observer, None)

    @staticmethod
    def _visible(
        registration: _ObserverRegistration,
        context_id: int,
        graph_scope: _GraphScope,
    ) -> bool:
        if registration.owner_context_id == context_id:
            return False
        supervised = registration.graph_scope
        if supervised is None:
            return True
        if supervised == ():
            return False
        return any(
            graph_scope == candidate
            if isinstance(graph_scope, tuple) and isinstance(candidate, tuple)
            else graph_scope is candidate
            for candidate in supervised
        )
