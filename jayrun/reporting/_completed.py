"""One bounded mapping of finalized public evidence for text and plots.

This module owns presentation only. It never reads live managers or payloads,
changes runtime state, or turns absence of a record into a successful outcome.
"""
from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
import json
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING
from collections.abc import Callable

from ..visualization.contract import MAX_EXPORT_BYTES, summarize

if TYPE_CHECKING:
    from ..engine.context_run import ContextRun
    from ..engine.recorders.context.report import ContextReport
    from ..engine.snapshot import ContextSnapshot
    from ..engine.artifact.result import ArtifactResult
    from ..engine.interfaces.context_record import ContextRecord
    from ..core.graph.graph_definition import GraphDefinition

MAX_EVIDENCE_ITEMS = 50000


def _safe(value: object) -> object:
    # ContextRecord guarantees immutable mapping proxies with string keys.
    # Convert only its bounded branches, not arbitrary Mapping implementations.
    if type(value) is MappingProxyType:
        value = dict(value)
    if type(value) in (dict, tuple, list):
        return _safe_container(value)
    return summarize(value)


def _safe_container(value: dict | tuple | list, depth: int = 0) -> object:
    if depth >= 6:
        return '[depth limit; detail omitted]'
    if isinstance(value, dict):
        converted = {}
        for key, child in list(value.items())[:64]:
            if type(child) is MappingProxyType:
                child = dict(child)
            converted[key] = _safe_container(child, depth + 1) if type(child) in (dict, tuple, list) else summarize(child)
        if len(value) > 64:
            converted['[omitted]'] = f'{len(value)-64} further fields'
        return summarize(converted)
    result = []
    for child in value[:64]:
        if type(child) is MappingProxyType:
            child = dict(child)
        result.append(_safe_container(child, depth + 1) if type(child) in (dict, tuple, list) else summarize(child))
    if len(value) > 64:
        result.append(f'[{len(value)-64} further items omitted]')
    return result


def _failure(error: BaseException | None) -> object:
    if error is None:
        return None
    # Avoid arbitrary exception __str__/repr implementations and traceback locals.
    return {'type': type(error).__name__, 'arguments': _safe(BaseException.args.__get__(error))}


def _record(record: object) -> dict:
    result = {'type': type(record).__name__}
    for field in fields(record):
        value = getattr(record, field.name)
        result[field.name] = (_failure(value) if isinstance(value, BaseException)
                              else value.value if isinstance(value, Enum)
                              else value.isoformat() if isinstance(value, datetime) else _safe(value))
    return result


def completed_evidence(run: ContextRun) -> dict:
    """Detach finalized evidence; all identities remain explicit and lossless."""
    return _completed_evidence(run.snapshot(), run.graph, run.artifact, run.records)


def _completed_evidence(
    snapshot: ContextSnapshot,
    graph: GraphDefinition,
    artifact: Callable[[int], ArtifactResult],
    read_records: Callable[[str], tuple[ContextRecord, ...]],
) -> dict:
    """Share one evidence conversion without retaining an observing/control handle."""
    from ..engine.context_run import ContextNotTerminatedError

    if not snapshot.finalized:
        raise ContextNotTerminatedError(f'context {snapshot.context_id!r} has not terminated')
    report = snapshot.report
    if report is None:
        raise ValueError('finalized context has no terminal report')
    sessions = report.executions
    count = (len(sessions) + len(snapshot.records) + len(report.history)
             + sum(len(s.attempts) + sum(len(a.records) for a in s.attempts) for s in sessions)
             + sum(len(result.history) for _, result in snapshot.artifacts))
    if count > MAX_EVIDENCE_ITEMS:
        raise ValueError(f'completed evidence exceeds {MAX_EVIDENCE_ITEMS} items; nothing exported')
    executions = []
    for index, session in enumerate(sessions):
        if session.context_id != snapshot.context_id:
            raise ValueError('execution report belongs to a different context')
        executions.append({
            'id': f'session-{index}', 'step_index': session.step_index,
            'kind': session.step_kind, 'name': summarize(session.step_name),
            'layout_position': list(session.layout_position), 'iteration': session.iteration,
            'outcome': session.outcome.value, 'skip_reason': summarize(session.skip_reason),
            'active_seconds': session.duration_seconds, 'execution_count': session.execution_count,
            'attempts': [{'execution': a.execution, 'attempt': a.attempt,
                          'records': [_record(r) for r in a.records]} for a in session.attempts],
        })
    artifacts = []
    for definition in graph.inspect.artifacts:
        try:
            result = artifact(definition.artifact_id)
        except KeyError:
            history, availability = [], 'not recorded'
            history_coverage = 'not recorded at finalized owner; earlier history unknown'
        else:
            history = [dict(_record(r), retained_index=i) for i, r in enumerate(result.history, 1)]
            history_coverage = ('retained entries only; pruning and prior-owner completeness unknown' if history
                                else 'empty retained tuple; complete empty history is not established')
            last = result.history[-1].state.value if result.history else None
            availability = {'cleared': 'not retained', 'unregistered': 'unknown: never registered',
                            'registered': 'registered; payload excluded',
                            'updated': 'registered; payload excluded'}.get(last, 'unknown')
        artifacts.append({'id': f'artifact-{definition.artifact_id}',
                          'name': summarize(definition.name), 'role': definition.role.value,
                          'exit': definition.is_exit, 'availability': availability,
                          'history': history, 'history_coverage': history_coverage})
    # Snapshot supplies retained keys through the public contract. Read actual
    # values through records(key), never through private key enumeration.
    retained = []
    for key in dict.fromkeys(r.key for r in snapshot.records):
        retained.extend(read_records(key))
    retained.sort(key=lambda r: r.sequence)
    if tuple(retained) != snapshot.records:
        raise ValueError('retained records changed after finalized snapshot')
    records = [{'id': f'{r.context_id}:{r.sequence}', 'sequence': str(r.sequence),
                'key': r.key, 'value': _safe({r.key: r.value})[r.key] if len(r.key) <= 256 else '[long-key value omitted]',
                'iteration': r.iteration, 'step_index': r.step_index,
                'execution': r.execution, 'attempt': r.attempt, 'generation': r.generation,
                'recorded_at': r.recorded_at.isoformat()} for r in retained]
    data = {
        'context_id': str(snapshot.context_id), 'graph_key': snapshot.graph_key,
        'graph_version': snapshot.graph_version, 'engine_id': snapshot.engine_id,
        'generation': snapshot.generation, 'revision': snapshot.revision, 'report_revision': report.revision,
        'outcome': report.state.value, 'iteration_count': report.iteration_count,
        'completed_iterations': snapshot.completed_iterations, 'stop_requested': report.stop_requested,
        'created_at': report.created_at.isoformat(), 'finished_at': report.finished_at.isoformat(),
        'elapsed_wall_seconds': (report.finished_at - report.created_at).total_seconds(),
        'failure': _failure(report.failure),
        'failed_step': None if report.failed_step is None else _record(report.failed_step),
        'executions': executions, 'artifacts': artifacts, 'records': records,
        'connections': _connection_history(graph, artifacts, executions),
        'history': [_record(h) for h in report.history],
        'coverage': {
            'context_records': 'complete retained history' if snapshot.records_complete else 'incomplete: records pruned or unavailable',
            'committed_record_sequence': str(snapshot.record_sequence), 'retained_record_count': len(retained),
            'artifact_history': 'available transitions only; recorder mode/prior-owner history may omit earlier transitions',
            'artifact_identity': 'retained_index is local tuple order, not a core sequence; no artifact timestamps, consumer events, attempt identity or global chronology recorded',
            'artifact_values': 'excluded; artifact None cannot establish recorded None or non-production',
            'attempt_records': 'only emitted logs/metrics/timers/failures; empty records do not prove none occurred',
            'resource_operations': 'resource step sessions only; setup versus cache reuse, contention and teardown not individually recorded',
            'timing': 'active session durations exclude placement waits; wall interval is submission to terminal state, not cleanup completion; no attempt timestamps or accurate timeline',
            'stdout': 'not captured; free-text labels/logs/exceptions are not a credential detector',
        },
    }
    data.update(submission_evidence(snapshot, graph))
    _encode(data)
    return data


def submission_evidence(snapshot, graph=None) -> dict:
    """Safe submitted configuration and effective portable settings, no payloads.

    A declaration default is not proof of an effective runtime value. Detached
    dashboards can reuse their earlier captured configuration when graph access
    has expired. Framework snapshots and ContextReport are not changed.
    """
    submitted = dict(snapshot.config_context)
    definitions = () if graph is None else graph.inspect.configs
    configuration = []
    for definition in definitions[:128]:
        name = definition.attribute_name
        present = definition.config_id in submitted
        configuration.append({'id': str(definition.config_id), 'owner': definition.owner,
            'position': list(definition.layout_position), 'name': name,
            'description': summarize(definition.description), 'type': summarize(definition.value_type),
            'submitted': next(iter(_safe({name: submitted[definition.config_id].value}).values())) if present else {'availability':'not submitted'},
            'declared_default': next(iter(_safe({name: definition.default}).values())),
            'effective': {'availability':'unknown', 'reason':'Effective/default provenance is not recorded in the public snapshot.'},
            'provenance':'Submitted snapshot values; current graph declaration defaults.'})
    if graph is None:
        configuration = [{'id': str(key), 'submitted': {'availability':'redacted',
            'reason':'Declaration unavailable; cannot identify sensitive keys'}} for key in list(submitted)[:128]]
    def setting(value):
        if isinstance(value, Enum): return value.value
        if is_dataclass(value) and type(value).__module__.startswith('jayrun.engine.settings.'):
            return {f.name: setting(getattr(value, f.name)) for f in fields(value)}
        return _safe(value)
    return {'configuration': configuration,
        'configuration_omitted': max(0, len(definitions if graph is not None else submitted)-128),
        'settings': {'values': setting(snapshot.context_settings),
            'provenance':'Captured effective portable ContextSettings.',
            'gap':'Requested settings and engine-level effective placement/execution/failure policy are not exposed here.'}}


def _connection_history(graph: GraphDefinition, artifacts: list[dict], executions: list[dict]) -> list[dict]:
    """Reference recorded producer updates, never infer lifecycle from a wire.

    Consumption cleanup has no consuming step identity in ArtifactRecord. Keep
    those events in artifact history; do not distribute them among connections.
    A target's output update describes its outgoing value, not its incoming wire.
    """
    from ..core.graph.compiled_graph import CompiledOperatorStep
    from ..core.validation.graph import OperatorNode

    validation = graph.validate()
    steps = graph._compiled_graph.steps if executions else ()
    operators = {node.node_id: node for node in validation.nodes if isinstance(node, OperatorNode)}
    compiled = {step.layout_position: (index, step) for index, step in enumerate(steps)
                if isinstance(step, CompiledOperatorStep)}
    definitions = {artifact: index for index, artifact in enumerate(graph.artifacts)}
    results = {artifact['id']: artifact for artifact in artifacts}
    connections = []
    for edge in validation.edges:
        aid = f'artifact-{definitions[edge.artifact]}'
        producer = compiled.get(operators[edge.source].layout_position) if edge.source in operators else None
        consumer = compiled.get(operators[edge.target].layout_position) if edge.target in operators else None
        refs = []
        if producer is not None and any(field.artifact is edge.artifact for field in producer[1].output_fields):
            refs = [record['retained_index'] for record in results[aid]['history']
                    if record['actor']=='operator' and record['step_index']==producer[0]]
        connections.append({'id': f'edge-{edge.edge_id}', 'artifact_id': aid,
                            'producer_step': None if producer is None else producer[0],
                            'consumer_step': None if consumer is None else consumer[0],
                            'producer_history_indices': refs,
                            'consumer_sessions': [s['id'] for s in executions if consumer and s['step_index']==consumer[0]],
                            'coverage': 'Only recorded updates at this verified producer output are attributed. Entry, internal cleanup and consumer lifecycle events lack exact connection attribution; see artifact history. No value continuity across discrete segments is inferred.'})
    return connections


def _encode(data: dict) -> str:
    encoded = json.dumps(data, ensure_ascii=True, allow_nan=False)
    if len(encoded.encode()) > MAX_EXPORT_BYTES:
        raise ValueError('completed evidence exceeds export byte limit; nothing exported')
    return encoded


def _text_tree(value: object, indent: str = '') -> list[str]:
    if isinstance(value, dict):
        lines = []
        for key, child in value.items():
            label = json.dumps(key, ensure_ascii=True)
            if isinstance(child, (list, dict)):
                lines.append(f'{indent}{label}:')
                lines.extend(_text_tree(child, indent + '  '))
            else:
                lines.append(f'{indent}{label}: {json.dumps(child, ensure_ascii=True)}')
        return lines or [indent + '(no retained fields)']
    if isinstance(value, list):
        lines = []
        for index, child in enumerate(value, 1):
            lines.append(f'{indent}[{index}]')
            lines.extend(_text_tree(child, indent + '  '))
        return lines or [indent + '(no retained entries)']
    return [indent + json.dumps(value, ensure_ascii=True)]


class _RunReporter:
    """The ContextRun formatter; immutable aggregate evidence is available as data.

    data is the original immutable ContextReport, never a forwarding proxy.
    Formatting and plotting consume completed_evidence without separate logic.
    """
    def __init__(self, run: ContextRun) -> None:
        # A separately retained formatter deliberately owns the evidence context,
        # not its parent ContextRun or that handle's observation/control services.
        # The run can cache this formatter without a run -> formatter -> run cycle.
        self._context = run._context

    @property
    def _evidence(self) -> dict:
        context = self._context
        return _completed_evidence(context.snapshot, context.graph,
                                   context._artifact_result,
                                   context._record_repository.records)

    @property
    def data(self) -> ContextReport:
        from ..engine.context_run import ContextNotTerminatedError

        if not self._context.finalized:
            raise ContextNotTerminatedError(
                f'context {self._context.context_id!r} has not terminated')
        return self._context._report_value()

    def __str__(self) -> str:
        return self.format()

    def format(self, *, compact: bool = False) -> str:
        if type(compact) is not bool:
            raise TypeError('compact must be a bool')
        data = self._evidence
        return _format_evidence(data, compact=compact)

    def print(self, *, compact: bool = False) -> None:
        print(self.format(compact=compact))

    def save(self, path: str | Path = 'run.txt', *, compact: bool = False) -> Path:
        text = self.format(compact=compact)
        output = Path(path).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + '\n', encoding='utf-8')
        return output


def _format_evidence(data: dict, *, compact: bool = False) -> str:
    """Format the shared detached schema without retaining its source run."""
    lines = [f"Completed run | context={data['context_id']} | {data['outcome'].upper()}",
             f"Graph: {data['graph_key']!r} v{data['graph_version']}",
             f"Iterations: {data['completed_iterations']} completed / {data['iteration_count']} started",
             "Stop accepted: " + {True: "yes", False: "no", None: "unknown (not captured)"}[data.get('stop_requested')],
             f"Elapsed wall seconds: {data['elapsed_wall_seconds']}",
             'IDENTITY', *_text_tree({key:data[key] for key in ('context_id','graph_key','graph_version','engine_id','generation','revision','report_revision')}),
             'FAILED STEP', *_text_tree(data['failed_step']),
             'COVERAGE', *_text_tree(data['coverage']),
             'FAILURE', *_text_tree(data['failure'])]
    lines.extend(['CONFIGURATION', *_text_tree(data.get('configuration', {'availability':'not captured'})),
                  'Configuration entries omitted: '+str(data.get('configuration_omitted', 'unknown')),
                  'SETTINGS', *_text_tree(data.get('settings', {'availability':'not captured'}))])
    for title, rows in [('OPERATOR SESSIONS', [x for x in data['executions'] if x['kind']=='operator']),
                        ('RESOURCE SESSIONS', [x for x in data['executions'] if x['kind']=='resource']),
                        ('ARTIFACT HISTORY', data['artifacts']), ('CONNECTION HISTORY REFERENCES', data['connections']), ('CONTEXT RECORDS', data['records']),
                        ('LIFECYCLE HISTORY', data['history'])]:
        lines.append(title)
        for row in rows:
            item = dict(row)
            if compact:
                if 'attempts' in item:
                    item['attempts'] = [{'execution': a['execution'], 'attempt': a['attempt'],
                                         'records': f"[{len(a['records'])} records omitted]"} for a in item['attempts']]
                for field in ('value', 'history'):
                    if field in item:
                        value = item[field]
                        item[field] = f'[detail omitted; {len(value)} entries]' if isinstance(value, list) else '[value omitted]'
            lines.extend(_text_tree(item))
            lines.append('')
        if not rows:
            lines.append('No retained evidence')
    result = '\n'.join(lines)
    if len(result.encode()) > MAX_EXPORT_BYTES:
        raise ValueError('text report exceeds export byte limit')
    return result
