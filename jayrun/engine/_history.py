"""Lifecycle-owned diagnostic capture, separate from execution and timing learning.

Only enabled engines import this adapter. Submission capture runs on the submitting
thread outside runtime locks. Finalization registers bounded detached owner facts;
the Database lane encodes them before an atomic context/layout publication.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, fields, replace
from datetime import datetime, timezone
import platform
import sys
import threading
import time
from types import MappingProxyType
from typing import TYPE_CHECKING, TypeAlias
import weakref

from .. import __version__
from ..core.graph.definition.artifact import ArtifactDefinition
from ..core.graph.compiled_graph import CompiledOperatorStep, CompiledResourceStep
from ..persistence import Database, PersistenceBackpressure, PersistenceError
from ..persistence.errors import PersistenceTimeout, StorageContractError
from ..persistence._database import _Reservation, _wait
from ..persistence.records import (ContextHistoryEntry, ContextHistoryHeader, EngineSessionHeader,
                                   EngineSessionRecord, SerializedLayout, _context_body, _json as _layout_json)
from ..persistence.values import ValueMarker, ValuePath, ValueSnapshot
from .context.step_reference import StepReference
from .interfaces.context_record import ContextRecord
from .messages.origin import EngineOrigin, RuntimeModuleOrigin, ContextOrigin, StepOrigin
from .progress import ProgressSnapshot, StepProgress, StepProgressState
from .recorders.artifact.record import ArtifactRecord
from .recorders.artifact.artifact_state import ArtifactState
from .artifact.actor import ArtifactActor
from .recorders.context.report import ContextReport
from .recorders.execution.records import (AttemptRecord, ExecutionReport, ExecutionOutcome,
    FailureRecord, LogRecord, MetricRecord, RecordOrigin, TimerRecord)
from .registry.context_status import (StateTransition, StopRequested, IterationStarted,
                                     ControlRequested, EngineChanged)
from .registry.context_state import ContextState, ContextRequest
from .resource.placement import Placement, PlacementGroup
from .settings.context import ContextSettings
from .settings.engine import RetryPolicy
from ._capture_values import _encode_detached_facts, _encode_framework_value

if TYPE_CHECKING:
    from ..core.graph.graph_definition import GraphDefinition
    from ..core.graph.graph_registry import GraphRegistry
    from ..core.config.context import ConfigContext
    from .registry.context_instance import ContextInstance
    from .settings.combined_context import CombinedContextSettings
    from .settings.engine import EngineSettings
    from .submission import _NormalizedSubmission
    from .snapshot import ContextSnapshot


_StepCorrespondence: TypeAlias = tuple[int, str, str, tuple[int, int], str]


def _capture_caller() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise RuntimeError(
        "database-enabled synchronous start/submit/apply captures diagnostics; "
        "use await asyncio.to_thread(...) instead of blocking a running event loop"
    )


def _qualified(cls: type) -> str:
    module = type.__getattribute__(cls, "__module__")
    name = type.__getattribute__(cls, "__qualname__")
    return f"{module}.{name}" if type(module) is str and type(name) is str else "unknown type"


def _redactions(database: Database, namespace: str) -> tuple[ValuePath, ...]:
    # A root redaction applies to every diagnostic namespace, never to essential
    # structural identities or to strings that the application chose as labels.
    return tuple(path[1:] if path else () for path in database.redact
                 if not path or path[0] == namespace)


def _encode(database: Database, namespace: str, value: object) -> ValueSnapshot:
    # Engine facts are already supported detached values. Application codecs run
    # only at the pre-execution producer boundary, never on the backend lane.
    return _encode_detached_facts(value, limits=database.value_limits,
                                  redact=_redactions(database, namespace))


def _retry(policy: RetryPolicy) -> dict[str, object]:
    return {"max_attempts": policy.max_attempts,
            "retry_on": tuple(_qualified(cls) for cls in policy.retry_on)}


def _context_settings(settings: ContextSettings | CombinedContextSettings | None, graph: GraphDefinition) -> object:
    if settings is None:
        return ValueMarker("missing", "No per-context settings override was supplied")
    registry = graph._specification.artifacts
    ids = []
    for reference in settings.artifact_policy.retained_artifacts or ():
        if type(reference) is int:
            ids.append(reference)
        elif isinstance(reference, ArtifactDefinition):
            ids.append(reference.artifact_id)
        else:
            ids.append(registry.definition_for(reference).artifact_id)
    result = {name: getattr(settings, name) for name in (
        "max_iterations", "max_repeats", "record_history_limit", "record_max_keys",
        "record_max_value_bytes", "record_max_total_bytes")}
    result["retry_policy"] = None if settings.retry_policy is None else _retry(settings.retry_policy)
    result["artifact_policy"] = {"retained_artifacts": None if settings.artifact_policy.retained_artifacts is None else tuple(ids), "release_entry_artifacts": settings.artifact_policy.release_entry_artifacts}
    if hasattr(settings, "recording_mode"):
        result["recording_mode"] = settings.recording_mode.value
        result["failure_mode"] = settings.failure_mode.value
    return result


def _engine_settings(settings: EngineSettings) -> dict[str, object]:
    result = {name: getattr(settings, name) for name in (
        "max_workers", "max_tasks", "context_history_admission_limit", "remote_context_id_limit",
        "terminal_history_limit", "terminal_history_max_bytes")}
    result.update(recording_mode=settings.recording_mode.value, failure_mode=settings.failure_mode.value,
                  routing_mode=settings.routing_mode.value, retry_policy=_retry(settings.retry_policy))
    result["runtime_devices"] = tuple({"device": device.device.value,
        "backends": tuple(backend.value for backend in device.backends), "device_id": device.device_id,
        "memory_limit_gb": device.memory_limit_gb, "exclusive_only": device.exclusive_only}
        for device in settings.runtime_devices)
    return result


_FACT_TYPES = (ContextReport, ExecutionReport, AttemptRecord, TimerRecord, MetricRecord,
               LogRecord, FailureRecord, ContextRecord, ArtifactRecord, StepReference,
               StateTransition, StopRequested, IterationStarted, ControlRequested, EngineChanged,
               EngineOrigin, RuntimeModuleOrigin, ContextOrigin, StepOrigin, ProgressSnapshot, StepProgress)
_ENUM_TYPES = (ContextState, ContextRequest, StepProgressState, RecordOrigin, ExecutionOutcome,
               ArtifactState, ArtifactActor)


class _Facts:
    """Bounded copies of exact framework facts, never arbitrary-object inspection."""

    def __init__(self, database: Database, byte_limit: int) -> None:
        self.limits = database.value_limits
        self.remaining = byte_limit
        self.nodes = 0
        self.active: set[int] = set()
        self.complete = True

    def _take(self, size: int = 64) -> None:
        self.nodes += 1
        self.remaining -= size
        if self.nodes > self.limits.max_nodes or self.remaining < 0:
            raise PersistenceBackpressure("final diagnostic facts exceed the capture allowance")

    def copy(self, value: object, depth: int = 0) -> object:
        self._take()
        cls = type(value)
        if depth > self.limits.max_depth:
            raise PersistenceBackpressure("final diagnostic facts exceed the depth limit")
        if value is None or cls in (bool, float, datetime):
            return value
        if cls is int:
            self._take(max(1, (value.bit_length() + 7) // 8))
            return value
        if cls is str:
            # Conservative UTF-8/JSON source charge without allocating an encoding.
            self._take(6 * len(value))
            return value
        if cls in _ENUM_TYPES:
            return value.value
        if isinstance(value, type):
            return self.copy(_qualified(value), depth + 1)
        if isinstance(value, BaseExceptionGroup):
            # Read built-in descriptors, not application overrides or traceback
            # formatting. Preserve bounded nested cleanup/primary failures.
            children = BaseExceptionGroup.exceptions.__get__(value)
            if len(children) > self.limits.max_items:
                raise PersistenceBackpressure("too many grouped diagnostic failures")
            return {"type": self.copy(_qualified(cls), depth + 1),
                    "message": self.copy(BaseExceptionGroup.message.__get__(value), depth + 1),
                    "exceptions": tuple(self.copy(child, depth + 1) for child in children)}
        if isinstance(value, BaseException):
            # Never queue an exception/traceback. Preserve its type and supported
            # scalar arguments; complex application arguments stay unavailable.
            args = BaseException.args.__get__(value)
            if len(args) > self.limits.max_items:
                raise PersistenceBackpressure("too many exception arguments")
            safe = []
            for arg in args:
                if arg is None or type(arg) in (bool, int, float, str):
                    safe.append(self.copy(arg, depth + 1))
                else:
                    self.complete = False
                    safe.append(ValueMarker("unsupported", "Non-scalar exception argument excluded"))
            return {"type": self.copy(_qualified(cls), depth + 1), "arguments": tuple(safe)}
        if cls in _FACT_TYPES:
            return {field.name: self.copy(getattr(value, field.name), depth + 1) for field in fields(value)}
        if cls in (dict, MappingProxyType, tuple, list):
            if len(value) > self.limits.max_items:
                raise PersistenceBackpressure("final diagnostic collection exceeds its item limit")
            identity = id(value)
            if identity in self.active:
                raise StorageContractError("cyclic framework diagnostic facts")
            self.active.add(identity)
            try:
                if cls in (dict, MappingProxyType):
                    return {self.copy(key, depth + 1): self.copy(child, depth + 1) for key, child in value.items()}
                return tuple(self.copy(child, depth + 1) for child in value)
            finally:
                self.active.remove(identity)
        self.complete = False
        return ValueMarker("unsupported", "Not a supported framework diagnostic fact")


def _placement(value: Placement | PlacementGroup) -> tuple[dict[str, object], ...]:
    if type(value) is Placement:
        placements = (value,)
    elif type(value) is PlacementGroup:
        placements = value.placements
    else:
        return ()
    return tuple({"device": item.device.value, "backend": item.backend.value if item.backend else None,
                  "device_id": item.device_id, "memory_bytes": item.memory_bytes} for item in placements)


def _layout(graph: GraphDefinition) -> tuple[SerializedLayout, tuple[_StepCorrespondence, ...]]:
    from ..visualization.adapters.definition import _report_payload
    from ..visualization.contract import MAX_NODES, MAX_CONNECTIONS
    operators = graph.inspect.operators
    if (len(operators) + len(graph.inspect.artifacts.entry) + len(graph.inspect.artifacts.exit) > MAX_NODES
            or len(graph.artifacts) > MAX_CONNECTIONS):
        raise StorageContractError("declaration exceeds the portable viewer topology bounds")
    # Reject oversized structural labels before the adapter hashes/JSON-copies
    # them. Defaults are excluded separately; this does not discover secrets.
    components = (*graph.artifacts, *(reference.operator for reference in operators),
                  *graph._resource_context.instances.values())
    for component in components:
        for text in (component.name, component.description):
            if text is not None and (type(text) is not str or len(text) > 8192):
                raise StorageContractError("declaration text exceeds the portable viewer bound")
    # Do not put unredacted configuration defaults (or hashes of them) into the
    # picture. Runtime values live only in the independently redacted typed field.
    payload = _report_payload(graph.validate(), graph.artifacts, graph=graph, include_config_defaults=False)
    nodes = {tuple(node["identity"]["Core layout position"]): node
             for node in payload["nodes"] if node["kind"] == "operator"}
    for node in nodes.values():
        node["execution_steps"] = []
        for marker in node["resources"]:
            marker["execution_steps"] = []
    descriptors = []
    steps = graph._compiled_graph.steps
    for index, step in enumerate(steps):
        node = nodes.get(step.layout_position)
        if node is None:
            raise StorageContractError("compiled step has no portable occurrence")
        if isinstance(step, CompiledOperatorStep):
            kind, name, subject = "operator", step.operator_name, node
        elif isinstance(step, CompiledResourceStep):
            kind, name = "resource", step.resource_name
            consuming = next((steps[i] for i in step.group_indices if isinstance(steps[i], CompiledOperatorStep)), None)
            if consuming is None or not any(field is step.resource_field and resource is step.resource
                                           for field, resource in consuming.bound_resources):
                raise StorageContractError("resource step has no verified bound consumer")
            markers = [marker for marker in node["resources"] if marker["details"]["Field"] == step.resource_field.attribute_name]
            if len(markers) != 1:
                raise StorageContractError("resource step has no unique portable field")
            subject = markers[0]
        else:
            raise StorageContractError("unknown compiled step kind")
        subject["execution_steps"].append(index)
        descriptors.append((index, kind, name, step.layout_position, subject["id"]))
    payload["details"]["Historical configuration"] = "Resolved values are stored separately; layout defaults are excluded."
    # The adapter already normalized this payload. Our only additions above are
    # checked step indices and fixed text. Constructing the bytes envelope still
    # validates the complete final layout; from_payload would normalize it again.
    return SerializedLayout(graph.graph_id, graph.version, payload["schema_version"],
                            _layout_json(payload)), tuple(descriptors)


@dataclass(frozen=True, slots=True)
class _LayoutCache:
    graph: weakref.ReferenceType[GraphDefinition]
    serializers_bound: bool
    layout: SerializedLayout
    steps: tuple[_StepCorrespondence, ...]
    reservation: _Reservation


class _ContextCapture:
    """Private, charged pre-execution inputs. No graph, artifact or authority refs."""

    def __init__(self, recorder: _HistoryRecorder, reservation: _Reservation,
                 graph_id: str, graph_version: str, source: str) -> None:
        self.recorder = recorder
        self.reservation = reservation
        self.graph_id = graph_id
        self.graph_version = graph_version
        self.source = source
        self.captured_at = datetime.now(timezone.utc)
        self.configurations = self.requested_settings = self.effective_settings = None
        self.layout: SerializedLayout | None = None
        self.steps: tuple[_StepCorrespondence, ...] = ()
        self.coverage: tuple[str, ...] = ()
        self.gap = False
        self.claimed = False
        self.capture_generation = 0
        self.serializers_bound = False
        self.done = False
        self.lock = threading.Lock()

    def check_binding(self, graph: GraphDefinition) -> None:
        if self.serializers_bound != graph._serializers_bound:
            raise StorageContractError("graph serializers changed during diagnostic capture; submit the fully bound graph again")

    def claim(self, *, generation: int = 0) -> None:
        with self.lock:
            if self.done or self.claimed:
                raise StorageContractError("diagnostic capture is no longer available for registration")
            self.claimed = True
            self.capture_generation = generation

    def discard(self, *, force: bool = False, gap: bool = False) -> None:
        with self.lock:
            if self.done or (self.claimed and not force):
                return
            self.done = True
            self.configurations = self.requested_settings = self.effective_settings = None
            self.layout = None
            self.steps = ()
            self.recorder.database._discard(self.recorder, self.reservation, gap=gap)
        self.recorder._forget(self)

    def handoff(self, context: ContextInstance, report: ContextReport) -> None:
        """Called before finalized readiness; bounded copying, no encoding/callbacks."""
        database = self.recorder.database
        with self.lock:
            if self.done:
                return
            finalized_at = datetime.now(timezone.utc)
            provenance = {"runtime_context_id": context.context_id, "generation": context.generation,
                "revision": context.status.revision, "recording_engine_id": self.recorder.engine_id,
                "execution_engine_id": context.engine_id, "authoritative_local": context.is_local,
                "capture_source": self.source, "captured_at": self.captured_at,
                "capture_generation": self.capture_generation,
                "graph_key": (context.graph_scope if isinstance(context.graph_scope, tuple)
                              and all(type(part) is str and len(part) <= 256 for part in context.graph_scope)
                              else None),
                "created_at": context.status.created_at, "finalized_at": finalized_at}
            header = (f"{context.context_id}:{context.generation}", report.state.value, finalized_at)
            evidence: object = ValueMarker("missing", "Final evidence capture unavailable")
            coverage = list(self.coverage)
            gap = self.gap
            try:
                allowance = min(database.limits.max_context_bytes, 2 * database.value_limits.max_bytes)
                if self.reservation.size + allowance > database.limits.batch_bytes:
                    raise PersistenceBackpressure("final capture would exceed one publication batch")
                database._reserve_detail(self.recorder, self.reservation, allowance)
                facts = _Facts(database, allowance)
                if len(report.executions) > database.value_limits.max_items:
                    raise PersistenceBackpressure("too many retained executions for diagnostic capture")
                for execution in report.executions if self.layout is not None else ():
                    if not 0 <= execution.step_index < len(self.steps):
                        raise StorageContractError("execution has no captured step correspondence")
                    index, kind, name, position, _ = self.steps[execution.step_index]
                    if (execution.step_kind, execution.step_name, execution.layout_position) != (kind, name, position):
                        raise StorageContractError("execution disagrees with the captured step correspondence")
                records, sequence = context._record_repository._history_snapshot(
                    max_items=database.value_limits.max_items,
                    max_bytes=database.value_limits.max_bytes,
                )
                evidence = {"schema": "jayrun.execution-history/1", "report": facts.copy(report),
                    "completed_iterations": context.completed_iterations,
                    "progress": facts.copy(context.progress), "timing": facts.copy(context._timing_evidence()),
                    "records": facts.copy(records),
                    "record_sequence": sequence, "records_complete": len(records) == sequence,
                    "step_correspondence": self.steps}
                if len(context._artifacts) > database.value_limits.max_items:
                    raise PersistenceBackpressure("too many retained artifact histories")
                artifacts = []
                registry = context.graph._specification.artifacts
                for artifact, result in context._artifacts.items():
                    artifacts.append(facts.copy({"artifact_id": registry.definition_for(artifact).artifact_id,
                        "history": result.history, "placement": _placement(result.data.placement)}))
                evidence["artifacts"] = tuple(artifacts)
                if not facts.complete:
                    coverage.append("Unsupported non-scalar diagnostic facts are explicitly marked; no live objects retained.")
                if len(records) != sequence:
                    coverage.append("Context records contain only live-policy-retained values; earlier records were pruned/unavailable.")
                coverage.extend(("Artifact payloads, checkpoints, exception tracebacks and placement leases are excluded.",
                    "Artifact transitions and attempt records are retained evidence, not a complete event timeline.",
                    "Resource teardown after context finalization belongs to engine-session cleanup, not this context.",
                    "Progress is the frozen final tracker snapshot; engine-owned timing learning is recorded independently."))
                if not context.is_local:
                    coverage.append("Remote shadow observation, not a locally authoritative execution; originating effective engine settings may be unavailable.")
                if self.capture_generation != context.generation:
                    coverage.append("Inputs were captured at an earlier ownership generation; remote mutations/effective settings are not reconstructed.")
                if report.started_at is None:
                    coverage.append("Execution did not start; captured settings were resolved but not exercised.")
            except Exception as error:
                evidence = ValueMarker("truncated", "Required final evidence exceeded limits or could not be detached")
                coverage.append(f"Required final evidence unavailable: {type(error).__name__}; execution outcome is unchanged.")
                gap = True
            try:
                # The closure owns detached facts only. In particular it cannot
                # retain context/report/graph or a live exception via its locals.
                self.recorder.database._defer_context(self.recorder, self.reservation,
                    lambda h=header, p=provenance, e=evidence, c=tuple(coverage), g=gap: self._build(h, p, e, c, g))
            except Exception as error:
                self.recorder.database._record_gap(self.recorder, error)
                self.recorder.database._discard(self.recorder, self.reservation)
            self.done = True
        self.recorder._forget(self)

    def _build(self, header: tuple[str, str, datetime], provenance: dict[str, object], evidence: object,
               coverage: tuple[str, ...], gap: bool) -> tuple[ContextHistoryEntry, bool]:
        database = self.recorder.database
        h = ContextHistoryHeader(self.recorder.session_id, header[0], self.graph_id, self.graph_version,
                                 header[1], header[2], layout_schema=self.layout.schema_version if self.layout else None)
        try:
            details = _encode(database, "evidence", evidence)
        except StorageContractError:
            details = _encode(database, "evidence", ValueMarker("truncated", "Required final evidence exceeds encoding limits"))
            coverage += ("Required final evidence encoding failed its bounded contract.",)
            gap = True
        origin = _encode(database, "provenance", provenance)
        entry = ContextHistoryEntry(h, self.configurations, self.requested_settings, self.effective_settings,
                                    origin, details, coverage, self.layout)
        if len(_context_body(entry)) > database.limits.max_context_bytes:
            entry = replace(entry, evidence=_encode(database, "evidence", ValueMarker("truncated", "Context body limit exceeded")),
                            coverage=coverage + ("Required final evidence omitted to preserve the essential outcome within the body limit.",))
            gap = True
        return entry, gap


class _HistoryRecorder:
    """One supervisor-owned capture lifetime, using the existing Database lane."""

    def __init__(self, database: Database, name: str, engine_id: str, on_failure=None) -> None:
        self.database = database
        self._on_failure = on_failure
        self.name = name
        self.engine_id = engine_id
        self.session_id = engine_id
        self._session: EngineSessionRecord | None = None
        self._session_reservation: _Reservation | None = None
        self._session_ready = False
        self._owned = False
        self._closing = False
        self._condition = threading.Condition()
        self._captures: set[_ContextCapture] = set()
        self._preparing = 0
        self._cache: _LayoutCache | None = None

    def open(self, settings: EngineSettings) -> None:
        _capture_caller()
        self._engine_settings = settings
        from .settings.engine import FailureMode
        future = self.database._begin_open(self, False,
            continue_on_failure=settings.failure_mode is FailureMode.CONTINUE,
            on_failure=self._on_failure)
        self._owned = True
        _wait(future, self.database.limits.close_timeout)
        reservation = self.database._reserve(self)
        if reservation is None:
            return
        try:
            header = EngineSessionHeader(self.session_id, datetime.now(timezone.utc), self.name, self.engine_id)
            values = self.database._capture_value(self, reservation, _engine_settings(settings), namespace="engine_settings")
            environment = self.database._capture_value(self, reservation, {"framework_version": __version__,
                "python": sys.version, "implementation": platform.python_implementation(), "platform": sys.platform}, namespace="environment")
            self._session = EngineSessionRecord(header, settings=values, environment=environment,
                coverage=("Context/session history and compatible engine-owned timing contributions are recorded independently.",))
            from ..persistence.backend import WriteBatch
            size = WriteBatch("0-" + "0" * 32, 1, sessions=(self._session,)).byte_size
            if size > reservation.size:
                self.database._reserve_detail(self, reservation, size - reservation.size)
            # Keep the startup snapshots charged while retained for shutdown.
            # The active lane's separate reservation covers its publication copy.
            self._session_reservation = self.database._reserve_cache(self, size)
            if self._session_reservation is None:
                raise PersistenceBackpressure("engine-session retention capacity unavailable")
            self.database._publish(self, reservation, sessions=(self._session,))
            try:
                _wait(self.database._barrier(), self.database.limits.close_timeout)
                self._session_ready = True
            except PersistenceError:
                if self.database._strict:
                    raise
        except PersistenceBackpressure as error:
            if self.database._strict:
                raise
            self.database._record_gap(self, error)
        finally:
            if reservation.active and not reservation.published:
                self.database._discard(self, reservation)
            if self._session_reservation is None:
                self._session = None

    def _forget(self, capture: _ContextCapture) -> None:
        with self._condition:
            self._captures.discard(capture)
            self._condition.notify_all()

    def prepare(self, submission: _NormalizedSubmission, settings: CombinedContextSettings,
                requested: ContextSettings | None, *, source: str = "submission") -> _ContextCapture | None:
        return self._prepare(submission.graph, submission.configs, settings, requested, source)

    def prepare_snapshot(self, snapshot: ContextSnapshot, graph_registry: GraphRegistry | None) -> _ContextCapture | None:
        from ..core.config.context import ConfigContext
        from .settings.combined_context import CombinedContextSettings
        from .submission import _normalize_configs
        if graph_registry is None:
            raise StorageContractError("snapshot capture requires a registered graph")
        graph = graph_registry[(snapshot.graph_key, snapshot.graph_version)]
        by_id = {definition.config_id: graph._specification.configs.source_for(definition)
                 for definition in graph._specification.configs.definitions}
        supplied = ConfigContext({by_id[key]: data.value for key, data in snapshot.config_context})
        resolved = _normalize_configs(supplied, graph._specification.configs)
        configs = ConfigContext._from_normalized(supplied, graph._specification.configs, resolved)
        # The receiver resolves its own supported effective execution settings;
        # the wire does not contain every originating engine setting.
        settings = CombinedContextSettings.from_settings(self._engine_settings, snapshot.context_settings,
                                                        graph._specification.artifacts)
        return self._prepare(graph, configs, settings, snapshot.context_settings, "accepted_snapshot")

    def _prepare(self, graph: GraphDefinition, configs: ConfigContext, settings: CombinedContextSettings,
                 requested: ContextSettings | None, source: str) -> _ContextCapture | None:
        _capture_caller()
        with self._condition:
            if self._closing:
                raise StorageContractError("engine history capture is closing")
            self._preparing += 1
        reservation: _Reservation | None = None
        capture: _ContextCapture | None = None
        try:
            # Optional cached layout reuse must not consume the last essential
            # admission slot. The cache has no authority and can be dropped.
            with self._condition:
                status = self.database.status
                if self._cache is not None and (status.pending_items >= self.database.limits.pending_items
                        or status.pending_bytes + self.database.limits.essential_bytes > self.database.limits.pending_bytes):
                    old, self._cache = self._cache, None
                    self.database._discard(self, old.reservation)
            reservation = self.database._reserve(self)
            if reservation is None:
                return None
            if not self._session_ready:
                self.database._discard(self, reservation, gap=True)
                return None
            capture = _ContextCapture(self, reservation, graph.graph_id, graph.version, source)
            capture.serializers_bound = graph._serializers_bound
            with self._condition:
                self._captures.add(capture)
            values = {}
            for definition in graph._specification.configs.definitions:
                field = graph._specification.configs.source_for(definition)
                data = configs.instances.get(field)
                values[definition.config_id] = {"name": definition.attribute_name,
                    "owner": definition.owner, "layout_position": definition.layout_position,
                    "value": data.value if data is not None else ValueMarker("missing", "Optional field is unresolved")}
            capture.configurations = self.database._capture_value(self, reservation, values, namespace="configurations", encoder=_encode_framework_value)
            capture.requested_settings = self.database._capture_value(self, reservation, _context_settings(requested, graph), namespace="requested_settings", encoder=_encode_framework_value)
            capture.effective_settings = self.database._capture_value(self, reservation, _context_settings(settings, graph), namespace="effective_settings", encoder=_encode_framework_value)
            try:
                capture.layout, capture.steps = self._get_layout(graph, reservation)
            except PersistenceBackpressure as error:
                if self.database._strict:
                    raise
                capture.gap = True
                capture.coverage += (f"Required layout unavailable at submission: {type(error).__name__}.",)
            # Validate identities and reserve the escaped body/header overhead now,
            # before creating runtime ownership. Later facts get their own budget.
            missing = _encode(self.database, "evidence", ValueMarker("missing", "Not finalized"))
            probe = ContextHistoryEntry(ContextHistoryHeader(self.session_id, "0:0", graph.graph_id, graph.version,
                "finished", capture.captured_at, layout_schema=capture.layout.schema_version if capture.layout else None),
                capture.configurations, capture.requested_settings, capture.effective_settings,
                missing, missing, capture.coverage, capture.layout)
            size = len(_context_body(probe))
            if size + 8192 > self.database.limits.max_context_bytes:
                raise PersistenceBackpressure("required submission diagnostics exceed the context body limit")
            required = size + (len(capture.layout.body) if capture.layout else 0) + 8192
            if required > self.database.limits.batch_bytes:
                raise PersistenceBackpressure("required submission diagnostics exceed one publication batch")
            if required > reservation.size:
                self.database._reserve_detail(self, reservation, required - reservation.size)
            with self._condition:
                if self._closing:
                    raise StorageContractError("engine stopped accepting prepared diagnostics")
            capture.check_binding(graph)
            return capture
        except PersistenceBackpressure as error:
            if capture is not None:
                capture.discard(force=True, gap=not self.database._strict)
            elif reservation is not None and reservation.active:
                self.database._discard(self, reservation, gap=not self.database._strict)
            if not self.database._strict:
                return None
            self.database._record_gap(self, error)
            raise
        except BaseException:
            if capture is not None:
                capture.discard(force=True)
            elif reservation is not None and reservation.active:
                self.database._discard(self, reservation)
            raise
        finally:
            with self._condition:
                self._preparing -= 1
                self._condition.notify_all()

    def _get_layout(self, graph: GraphDefinition, reservation: _Reservation) -> tuple[SerializedLayout, tuple[_StepCorrespondence, ...]]:
        with self._condition:
            cache = self._cache
            if cache is not None and cache.graph() is graph and cache.serializers_bound == graph._serializers_bound:
                self.database._reserve_detail(self, reservation, cache.reservation.size)
                return cache.layout, cache.steps
        ceiling = self.database.limits.layout_bytes
        self.database._reserve_detail(self, reservation, ceiling)
        try:
            layout, steps = _layout(graph)
            descriptor_bytes = sum(128 + 6 * len(row[2]) for row in steps)
            if len(layout.body) > ceiling:
                raise PersistenceBackpressure("required graph layout exceeds its configured byte limit")
            self.database._reserve_detail(self, reservation, descriptor_bytes)
        except BaseException:
            self.database._release_detail(self, reservation, ceiling)
            raise
        self.database._release_detail(self, reservation, ceiling - len(layout.body))
        # Only one reusable detached variant per engine, never a graph-ID cache.
        # Every byte is charged independently of context reservations.
        with self._condition:
            old, self._cache = self._cache, None
            if old is not None:
                self.database._discard(self, old.reservation)
            charge = len(layout.body) + sum(128 + 6 * len(row[2]) for row in steps)
            cache_reservation = self.database._reserve_cache(self, charge)
            if cache_reservation is not None:
                self._cache = _LayoutCache(weakref.ref(graph), graph._serializers_bound, layout, steps, cache_reservation)
        return layout, steps

    def close(self, *, failure: BaseException | None, cleanup_failures: tuple[BaseException, ...]) -> None:
        if not self._owned:
            return
        if self.database._owner is not self:
            # A rejected acquisition may already have closed its own lane.
            self._owned = False
            self._session = None
            self._session_reservation = None
            return
        deadline = time.monotonic() + self.database.limits.close_timeout
        failures: list[BaseException] = []
        with self._condition:
            self._closing = True
            while self._preparing and time.monotonic() < deadline:
                self._condition.wait(max(0, deadline - time.monotonic()))
            preparing = self._preparing
            captures = tuple(self._captures) if not preparing else ()
            cache, self._cache = self._cache, None
        if cache is not None and cache.reservation.active:
            self.database._discard(self, cache.reservation)
        for capture in captures:
            capture.discard(force=True, gap=capture.claimed)
        try:
            if preparing:
                raise PersistenceTimeout("diagnostic capture is still settling; Database retains its reservation/handle ownership")
            self.database._drain_profiles()
            _wait(self.database._barrier(report_failure=False), max(0, deadline - time.monotonic()))
            if self._session is not None and self.database._owner is self:
                reservation, self._session_reservation = self._session_reservation, None
                if reservation is not None and reservation.active:
                    try:
                        status = self.database.status
                        facts = _Facts(self.database, self.database.value_limits.max_bytes)
                        shutdown = self.database._capture_value(self, reservation, {
                            "runtime_result": "failed" if failure is not None or cleanup_failures else "stopped",
                            "runtime_failure": facts.copy(failure), "runtime_cleanup_failures": facts.copy(cleanup_failures),
                            "persistence_drain": "complete" if status.first_failed is None else "failed",
                            "failed_handoffs": status.failed, "capture_gaps": status.capture_gaps,
                            "first_failed": status.first_failed, "close": "not_yet_attempted",
                        }, namespace="shutdown")
                        final = replace(self._session, header=replace(self._session.header, shutdown_at=datetime.now(timezone.utc)), shutdown=shutdown)
                        from ..persistence.backend import WriteBatch
                        size = WriteBatch("0-" + "0" * 32, 1, sessions=(final,)).byte_size
                        if size > reservation.size:
                            self.database._reserve_detail(self, reservation, size - reservation.size)
                        self.database._publish(self, reservation, sessions=(final,))
                    finally:
                        if reservation.active and not reservation.published:
                            self.database._discard(self, reservation, gap=True)
        except BaseException as error:
            failures.append(error)
            if self.database._owner is self:
                self.database._record_gap(self, error)
        finally:
            if self._session_reservation is not None and self._session_reservation.active:
                self.database._discard(self, self._session_reservation, gap=True)
                self._session_reservation = None
            self._session = None
            if self.database._owner is self:
                future = self.database._begin_close(self, allow_closed=True)
                try:
                    _wait(future, max(0, deadline - time.monotonic()))
                except BaseException as error:
                    failures.append(error)
                if future.done() and self.database._thread is not None:
                    self.database._thread.join(max(0, deadline - time.monotonic()))
            self._owned = self.database._owner is self
        if failures and self.database._strict:
            raise BaseExceptionGroup("engine persistence cleanup failed", failures)
