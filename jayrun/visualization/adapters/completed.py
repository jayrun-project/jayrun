"""Attach finalized evidence to the one declaration renderer."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ...reporting._completed import completed_evidence
from ...core.graph.compiled_graph import CompiledOperatorStep, CompiledResourceStep
from ..contract import summarize, validate_payload
from .definition import definition_payload

if TYPE_CHECKING:
    from ...engine.context_run import ContextRun


def completed_payload(run: ContextRun) -> dict:
    evidence = completed_evidence(run)
    graph = definition_payload(run.graph)
    graph['completed'] = evidence
    graph['label'] = f"Completed run · {evidence['outcome']}"
    graph['identity'].update({'Context': evidence['context_id'], 'Graph key': evidence['graph_key'],
                              'Graph version': evidence['graph_version'], 'Owner generation': evidence['generation']})
    graph['details']['Execution coverage'] = evidence['coverage']
    nodes = {tuple(n['identity']['Core layout position']): n for n in graph['nodes'] if n['kind']=='operator'}
    for node in nodes.values():
        node['execution_steps'] = []
        for marker in node['resources']:
            marker['execution_steps'] = []
    # A rejected, incomplete declaration may have no compilable graph. No report
    # means no compilation is needed and no execution state is inferred.
    steps = run.graph._compiled_graph.steps if evidence['executions'] else ()
    for session in evidence['executions']:
        index = session['step_index']
        if type(index) is not int or not 0 <= index < len(steps):
            raise ValueError('execution references an unknown compiled step')
        step = steps[index]
        resource = isinstance(step, CompiledResourceStep)
        kind = 'resource' if resource else 'operator'
        name = step.resource_name if resource else step.operator_name
        if (session['kind'] != kind or session['name'] != summarize(name) or
                tuple(session['layout_position']) != step.layout_position):
            raise ValueError('execution identity disagrees with its authoritative compiled step')
        node = nodes.get(step.layout_position)
        if node is None:
            raise ValueError('compiled occurrence has no validation occurrence')
        subject = node
        if resource:
            operator = next((steps[i] for i in step.group_indices if isinstance(steps[i], CompiledOperatorStep)), None)
            if operator is None or not any(field is step.resource_field and value is step.resource for field, value in operator.bound_resources):
                raise ValueError('resource session has no verified consuming binding')
            markers = [m for m in node['resources'] if m['details']['Field']==step.resource_field.attribute_name]
            if len(markers)!=1:
                raise ValueError('resource session has no unique field marker')
            subject = markers[0]
        subject['execution_steps'].append(index)
        if session['outcome']=='failed':
            graph['findings'].append({'id': 'failure-'+session['id'], 'subject': subject['id'],
                                      'severity':'error', 'message':f"{kind.title()} session failed in iteration {session['iteration']}; see retained attempts."})
    for node in nodes.values():
        node['execution_steps'] = list(dict.fromkeys(node['execution_steps']))
        for marker in node['resources']:
            marker['execution_steps'] = list(dict.fromkeys(marker['execution_steps']))
    for edge in graph['edges']:
        edge['completed_connection'] = edge['id']
    return validate_payload(graph)
