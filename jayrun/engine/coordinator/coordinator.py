from __future__ import annotations

import asyncio
from time import monotonic

from ..base.runtime_module import RuntimeModule
from ..messages.commands.abort_context import AbortContextCommand
from ..limits import ContextHistoryLimitError
from ..messages.commands.apply_snapshot import ApplySnapshotCommand, _SnapshotRejectedError
from ..pressure import PressureSnapshot
from ..messages.commands.pause_context import PauseContextCommand
from ..messages.commands.reconcile_contexts import ReconcileContextsCommand
from ..messages.commands.resume_context import ResumeContextCommand
from ..messages.commands.retrieve_session import RetrieveSessionCommand
from ..messages.commands.shutdown_runtime import ShutdownRuntimeCommand
from ..messages.commands.start_context import StartContextCommand
from ..messages.commands.stop_context import StopContextCommand
from ..messages.commands.transfer_context import TransferContextCommand
from ..messages.commands.record_context import RecordContextCommand
from ..messages.events.context_admitted import ContextAdmittedEvent
from ..messages.events.context_registered import ContextRegisteredEvent
from ..messages.events.context_terminated import ContextTerminatedEvent
from ..messages.events.runtime_idle import RuntimeIdleEvent
from ..messages.runtime_message import _AcceptedRuntimeMessage
from .batch_size_estimator import BatchSizeEstimator
from .message_queue import RuntimeMessageQueue
from .state import CoordinatorState


class Coordinator(RuntimeModule):
    _shutdown_poll_interval = 10e-3

    def initialize(self) -> None:
        self._queue = RuntimeMessageQueue()

        self._batch_estimator = BatchSizeEstimator()
        self._handlers = {
            AbortContextCommand: self._handle_abort_context,
            ApplySnapshotCommand: self._handle_apply_snapshot,
            ContextAdmittedEvent: self._handle_context_admitted,
            ContextRegisteredEvent: self._handle_context_registered,
            ContextTerminatedEvent: self._handle_context_terminated,
            PauseContextCommand: self._handle_pause_context,
            ReconcileContextsCommand: self._handle_reconcile_contexts,
            ResumeContextCommand: self._handle_resume_context,
            RetrieveSessionCommand: self._handle_retrieve_session,
            RuntimeIdleEvent: self._handle_runtime_idle,
            ShutdownRuntimeCommand: self._handle_shutdown_runtime,
            StartContextCommand: self._handle_start_context,
            StopContextCommand: self._handle_stop_context,
            RecordContextCommand: self._handle_store_value,
            TransferContextCommand: self._handle_transfer_context,
        }
        self._state = CoordinatorState.CREATED
        # Fixed-size counts retain rejection classes, never input payloads or
        # exception tracebacks. Correctness evidence is not mode-dependent.
        self._snapshot_rejections = {"input": 0, "lifecycle": 0}

    async def run(self) -> None:
        self._state = CoordinatorState.RUNNING

        accepted: _AcceptedRuntimeMessage | None = None
        while self._state is not CoordinatorState.STOPPED:
            batch = await self._collect_batch()
            try:
                for accepted in batch:
                    if not self.accepts(accepted):
                        continue
                    self._dispatch(accepted)
            finally:
                # Completion outcomes can own artifact payloads. Release the
                # entire batch and loop variable before reconciliation/idle waits,
                # not only after another message eventually arrives.
                for pending in batch:
                    if pending.history_capture is not None:
                        pending.history_capture.discard()
                    if pending.ownership_reservation is not None:
                        self._engine_runtime.registry.release_ownership_reservation(pending.ownership_reservation)
                pending = None
                batch = ()
                accepted = None
            await self._reconcile()
            await asyncio.sleep(0)
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
        self._engine_runtime.registry.request_shutdown(
            forced=forced,
            origin=self.origin,
        )
        if forced:
            self._engine_runtime.executor_manager.cancel_contexts(
                self._engine_runtime.registry.draining_contexts()
            )

    def accepts(self, message: _AcceptedRuntimeMessage) -> bool:
        if self._state in {
            CoordinatorState.CREATED,
            CoordinatorState.RUNNING,
        }:
            return True
        if self._state is CoordinatorState.STOPPING:
            return message.accepted_during_shutdown
        return False

    async def _collect_batch(
        self,
    ) -> tuple[_AcceptedRuntimeMessage, ...]:
        if self._state is CoordinatorState.STOPPING:
            try:
                first = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=self._shutdown_poll_interval,
                )
            except asyncio.TimeoutError:
                return ()
        else:
            first = await self._queue.get()

        messages = [first]
        # Batch work that is already accepted, but never delay reconciliation
        # merely to fill a batch: the next arrival may depend on that work.
        for _ in range(self._batch_estimator.value - 1):
            try:
                messages.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        return tuple(messages)

    def put(
        self,
        message: _AcceptedRuntimeMessage,
    ) -> None:
        self._queue.put(message)

    def _dispatch(self, accepted: _AcceptedRuntimeMessage) -> None:
        message = accepted.message
        try:
            handler = self._handlers[type(message)]
        except KeyError:
            raise TypeError(
                f"unsupported runtime message: {type(message).__name__}"
            ) from None
        if accepted.history_capture is not None and isinstance(message, ApplySnapshotCommand):
            handler(message, accepted.origin, history_capture=accepted.history_capture)
        else:
            handler(message, accepted.origin)

    def _handle_abort_context(self, message, origin) -> None:
        self._engine_runtime.registry.abort_context(
            message.context_id,
            origin=origin,
        )

    def _handle_apply_snapshot(self, message, origin, *, history_capture=None) -> None:
        # Ingress validation precedes queueing. Earlier accepted updates can
        # invalidate a later snapshot before this owner turn; reject that input
        # before commitment rather than failing the runtime. Apply failures
        # remain fatal and are deliberately outside this validation boundary.
        try:
            self._engine_runtime.registry.validate_snapshot(message.snapshot)
            if isinstance(message.snapshot, PressureSnapshot):
                self._engine_runtime.registry.apply_snapshot(message.snapshot, origin=origin)
                return
        except (_SnapshotRejectedError, ContextHistoryLimitError):
            self._snapshot_rejections["lifecycle"] += 1
            return
        except (KeyError, TypeError, ValueError):
            self._snapshot_rejections["input"] += 1
            return
        if history_capture is not None:
            self._engine_runtime.registry.apply_snapshot(message.snapshot, origin=origin, history_capture=history_capture)
        else:
            self._engine_runtime.registry.apply_snapshot(message.snapshot, origin=origin)

    def _handle_pause_context(self, message, origin) -> None:
        duration = message.duration
        if duration is not None:
            duration = max(duration - (monotonic() - message.submitted_at), 0)
        self._engine_runtime.registry.pause_context(
            message.context_id,
            origin=origin,
            duration=duration,
        )

    def _handle_resume_context(self, message, origin) -> None:
        self._engine_runtime.registry.resume_context(
            message.context_id,
            origin=origin,
        )

    def _handle_stop_context(self, message, origin) -> None:
        self._engine_runtime.registry.stop_context(
            message.context_id,
            origin=origin,
        )

    def _handle_store_value(self, message, origin) -> None:
        self._engine_runtime.registry.store_context_record(
            message.record,
            origin=origin,
        )

    def _handle_transfer_context(self, message, origin) -> None:
        self._engine_runtime.registry.transfer_context(
            message.context_id,
            engine_id=message.engine_id,
            origin=origin,
        )

    def _handle_start_context(self, message, origin) -> None:
        self._engine_runtime.registry.start_context(
            message.context_id,
            origin=origin,
        )

    def _handle_reconcile_contexts(self, message, origin) -> None:
        self._engine_runtime.context_scheduler.reconcile()

    def _handle_retrieve_session(self, message, origin) -> None:
        self._engine_runtime.executor_manager.retrieve_session(message.session_id)

    def _handle_shutdown_runtime(self, message, origin) -> None:
        self.request_shutdown(forced=message.forced)

    def _handle_context_registered(self, message, origin) -> None:
        context = self._engine_runtime.registry.find_context(message.context_id)
        if context is not None and context.is_local:
            if message.supervising:
                self._engine_runtime.context_manager.register(context)
            else:
                self._engine_runtime.context_scheduler.admit_context(context)

    def _handle_context_admitted(self, message, origin) -> None:
        context = self._engine_runtime.registry.find_context(message.context_id)
        if context is not None and context.is_local:
            self._engine_runtime.context_manager.register(context)

    def _handle_context_terminated(self, message, origin) -> None:
        self._engine_runtime.registry.terminate_context(
            context_id=message.context_id,
            outcome=message.outcome,
        )
        self._engine_runtime.context_manager.acknowledge_termination(
            message.context_id
        )

    def _handle_runtime_idle(self, message, origin) -> None:
        self._engine_runtime.gateway.notify_idled_state()

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
            origin=self.origin,
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
            origin=self.origin,
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
            supervision_capacities=(
                self._engine_runtime.executor_manager.supervision_free
            ),
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
        self._engine_runtime.registry.finish_authority_shutdown_if_ready(
            self.origin
        )
        if self._engine_runtime.registry.has_unfinalized_contexts:
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
