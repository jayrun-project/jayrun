"""Bounded detached dashboard evidence from public run and snapshot interfaces."""
from dataclasses import fields, is_dataclass
from enum import Enum
import math
import json
from datetime import datetime
from itertools import islice



MAX_RECORDS = 2048
MAX_TEXT = 4096
SECRET_WORDS = ('password', 'secret', 'token', 'credential', 'private_key', 'api_key')


def safe(value, *, key='', depth=0, budget=None):
    """JSON-safe display; never call an arbitrary object's repr or serializer."""
    if budget is None: budget = [1024]
    budget[0] -= 1
    if budget[0] < 0: return {'availability':'omitted','reason':'structured value budget'}
    if any(word in key.lower() for word in SECRET_WORDS):
        return {'availability': 'redacted'}
    if depth > 6:
        return {'availability': 'omitted', 'reason': 'display depth limit'}
    if type(value) is int and value.bit_length()>13000:
        return {'availability':'omitted','reason':'integer exceeds bounded decimal display'}
    if value is None or type(value) in (bool, int):
        return str(value) if type(value) is int and abs(value) > 2**53-1 else value
    if type(value) is float:
        return value if math.isfinite(value) else {'availability': 'unsupported', 'type': 'nonfinite float'}
    if type(value) is str:
        return value if len(value) <= MAX_TEXT else {'availability': 'omitted', 'reason': 'text limit', 'prefix': value[:MAX_TEXT]}
    if isinstance(value, Enum):
        return safe(value.value, depth=depth+1, budget=budget)
    if type(value) in (list, tuple):
        return [safe(v, depth=depth+1, budget=budget) for v in value[:128]] + ([{'availability': 'omitted', 'count': len(value)-128}] if len(value)>128 else [])
    from types import MappingProxyType
    if type(value) in (dict, MappingProxyType):
        from itertools import islice
        pairs=list(islice(value.items(),128))
        result={k:safe(v,key=k,depth=depth+1,budget=budget) for k,v in pairs if type(k) is str and len(k)<=MAX_TEXT}
        if len(result)<len(value): result['[display omissions]']=len(value)-len(result)
        return result
    return {'availability':'unsupported', 'type':type(value).__name__}


def record_value(record):
    value=safe(record.value,key=record.key)
    if len(json.dumps(value).encode())>16384:
        value={'availability':'omitted','reason':'record exceeds 16 KiB display limit'}
    return {'key':record.key,'sequence':str(record.sequence),'value':value,
            'value_type':type(record.value).__name__,
            'numeric':type(record.value) in (int,float) and not isinstance(value,dict),
            'iteration':record.iteration,'step_index':record.step_index,'execution':record.execution,'attempt':record.attempt,'generation':record.generation,'recorded_at':record.recorded_at.isoformat()}


def configuration(snapshot, graph=None):
    submitted=dict(snapshot.config_context)
    definitions=() if graph is None else graph.inspect.configs
    output=[]
    for definition in definitions[:128]:
        present=definition.config_id in submitted
        output.append({'id':str(definition.config_id),'owner':definition.owner,
                       'position':list(definition.layout_position),'name':definition.attribute_name,
                       'description':definition.description,'type':getattr(definition.value_type,'__name__','unknown'),
                       'submitted':safe(submitted[definition.config_id].value,key=definition.attribute_name) if present else {'availability':'not submitted'},
                       'declared_default':safe(definition.default,key=definition.attribute_name),
                       'provenance':'Declaration captured at dashboard acquisition; submitted values from context snapshot.',
                       'effective':{'availability':'unknown','reason':'Effective/default provenance is not recorded in the public snapshot.'}})
    if not output:
        output=[{'id':str(k),'owner':'Unknown','submitted':{'availability':'redacted','reason':'Declaration unavailable; cannot identify sensitive keys'},'provenance':'Submitted snapshot; declaration unavailable.'} for k,v in islice(submitted.items(),128)]
    return output


def settings(snapshot):
    result={}
    for field in fields(snapshot.context_settings):
        value=getattr(snapshot.context_settings,field.name)
        if is_dataclass(value):
            value={f.name:safe(getattr(value,f.name),key=f.name) for f in fields(value)}
        result[field.name]=safe(value,key=field.name)
    return {'values':result,'provenance':'Captured effective portable ContextSettings.',
            'gap':'Requested settings and engine-level effective placement/execution/failure policy are not exposed here.'}


def _artifact_history_availability(*, retained: bool, finalized: bool,
                                   declared_count: int | None = None) -> str:
    """Describe evidence, not an expectation inferred from empty live results.

    Only an actual graph declaration (or its validated retained layout) can
    establish that artifact history does not apply. A missing ArtifactContext
    says nothing about artifacts produced inside a zero-input graph.
    """
    if retained:
        return 'Retained artifact metadata and lifecycle entries.'
    if declared_count == 0:
        return 'Not applicable: this graph declares no artifacts.'
    if finalized:
        return ('No retained artifact lifecycle evidence was captured. '
                'Earlier or pruned coverage is unknown.')
    return ('Live artifact history is not exposed in this public snapshot. '
            'Finalized entries are shown only if retained and captured.')


def detached(snapshot, graph=None, *, declared_artifact_count: int | None = None):
    retained=records(snapshot.records)
    if graph is not None:
        declared_artifact_count = len(graph.artifacts)
    return {'context_id':str(snapshot.context_id), 'evidence_sampled_at':snapshot.progress.observed_at.isoformat(), 'configuration':configuration(snapshot,graph),
            'settings':settings(snapshot),'records':retained,
            'records_omitted':max(0,len(snapshot.records)-len(retained)),
            'records_complete':snapshot.records_complete, 'display_complete':len(retained)==len(snapshot.records) and all(not isinstance(r['value'],dict) or 'availability' not in r['value'] for r in retained),'record_sequence':str(snapshot.record_sequence),
            'artifacts':[{'id':str(k),'history':[dict(_record(h),retained_index=i+1) for i,h in enumerate(v.history[:256])],
                          'payload':'Not collected by dashboard', 'history_omitted':max(0,len(v.history)-256), 'coverage':'Retained lifecycle order; completeness unknown.'}
                         for k,v in snapshot.artifacts[:256]],
            'artifacts_omitted':max(0,len(snapshot.artifacts)-256),
            'artifact_history_policy': 'Only recorded entries are available. PRODUCTION and PERFORMANCE retain the latest artifact lifecycle entry; DEBUG retains the recorded sequence. The public snapshot does not identify the recording mode. Missing earlier entries cannot be reconstructed.',
            'artifact_history_availability':_artifact_history_availability(
                retained=bool(snapshot.artifacts), finalized=snapshot.finalized,
                declared_count=declared_artifact_count),
            'activity':[_record(h) for h in snapshot.history[-256:]],
            'activity_omitted':max(0,len(snapshot.history)-256),'failure':_failure(snapshot.failure),
            'access':{'observes':'Unknown','controls':'Unknown','scope':'Public granted-access metadata unavailable'},
            'report':None,'report_availability':'Finalized formatter unavailable until a finalized run handle is acquired.'}


def terminal_evidence(snapshot):
    """Detach terminal report fields without accessing ArtifactResult.data/value."""
    if not snapshot.finalized or snapshot.report is None:
        return None
    report = snapshot.report
    retained = records(snapshot.records)
    executions = []
    remaining = [1024]
    def attempt_records(values):
        count=min(len(values),64,remaining[0]);remaining[0]-=count
        return [_record(value) for value in values[:count]],len(values)-count
    for index, session in enumerate(report.executions[:256]):
        executions.append({
            'id': 'session-'+str(index), 'step_index': session.step_index,
            'kind': session.step_kind, 'name': safe(session.step_name),
            'layout_position': list(session.layout_position), 'iteration': session.iteration,
            'outcome': session.outcome.value, 'skip_reason': safe(session.skip_reason),
            'active_seconds': session.duration_seconds, 'execution_count': session.execution_count,
            'attempts': [{'execution': a.execution, 'attempt': a.attempt,
                          'records': (copied:=attempt_records(a.records))[0],
                          'records_omitted': copied[1]}
                         for a in session.attempts[:64]],
            'attempts_omitted': max(0, len(session.attempts)-64),
        })
    return {
        'context_id': str(snapshot.context_id), 'graph_key': snapshot.graph_key,
        'graph_version': snapshot.graph_version, 'engine_id': snapshot.engine_id,
        'generation': snapshot.generation, 'revision': snapshot.revision,
        'report_revision': report.revision, 'outcome': report.state.value,
        'stop_requested': report.stop_requested,
        'iteration_count': report.iteration_count, 'completed_iterations': snapshot.completed_iterations,
        'created_at': report.created_at.isoformat(), 'finished_at': report.finished_at.isoformat(),
        'elapsed_wall_seconds': (report.finished_at-report.created_at).total_seconds(),
        'failure': _failure(report.failure),
        'failed_step': None if report.failed_step is None else _record(report.failed_step),
        'executions': executions,
        'artifacts': [{'id':'artifact-'+str(key), 'availability':'Not collected by dashboard',
                       'history':[dict(_record(h),retained_index=i+1) for i,h in enumerate(value.history[:256])],
                       'history_omitted':max(0,len(value.history)-256),
                       'history_coverage':'Recorded lifecycle order; completeness unknown'}
                      for key,value in snapshot.artifacts[:256]],
        'records':retained,
        'connections': [], 'history':[_record(h) for h in report.history[-256:]],
        'coverage': {'artifact_values':'Not collected by dashboard',
                     'context_records':'complete' if snapshot.records_complete and len(retained)==len(snapshot.records) else 'missing/pruned/display-limited',
                     'committed_record_sequence':str(snapshot.record_sequence),
                     'executions_omitted':max(0,len(report.executions)-256),
                     'artifacts_omitted':max(0,len(snapshot.artifacts)-256),
                     'records_omitted':max(0,len(snapshot.records)-len(retained)),
                     'history_omitted':max(0,len(report.history)-256),
                     'connections':'Exact finalized connection correspondence unavailable without a temporary finalized run.',
                     'timing':'Recorded durations only; no fabricated timeline'},
    }


def _failure(error):
    if error is None: return None
    return {'type':type(error).__name__, 'arguments':safe(BaseException.args.__get__(error))}


def _record(record):
    result = {'type':type(record).__name__}
    for field in fields(record):
        value = getattr(record,field.name)
        result[field.name] = (_failure(value) if isinstance(value,BaseException) else
                              value.isoformat() if isinstance(value,datetime) else safe(value))
    return result


def records(retained):
    result=[]; remaining=128*1024
    for record in retained[-MAX_RECORDS:]:
        value=record_value(record)
        size=len(json.dumps(value).encode())
        if size>remaining:
            value['value']={'availability':'omitted','reason':'128 KiB record display budget'}
            value['numeric']=False
            size=len(json.dumps(value).encode())
        if size>remaining: break
        result.append(value); remaining-=size
    return result


def progress_view(progress, graph):
    """Map authoritative public step progress onto captured declaration positions."""
    nodes=[]
    for node in graph['nodes']:
        if node['kind'] != 'operator':continue
        position=node['identity'].get('Core layout position')
        steps=[step for step in progress.steps if list(step.layout_position)==position]
        states={step.state.value for step in steps}
        state=next((s for s in ('failed','cancelled','running','placement_waiting') if s in states),None)
        if state is None:
            state=('skipped' if states=={'skipped'} else 'completed') if states and states<={'completed','skipped'} else 'pending'
        nodes.append({'id':node['id'],'state':state,'elapsed_seconds':sum(s.elapsed_seconds for s in steps),
                      'steps':[{'index':s.step_index,'kind':s.step_kind,'name':s.step_name,
                                'state':s.state.value,'iteration':s.iteration,'execution_count':s.execution_count,
                                'elapsed_seconds':s.elapsed_seconds,'estimated_seconds':s.estimated_seconds} for s in steps]})
    return {'graph_id':graph['id'],'context_id':str(progress.context_id),'revision':progress.revision,
            'observed_at':progress.observed_at.isoformat(),'state':progress.context_state.value,
            'iteration':progress.iteration,'max_iterations':progress.max_iterations,
            'elapsed_seconds':progress.elapsed_seconds,'estimated_fraction':progress.estimated_fraction,
            'estimated_remaining_seconds':progress.estimated_remaining_seconds,'confidence':progress.confidence,
            'sample_count':progress.sample_count,'completed_steps':progress.completed_steps,
            'total_steps':len(progress.steps),'nodes':nodes}


def declaration_bindings(graph, definition):
    """Detach existing compiled declaration correspondence, never execution claims."""
    from ..core.graph.compiled_graph import CompiledOperatorStep, CompiledResourceStep
    from ..core.validation.graph import OperatorNode
    if not graph.inspect.complete:return {'steps':{},'connections':[]}
    steps=graph._compiled_graph.steps
    nodes={tuple(n['identity']['Core layout position']):n for n in definition['nodes'] if n['kind']=='operator'}
    targets={}
    compiled={}
    for index,step in enumerate(steps):
        node=nodes.get(step.layout_position)
        if node is None:continue
        if isinstance(step,CompiledOperatorStep):
            compiled[step.layout_position]=(index,step)
            subject=node;kind='operator';name=step.operator_name
        elif isinstance(step,CompiledResourceStep):
            markers=[m for m in node['resources'] if m['details']['Field']==step.resource_field.attribute_name]
            if len(markers)!=1:continue
            subject=markers[0];kind='resource';name=step.resource_name
        else:continue
        targets[str(index)]={'id':subject['id'],'kind':kind,'name':safe(name),'layout_position':list(step.layout_position)}
    validation=graph.validate()
    operators={n.node_id:n for n in validation.nodes if isinstance(n,OperatorNode)}
    artifacts={artifact:index for index,artifact in enumerate(graph.artifacts)}
    connections=[]
    for edge in validation.edges:
        producer=compiled.get(operators[edge.source].layout_position) if edge.source in operators else None
        consumer=compiled.get(operators[edge.target].layout_position) if edge.target in operators else None
        verified=producer is not None and any(f.artifact is edge.artifact for f in producer[1].output_fields)
        connections.append({'id':'edge-'+str(edge.edge_id),'artifact_id':'artifact-'+str(artifacts[edge.artifact]),
                            'producer_step':None if producer is None else producer[0],
                            'verified_output':verified,'consumer_step':None if consumer is None else consumer[0]})
    return {'steps':targets,'connections':connections}


def correspond(evidence, bindings):
    """Reference only recorded entries through captured declaration identities."""
    artifacts={a['id']:a for a in evidence['artifacts']}
    for connection in bindings['connections']:
        artifact=artifacts.get(connection['artifact_id'])
        if artifact is None:continue
        evidence['connections'].append({k:v for k,v in connection.items() if k!='verified_output'} | {
            'producer_history_indices':[h['retained_index'] for h in artifact['history']
                if connection['verified_output'] and h.get('actor')=='operator' and h.get('step_index')==connection['producer_step']],
            'consumer_sessions':[s['id'] for s in evidence['executions'] if connection['consumer_step'] is not None and s['step_index']==connection['consumer_step']],
            'coverage':'Verified producer-output identity and recorded entries only. No value continuity across discrete segments or consumer lifecycle attribution is inferred.'})
    if bindings['connections']:
        evidence['coverage']['connections']='Captured declaration correspondence; retained entries only, omissions and unassigned lifecycle events remain explicit.'
