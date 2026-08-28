from __future__ import annotations

from collections import deque

from ...core.artifact.base import Artifact
from ...core.context.runtime_data import Data
from ...core.graph.compiled_graph import (
    CompiledOperatorStep,
    CompiledResourceStep,
    CompiledStep,
)
from ...core.resource.base import BaseResource
from ...core.resource.field import ResourceField
from ..artifact.store import ExecutionArtifactStore
from ..execution.execution_mode import ExecutionMode
from ..interfaces.context import ContextInterface
from ..interfaces.execution import (
    ExecutionRequests,
    OperatorExecutionInterface,
    ResourceExecutionInterface,
)
from ..interfaces.placement import PlacementInterface
from ..interfaces.runtime import RuntimeInterface
from ..interfaces.services.accesses import ContextAccess, RuntimeAccess
from ..recorders.context.recorder import ContextRecorder
from ..recorders.execution.recorder import ExecutionRecorder
from ..registry.context_instance import ContextInstance
from ..registry.identities import ContextIdentity
from ..registry.runtime_registry import RuntimeRegistry
from ..resource.placement_request import PlacementRequest
from ..resource.resource_manager import ResourceManager
from .context_outcome import ContextOutcome
from .execution_proxy import (
    AsyncExecutionProxy,
    ExecutionProxy,
    ResourceTeardownProxy,
    SyncExecutionProxy,
)
from .execution_session import ExecutionSession
from .execution_state import ExecutionState
from .execution_step import ExecutionOperator, ExecutionResource
from .execution_tracker import ExecutionTracker
from .resource_key import ResourceKey


class ExecutionContext:
    def __init__(
        self,
        context_instance: ContextInstance,
        recorder: ContextRecorder,
        resource_manager: ResourceManager,
        runtime_access: RuntimeAccess,
        context_access: ContextAccess,
        runtime_registry: RuntimeRegistry,
    ) -> None:
        self.context_id = context_instance.context_id
        self._context = context_instance
        self._graph = context_instance.graph
        self._config_context = context_instance.config_context
        self._artifact_context = context_instance.artifact_context
        self._settings = context_instance.settings
        self._max_repeats = context_instance.settings.max_repeats
        self._recorder = recorder
        self._resource_manager = resource_manager
        self._runtime_access = runtime_access
        self._context_access = context_access
        self._registry = runtime_registry
        self._identity = ContextIdentity(context_id=self.context_id)
        self._live_sessions: dict[int, ExecutionSession] = {}
        self._placement_waiting_sessions: dict[int, ExecutionSession] = {}
        self._ready_steps: deque[tuple[int, ExecutionMode]] = deque()
        self._rescheduled_sessions: deque[ExecutionSession] = deque()
        self._resource_pins: dict[ResourceKey, int] = {}
        self._outcome: ContextOutcome | None = None

    def initialize(self) -> None:
        if not self._context.has_been_validated:
            raise RuntimeError("context has not been validated")

        compiled_graph = self._graph.compiled_graph
        self._compiled_steps: tuple[CompiledStep, ...] = compiled_graph.steps
        self._artifact_store = ExecutionArtifactStore(
            artifacts=compiled_graph.artifacts,
            entry_artifacts=compiled_graph.entry_artifacts,
            feedback_artifacts=tuple(
                artifact
                for artifact in compiled_graph.entry_artifacts
                if self._graph._specification.artifacts.definition_for(
                    artifact
                ).is_exit
            ),
            artifact_context=self._artifact_context,
            recorder=self._recorder.create_artifact_recorder(),
            settings=self._settings,
        )
        self._reset_iteration_state()

    def dispatch_next(self, mode: ExecutionMode) -> ExecutionSession | None:
        self.finalize_if_drained()
        if self.terminated or not self._context.can_dispatch:
            return None

        for _ in range(len(self._rescheduled_sessions)):
            session = self._rescheduled_sessions.popleft()
            if session.execution_mode is mode:
                if self._live_sessions.get(session.step.index) is not session:
                    raise RuntimeError("rescheduled session is not live")
                session.dispatch()
                return session
            self._rescheduled_sessions.append(session)

        for _ in range(len(self._ready_steps)):
            index, step_mode = self._ready_steps.popleft()
            if step_mode is not mode:
                self._ready_steps.append((index, step_mode))
                continue

            step = self._compiled_steps[index]
            registration_key: ResourceKey | None = None
            if isinstance(step, CompiledResourceStep):
                key = self._create_resource_key(
                    field=step.resource_field,
                    resource=step.resource,
                )
                lookup = self._resource_manager.lookup(key)
                if lookup is True:
                    self._pin_resource(key)
                    self._record_skipped_step(index, "resource_available")
                    self._complete_step(index)
                    continue
                if lookup is None:
                    self._ready_steps.append((index, step_mode))
                    continue
                if lookup is False:
                    self._resource_manager.register(key)
                    registration_key = key
                else:
                    raise TypeError("resource lookup must return True, False, or None")

            try:
                session = self._create_execution_session(index)
            except BaseException as failure:
                if registration_key is not None:
                    try:
                        self._resource_manager.cancel_registration(registration_key)
                    except BaseException as cleanup_failure:
                        failure.add_note(
                            "resource registration rollback also failed: "
                            f"{cleanup_failure!r}"
                        )
                raise
            if session is None:
                if registration_key is not None:
                    self._resource_manager.cancel_registration(registration_key)
                self._ready_steps.append((index, step_mode))
                continue

            if index in self._live_sessions:
                raise RuntimeError("step already has a live session")
            session._resource_registration_key = registration_key
            self._live_sessions[index] = session
            try:
                session.dispatch()
            except BaseException as failure:
                try:
                    self._drain_session(session, index)
                except BaseException as cleanup_failure:
                    failure.add_note(
                        f"session dispatch rollback also failed: {cleanup_failure!r}"
                    )
                raise
            return session

        return None

    def collect(self, session: ExecutionSession) -> None:
        index = session.step.index
        if self._live_sessions.get(index) is not session:
            if session.report is not None and session._report_recorded:
                return
            raise ValueError("session was not dispatched by this execution context")
        try:
            if self._context.is_draining:
                self._drain_session(session, index)
                self.finalize_if_drained()
            elif session.placement_waiting:
                self._collect_placement_waiting(session, index)
            elif session.finished:
                self._collect_finished(session, index)
            elif session.failed:
                self._collect_failed(session, index)
            else:
                raise RuntimeError("only a finished or failed session can be collected")
        except BaseException as failure:
            self._contain_collection_failure(session, index, failure)
            raise

    def finalize_if_drained(self) -> None:
        if self.terminated:
            return

        if self._context.is_terminal or self._context.is_draining:
            self._drain_non_dispatched_sessions()
            if not self._live_sessions:
                self._finalize(retain_results=False)
            return

        if (
            self._context.is_running
            and self._tracker.is_done
            and not self._live_sessions
        ):
            self._finish_iteration()

    def _reset_iteration_state(self) -> None:
        if self._live_sessions:
            raise RuntimeError("cannot reset while sessions are live")
        compiled_graph = self._graph.compiled_graph
        self._pending_dependencies = list(compiled_graph.initial_dependency_counts)
        self._tracker = ExecutionTracker(len(self._compiled_steps))
        self._ready_steps: deque[tuple[int, ExecutionMode]] = deque()
        self._rescheduled_sessions: deque[ExecutionSession] = deque()
        self._initialize_ready_steps()

    def _initialize_ready_steps(self) -> None:
        completed: deque[int] = deque()
        for index, dependency_count in enumerate(self._pending_dependencies):
            if dependency_count == 0 and self._prepare_step(index):
                completed.append(index)
        self._unlock_successors(completed)

    def _prepare_step(self, index: int) -> bool:
        step = self._compiled_steps[index]
        if isinstance(step, CompiledOperatorStep):
            return self._prepare_operator(index)
        if isinstance(step, CompiledResourceStep):
            return self._prepare_resource(index)
        raise TypeError("compiled graph contains an unsupported step")

    def _prepare_operator(self, index: int) -> bool:
        if self._operator_has_none_input(index):
            self._release_operator_artifacts(
                self._compiled_steps[index],
                produced_artifacts=(),
            )
            self._record_skipped_step(index, "missing_input")
            return True
        step = self._compiled_steps[index]
        self._ready_steps.append((index, step.execution_mode))
        return False

    def _prepare_resource(self, index: int) -> bool:
        step = self._compiled_steps[index]
        if not isinstance(step, CompiledResourceStep):
            raise TypeError("resource preparation requires a resource step")

        if self._operator_has_none_input(step.group_indices[-1]):
            self._record_skipped_step(index, "missing_input")
            return True

        key = self._create_resource_key(
            field=step.resource_field,
            resource=step.resource,
        )
        lookup = self._resource_manager.lookup(key)
        if lookup is True:
            self._pin_resource(key)
            self._record_skipped_step(index, "resource_available")
            return True

        if lookup is not False and lookup is not None:
            raise TypeError("resource lookup must return True, False, or None")

        self._ready_steps.append((index, step.execution_mode))
        return False

    def _unlock_successors(self, completed: deque[int]) -> None:
        while completed:
            index = completed.popleft()
            for successor_index in self._compiled_steps[index].successor_indices:
                self._pending_dependencies[successor_index] -= 1
                if self._pending_dependencies[successor_index] != 0:
                    continue
                if self._prepare_step(successor_index):
                    completed.append(successor_index)

    def _complete_step(self, index: int) -> None:
        self._unlock_successors(deque((index,)))

    def _create_execution_session(self, index: int) -> ExecutionSession | None:
        step = self._compiled_steps[index]
        if isinstance(step, CompiledOperatorStep):
            return self._create_operator_session(index, step)
        if isinstance(step, CompiledResourceStep):
            return self._create_resource_session(index, step)
        raise TypeError("compiled graph contains an unsupported step")

    def _create_operator_session(
        self,
        index: int,
        step: CompiledOperatorStep,
    ) -> ExecutionSession | None:
        recorder = self._create_execution_recorder(
            index=index,
            step_kind="operator",
            step_name=step.operator_name,
            layout_position=step.layout_position,
        )
        proxy = self._create_proxy(step.execution_mode)
        resource_bindings = tuple(
            (
                field,
                self._create_resource_key(field=field, resource=resource),
            )
            for field, resource in step.bound_resources
        )
        resource_keys = tuple(dict.fromkeys(key for _, key in resource_bindings))
        for key in resource_keys:
            lookup = self._resource_manager.lookup(key)
            if lookup is not True:
                if lookup is not False and lookup is not None:
                    raise TypeError("resource lookup must return True, False, or None")
                return None

        acquired_keys: list[ResourceKey] = []
        try:
            resource_data: dict[ResourceKey, Data] = {}
            for key in resource_keys:
                resource_data[key] = self._resource_manager.acquire(key)
                acquired_keys.append(key)
            for field, key in resource_bindings:
                setattr(proxy, field.attribute_name, resource_data[key])

            for field in step.config_fields:
                setattr(proxy, field.attribute_name, self._config_context.get(field))

            for field in step.declared_artifact_fields:
                setattr(proxy, field.attribute_name, Data(value=None))

            for field in step.bound_artifact_fields:
                setattr(
                    proxy,
                    field.attribute_name,
                    self._artifact_store.get(field.artifact),
                )

            self._attach_scope_interfaces(proxy, recorder, operator=True)
            proxy._runtime_output_mask = step.output_mask
            proxy._runtime_execute = step.execute_method

            session = ExecutionSession(
                step=ExecutionOperator(
                    index=index,
                    proxy=proxy,
                    context_id=self.context_id,
                ),
                execution_mode=step.execution_mode,
                recorder=recorder,
            )
            session._resource_keys.extend(acquired_keys)
            return session
        except BaseException as failure:
            for acquired_key in reversed(acquired_keys):
                try:
                    self._release_acquired_resource(acquired_key)
                except BaseException as cleanup_failure:
                    failure.add_note(
                        f"operator resource rollback also failed: {cleanup_failure!r}"
                    )
            raise

    def _create_resource_session(
        self,
        index: int,
        step: CompiledResourceStep,
    ) -> ExecutionSession:
        recorder = self._create_execution_recorder(
            index=index,
            step_kind="resource",
            step_name=step.resource.display_name,
            layout_position=step.layout_position,
        )
        proxy = self._create_proxy(step.execution_mode)

        for field in step.resource.config_fields:
            setattr(proxy, field.attribute_name, self._config_context.get(field))

        self._attach_scope_interfaces(proxy, recorder, operator=False)
        proxy._runtime_output_mask = step.output_mask
        proxy._runtime_execute = step.setup_method

        return ExecutionSession(
            step=ExecutionResource(
                index=index,
                proxy=proxy,
                context_id=self.context_id,
            ),
            execution_mode=step.execution_mode,
            recorder=recorder,
        )

    def _create_execution_recorder(
        self,
        index: int,
        step_kind: str,
        step_name: str,
        layout_position: tuple[int, int],
    ) -> ExecutionRecorder:
        recorder = self._recorder.create_execution_recorder()
        recorder.initialize(
            step_index=index,
            step_kind=step_kind,
            step_name=step_name,
            context_id=self.context_id,
            iteration=self._context.iteration_count,
            layout_position=layout_position,
        )
        return recorder

    def _create_proxy(self, mode: ExecutionMode) -> ExecutionProxy:
        if mode is ExecutionMode.EVENT_LOOP:
            return AsyncExecutionProxy()
        if mode is ExecutionMode.THREAD:
            return SyncExecutionProxy()
        raise ValueError(f"unsupported execution mode: {mode!r}")

    def _attach_scope_interfaces(
        self,
        proxy: ExecutionProxy,
        recorder: ExecutionRecorder,
        operator: bool,
    ) -> None:
        proxy.execution = (
            OperatorExecutionInterface(recorder=recorder)
            if operator
            else ResourceExecutionInterface(recorder=recorder)
        )
        proxy.placement = PlacementInterface(
            recorder=recorder,
            resource_manager=self._resource_manager,
        )
        proxy.context = ContextInterface(
            recorder=recorder,
            context_access=self._context_access,
        )
        proxy.runtime = RuntimeInterface(
            recorder=recorder,
            runtime_access=self._runtime_access,
        )

    def _drain_session(self, session: ExecutionSession, index: int) -> None:
        self._placement_waiting_sessions.pop(index, None)
        self._rescheduled_sessions = deque(
            queued for queued in self._rescheduled_sessions if queued is not session
        )
        failures: list[BaseException] = []
        for cleanup in (
            lambda: self._release_session_resources(session),
            lambda: self._cancel_session_registration(session),
            session.cancel,
            session.finalize,
            lambda: self._release_session_artifacts(session),
            lambda: self._record_session_report(session),
        ):
            try:
                cleanup()
            except BaseException as failure:
                failures.append(failure)
        if failures:
            raise BaseExceptionGroup("session drain failed", failures)
        if self._live_sessions.get(index) is session:
            del self._live_sessions[index]

    def _collect_placement_waiting(
        self,
        session: ExecutionSession,
        index: int,
    ) -> None:
        request = session.placement_request
        if request is None:
            raise RuntimeError("placement-waiting session has no request")
        if index in self._placement_waiting_sessions:
            raise RuntimeError("step is already waiting for placement")
        self._placement_waiting_sessions[index] = session
        self._registry.register_placement_request(
            request=request,
            identity=self._identity,
        )

    def resolve_placement(self, request: PlacementRequest) -> bool:
        if self.terminated or self._context.is_draining:
            return False
        index = request.step_reference.step_index
        session = self._placement_waiting_sessions.get(index)
        if session is None or session.placement_request != request:
            return False
        if self._live_sessions.get(index) is not session:
            raise RuntimeError("placement-waiting session is not live")
        del self._placement_waiting_sessions[index]
        session.resume_placement(request)
        self._rescheduled_sessions.append(session)
        return True

    def revoke_placement(self, request: PlacementRequest) -> bool:
        if self.terminated or self._context.is_draining:
            return False
        index = request.step_reference.step_index
        session = self._placement_waiting_sessions.get(index)
        if session is None or session.placement_request != request:
            return False
        if self._live_sessions.get(index) is not session:
            raise RuntimeError("placement-waiting session is not live")
        del self._placement_waiting_sessions[index]
        session.restart_placements(request)
        self._rescheduled_sessions.append(session)
        return True

    def _drain_non_dispatched_sessions(self) -> None:
        failures: list[BaseException] = []
        for index, session in tuple(self._live_sessions.items()):
            if session.state is ExecutionState.DISPATCHED:
                continue
            try:
                self._drain_session(session, index)
            except BaseException as failure:
                failures.append(failure)
        if failures:
            raise BaseExceptionGroup("context session drain failed", failures)

    def _contain_collection_failure(
        self,
        session: ExecutionSession,
        index: int,
        failure: BaseException,
    ) -> None:
        try:
            self._drain_session(session, index)
        except BaseException as cleanup_failure:
            failure.add_note(f"session cleanup also failed: {cleanup_failure!r}")

        context_failure: Exception
        if isinstance(failure, Exception):
            context_failure = failure
        else:
            context_failure = RuntimeError(
                "session collection escaped with a non-Exception failure"
            )
            context_failure.__cause__ = failure

        if not self._context.is_terminal and not self._context.is_draining:
            try:
                self._registry.fail_context(
                    context_id=self.context_id,
                    identity=self._identity,
                    failure=context_failure,
                    failed_step=session.recorder.step_reference,
                )
            except BaseException as transition_failure:
                failure.add_note(
                    f"context failure transition also failed: {transition_failure!r}"
                )

        try:
            self.finalize_if_drained()
        except BaseException as finalization_failure:
            failure.add_note(
                f"context finalization also failed: {finalization_failure!r}"
            )

    def _collect_finished(self, session: ExecutionSession, index: int) -> None:
        requests: ExecutionRequests = session.step.proxy.execution._requests
        if requests.repeat_requested and (
            self._max_repeats is None or session.repeat_count < self._max_repeats
        ):
            self._store_repeated_result(session, index)
            session.repeat()
            self._rescheduled_sessions.append(session)
            return

        if session.result is None:
            raise RuntimeError("finished session has no result")

        if session.placement_requests:
            self._registry.record_placement_requests(session.placement_requests)

        self._apply_result(session, index, session.result)
        session.finalize()
        self._release_session_artifacts(session)
        self._record_session_report(session)
        self._tracker.finished()
        del self._live_sessions[index]

        if self._tracker.is_done and self._context.is_running:
            self._finish_iteration()

    def _collect_failed(self, session: ExecutionSession, index: int) -> None:
        failure = session.failure
        if failure is None:
            raise RuntimeError("failed session has no failure")

        retry_policy = self._settings.retry_policy
        if (
            isinstance(failure, retry_policy.retry_on)
            and session.attempt_count < retry_policy.max_attempts
        ):
            session.retry()
            self._rescheduled_sessions.append(session)
            return

        self._release_session_resources(session)
        self._cancel_session_registration(session)
        session.finalize()
        self._release_session_artifacts(session)
        self._record_session_report(session)
        del self._live_sessions[index]
        self._registry.fail_context(
            context_id=self.context_id,
            identity=self._identity,
            failure=failure,
            failed_step=session.recorder.step_reference,
        )
        self.finalize_if_drained()

    def _store_repeated_result(
        self,
        session: ExecutionSession,
        index: int,
    ) -> None:
        step = self._compiled_steps[index]
        if not isinstance(step, CompiledOperatorStep):
            raise TypeError("only operators can repeat")
        if session.result is None:
            raise RuntimeError("finished session has no result")

        self._store_operator_result(step, session.result, index)
        for field in step.bound_artifact_fields:
            setattr(
                session.step.proxy,
                field.attribute_name,
                self._artifact_store.get(field.artifact),
            )

    def _apply_result(
        self,
        session: ExecutionSession,
        index: int,
        result: tuple[object, ...],
    ) -> None:
        step = self._compiled_steps[index]
        if isinstance(step, CompiledOperatorStep):
            try:
                self._store_operator_result(step, result, index)
                self._release_operator_artifacts(
                    step,
                    produced_artifacts=tuple(
                        field.artifact
                        for field in step.output_fields
                        if field.artifact is not None
                    ),
                )
            finally:
                self._release_session_resources(session)
        elif isinstance(step, CompiledResourceStep):
            self._load_resource(session, step, result)
        else:
            raise TypeError("compiled graph contains an unsupported step")
        self._complete_step(index)

    def _store_operator_result(
        self,
        step: CompiledOperatorStep,
        result: tuple[object, ...],
        index: int,
    ) -> None:
        for output, output_field in zip(result, step.output_fields, strict=True):
            self._artifact_store.update(
                artifact=output_field.artifact,
                data=output,
                step_index=index,
            )

    def _release_session_resources(self, session: ExecutionSession) -> None:
        failures: list[BaseException] = []
        for key in tuple(reversed(session._resource_keys)):
            try:
                self._release_acquired_resource(key)
            except BaseException as failure:
                failures.append(failure)
            else:
                session._resource_keys.remove(key)
        if failures:
            raise BaseExceptionGroup("session resource release failed", failures)

    def _cancel_session_registration(self, session: ExecutionSession) -> None:
        key = session._resource_registration_key
        if key is None:
            return
        self._resource_manager.cancel_registration(key)
        session._resource_registration_key = None

    def _record_session_report(self, session: ExecutionSession) -> None:
        if session._report_recorded:
            return
        self._recorder.record(session.report)
        session._report_recorded = True

    def _release_session_artifacts(self, session: ExecutionSession) -> None:
        session.result = None
        step = self._compiled_steps[session.step.index]
        if not isinstance(step, CompiledOperatorStep):
            return
        proxy = session.step.proxy
        for field in (*step.bound_artifact_fields, *step.declared_artifact_fields):
            if field.attribute_name is not None:
                setattr(proxy, field.attribute_name, Data(value=None))

    def _load_resource(
        self,
        session: ExecutionSession,
        step: CompiledResourceStep,
        result: tuple[object, ...],
    ) -> None:

        teardown_proxy = ResourceTeardownProxy()
        for field in step.resource.config_fields:
            setattr(
                teardown_proxy,
                field.attribute_name,
                self._config_context.get(field),
            )
        teardown_proxy.teardown = step.teardown_method
        key = session._resource_registration_key
        if key is None:
            raise RuntimeError("resource session has no active registration")

        self._resource_manager.load_data(
            key=key,
            proxy=teardown_proxy,
            data=result[0],
        )
        session._resource_registration_key = None
        try:
            self._record_resource_pin(key)
        except BaseException:
            self._resource_manager.unpin(key)
            raise

    def _finish_iteration(self) -> None:
        if self._registry.reiterate_context(
            context_id=self.context_id,
            identity=self._identity,
        ):
            self._artifact_store.repeat()
            self._reset_iteration_state()
            return
        self._finalize(retain_results=True)

    def _finalize(self, *, retain_results: bool) -> None:
        if self._outcome is not None:
            return
        if self._live_sessions:
            raise RuntimeError("cannot finalize while sessions are live")

        failures: list[BaseException] = []
        for cleanup in (
            self._release_pending_resource_pins,
            lambda: self._artifact_store.finalize(
                retain_results=retain_results,
            ),
            self._recorder.stop,
        ):
            try:
                cleanup()
            except BaseException as failure:
                failures.append(failure)
        if failures:
            raise BaseExceptionGroup("context finalization failed", failures)
        self._outcome = ContextOutcome(
            actor=self._identity,
            report=self._recorder.report,
            artifacts=self._artifact_store.result,
            failure=self._context.failure,
            failed_step=self._context.failed_step,
        )

    def _operator_has_none_input(self, index: int) -> bool:
        step = self._compiled_steps[index]
        for field in step.bound_artifact_fields:
            if self._artifact_store.get(field.artifact).value is None:
                return True
        return False

    def _create_resource_key(
        self,
        field: ResourceField,
        resource: BaseResource,
    ) -> ResourceKey:
        configuration = []

        for config_field in resource.config_fields:
            if config_field.attribute_name is None:
                raise RuntimeError("resource config field is not registered")

            config_data = self._config_context.get(config_field)
            value = None if config_data is None else config_data.value
            configuration.append((config_field.attribute_name, value))

        return ResourceKey(
            resource_type=type(resource),
            configuration=tuple(configuration),
            parallel_safe=field.parallel_safe,
        )

    def _record_resource_pin(self, key: ResourceKey) -> None:
        self._resource_pins[key] = self._resource_pins.get(key, 0) + 1

    def _pin_resource(self, key: ResourceKey) -> None:
        self._resource_manager.pin(key)
        try:
            self._record_resource_pin(key)
        except BaseException as failure:
            try:
                self._resource_manager.unpin(key)
            except BaseException as cleanup_failure:
                failure.add_note(
                    f"resource pin rollback also failed: {cleanup_failure!r}"
                )
            raise

    def _release_acquired_resource(self, key: ResourceKey) -> None:
        if self._resource_pins.get(key, 0) < 1:
            raise RuntimeError("execution context does not own a resource pin")
        self._resource_manager.release(key)
        self._consume_resource_pin(key)

    def _consume_resource_pin(self, key: ResourceKey) -> None:
        pin_count = self._resource_pins.get(key, 0)
        if pin_count < 1:
            raise RuntimeError("execution context does not own a resource pin")
        if pin_count == 1:
            del self._resource_pins[key]
        else:
            self._resource_pins[key] = pin_count - 1

    def _release_pending_resource_pins(self) -> None:
        failures: list[BaseException] = []
        for key, pin_count in tuple(self._resource_pins.items()):
            for _ in range(pin_count):
                try:
                    self._resource_manager.unpin(key)
                except BaseException as failure:
                    failures.append(failure)
                else:
                    self._consume_resource_pin(key)
        if failures:
            raise BaseExceptionGroup("context resource unpin failed", failures)

    def _rollback_initialization(self) -> None:
        if self.terminated:
            return
        self._drain_non_dispatched_sessions()
        if self._has_dispatched_sessions:
            raise RuntimeError("cannot roll back a context with dispatched sessions")
        if not hasattr(self, "_artifact_store"):
            failures: list[BaseException] = []
            for cleanup in (
                self._release_pending_resource_pins,
                self._recorder.stop,
            ):
                try:
                    cleanup()
                except BaseException as failure:
                    failures.append(failure)
            if failures:
                raise BaseExceptionGroup(
                    "context initialization rollback failed",
                    failures,
                )
            return
        self._finalize(retain_results=False)

    def _cancel_unsubmitted_session(self, session: ExecutionSession) -> None:
        index = session.step.index
        if self._live_sessions.get(index) is not session:
            return
        self._drain_session(session, index)

    def _record_skipped_step(self, index: int, reason: str) -> None:
        step = self._compiled_steps[index]
        if isinstance(step, CompiledOperatorStep):
            step_kind = "operator"
            step_name = step.operator_name
        elif isinstance(step, CompiledResourceStep):
            step_kind = "resource"
            step_name = step.resource.display_name
        else:
            raise TypeError("compiled graph contains an unsupported step")
        self._recorder.record_skipped(
            step_index=index,
            step_kind=step_kind,
            step_name=step_name,
            layout_position=step.layout_position,
            context_id=self.context_id,
            iteration=self._context.iteration_count,
            reason=reason,
        )
        self._tracker.skipped()

    def _release_operator_artifacts(
        self,
        step: CompiledStep,
        *,
        produced_artifacts: tuple[Artifact, ...],
    ) -> None:
        if not isinstance(step, CompiledOperatorStep):
            raise TypeError("artifact release requires an operator step")
        self._artifact_store.release_consumed(
            consumed_artifacts=tuple(
                field.artifact
                for field in step.bound_artifact_fields
                if field.artifact is not None
            ),
            produced_artifacts=produced_artifacts,
        )

    @property
    def terminated(self) -> bool:
        return self._outcome is not None

    @property
    def _has_dispatched_sessions(self) -> bool:
        return any(
            session.state is ExecutionState.DISPATCHED
            for session in self._live_sessions.values()
        )

    @property
    def outcome(self) -> ContextOutcome:
        if self._outcome is None:
            raise RuntimeError("execution context has not terminated")
        return self._outcome

    @property
    def is_supervising(self) -> bool:
        return self._context.is_supervising
