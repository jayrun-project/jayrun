from __future__ import annotations

import asyncio

from ..base.runtime_module import RuntimeModule
from ..messages.runtime_message import RuntimeMessage
from .batch_size_estimator import BatchSizeEstimator
from .state import CoordinatorState
from .timeout_estimator import TimeoutEstimator


class Coordinator(RuntimeModule):
    def initialize(self) -> None:
        self._queue: asyncio.Queue[RuntimeMessage] = asyncio.Queue()

        self._batch_estimator = BatchSizeEstimator()
        self._timeout_estimator = TimeoutEstimator()

        self._state = CoordinatorState.CREATED

    async def run(self) -> None:
        self._state = CoordinatorState.RUNNING

        while self._state is not CoordinatorState.STOPPED:
            batch = await self._collect_batch()
            for message in batch:
                if not self.accepts(message):
                    continue
                message.execute()
            await self._reconcile()
            if self._state is CoordinatorState.STOPPING:
                self._complete_shutdown_if_ready()

        self._engine_runtime.gateway.notify_shutdown_ready()

    def request_shutdown(self, forced: bool) -> None:
        if self._state not in {
            CoordinatorState.RUNNING,
            CoordinatorState.STOPPING,
        }:
            raise RuntimeError(
                f"coordinator cannot shut down from {self._state.value!r}"
            )

        # The coordinator owns the shutdown boundary. Once STOPPING is entered,
        # only messages required to drain accepted work may still execute.
        self._state = CoordinatorState.STOPPING
        self._engine_runtime.registry.request_shutdown(forced=forced)
        if forced:
            self._engine_runtime.executor_manager.cancel_contexts(
                self._engine_runtime.registry.draining_contexts()
            )

    def accepts(self, message: RuntimeMessage) -> bool:
        if self._state in {
            CoordinatorState.CREATED,
            CoordinatorState.RUNNING,
        }:
            return True
        if self._state is CoordinatorState.STOPPING:
            return message.execute_during_shutdown
        return False

    async def _collect_batch(
        self,
    ) -> tuple[RuntimeMessage, ...]:
        first = await self._queue.get()

        self._timeout_estimator.update()

        messages = [first]

        timeout = self._timeout_estimator.estimate(
            batch_size=self._batch_estimator.value,
            queue_size=self._queue.qsize(),
        )
        deadline = asyncio.get_running_loop().time() + timeout
        while len(messages) < self._batch_estimator.value:
            remaining = deadline - asyncio.get_running_loop().time()

            if remaining <= 0:
                break

            try:
                message = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=remaining,
                )

                self._timeout_estimator.update()
                messages.append(message)

            except asyncio.TimeoutError:
                break

        return tuple(messages)

    def put(
        self,
        message: RuntimeMessage,
    ) -> None:
        self._queue.put_nowait(message)

    async def _reconcile(self) -> None:
        if self._state == CoordinatorState.STOPPED:
            return
        requests = self._engine_runtime.registry.pending_placement_requests
        reconciliation = (
            await self._engine_runtime.resource_manager.reconcile_placements(
                requests
            )
        )
        resolved = self._engine_runtime.registry.resolve_placement_requests(
            reconciliation.ready,
            identity=self.identity,
        )
        rejected = self._engine_runtime.context_manager.resolve_placements(resolved)
        accepted = set(resolved) - set(rejected)
        stale = tuple(
            request
            for request in reconciliation.ready
            if request not in accepted
        )
        for request in stale:
            self._engine_runtime.resource_manager.cancel_placement_request(request)
        revoked = self._engine_runtime.registry.revoke_placement_requests(
            reconciliation.revoked,
            identity=self.identity,
        )
        rejected_revocations = (
            self._engine_runtime.context_manager.revoke_placements(revoked)
        )
        if rejected_revocations:
            raise RuntimeError(
                "registry-approved placement revocation was rejected"
            )
        capacities = self._engine_runtime.executor_manager.free

        sessions = self._engine_runtime.context_manager.acquire(
            capacities=capacities,
        )

        self._engine_runtime.executor_manager.assign(
            sessions=sessions,
        )

        active_sessions = sum(self._engine_runtime.executor_manager.occupied.values())

        self._batch_estimator.update(
            active_sessions,
        )

    def _complete_shutdown_if_ready(self) -> None:
        # Shutdown is safe only after contexts have finalized, executor callbacks
        # have been collected, placements have been cancelled, and the message
        # queue contains no remaining lifecycle work.
        if self._engine_runtime.registry.has_nonterminal_contexts:
            return
        if not self._engine_runtime.context_manager.empty:
            return
        if any(self._engine_runtime.executor_manager.occupied.values()):
            return
        if self._engine_runtime.registry.pending_placement_requests:
            return
        if not self._queue.empty():
            return
        self._state = CoordinatorState.STOPPED

    @property
    def is_stopping(self) -> bool:
        return self._state is CoordinatorState.STOPPING

    @property
    def is_stopped(self) -> bool:
        return self._state is CoordinatorState.STOPPED
