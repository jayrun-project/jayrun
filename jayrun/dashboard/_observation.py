"""Bounded presentation projection of public snapshots. Never an execution owner."""
from collections import OrderedDict
import json
from hashlib import sha256
from ..engine.registry.context_status import StateTransition, StopRequested, ControlRequested
from datetime import datetime, timezone
from time import monotonic

from ._evidence import _failure, _record, safe
from ._location import execution_location

LIMIT = 256
TERMINALS = 1000


def actions(snapshot, *, own=False):
    if snapshot.state.is_terminal or snapshot.state.is_draining:
        return []
    if own:
        return ['stop', 'abort']
    state = snapshot.state.value
    result = ['abort'] if snapshot.stop_requested else ['stop', 'abort']
    if state == 'paused':
        result.insert(0, 'resume')
    elif state in {'queued', 'running', 'placement_waiting'}:
        result.insert(0, 'pause')
    return result


def _context_record(record):
    result = _record(record)
    result['context_id'] = str(record.context_id)
    result['sequence'] = str(record.sequence)
    result['value'] = safe(record.value,key=record.key) if len(record.key)<=256 else '[long-key value omitted]'
    return result


def control_version(snapshot):
    """Control-relevant public history; recording/iteration revisions are independent."""
    revisions = [(type(entry).__name__, entry.revision) for entry in snapshot.history
                 if isinstance(entry, (StateTransition, StopRequested, ControlRequested))]
    value = (snapshot.engine_id, snapshot.generation, snapshot.state.value,
             snapshot.finalized, snapshot.stop_requested, revisions)
    return sha256(json.dumps(value).encode()).hexdigest()


def project(snapshot, *, own=False):
    p = snapshot.progress
    result = {
        'id': str(snapshot.context_id), 'graph': (snapshot.graph_key or 'Local graph (unregistered)')[:256],
        'version': snapshot.graph_version[:256], 'engine_id': snapshot.engine_id[:256],
        'execution_location': execution_location(snapshot.engine_id),
        'generation': snapshot.generation, 'revision': snapshot.revision,
        'control_version': control_version(snapshot),
        'progress_revision': p.revision, 'sampled_at': p.observed_at.isoformat(),
        'state': snapshot.state.value, 'finalized': snapshot.finalized,
        'iteration': snapshot.iteration_count, 'completed_iterations': snapshot.completed_iterations,
        'max_iterations': p.max_iterations,
        'fraction': p.estimated_fraction, 'remaining_seconds': p.estimated_remaining_seconds,
        'elapsed_seconds': p.elapsed_seconds, 'confidence': p.confidence,
        'sample_count': p.sample_count, 'created_at': snapshot.created_at.isoformat(),
        'updated_at': snapshot.updated_at.isoformat(),
        'finished_at': snapshot.finished_at.isoformat() if snapshot.finished_at else None, 'stop_requested': snapshot.stop_requested,
        'controller': own, 'actions': actions(snapshot, own=own),
        'steps': [{'index': s.step_index, 'kind': s.step_kind, 'name': s.step_name[:200],
                   'state': s.state.value, 'iteration': s.iteration, 'elapsed_seconds': s.elapsed_seconds}
                  for s in p.steps[:64]],
        'steps_omitted': max(0, len(p.steps)-64),
        'records': [_context_record(r) for r in snapshot.records[-32:]],
        'records_omitted': max(0, len(snapshot.records)-32),
        'records_complete': snapshot.records_complete,
        'history': [_record(h) for h in snapshot.history[-32:]],
        'history_omitted': max(0, len(snapshot.history)-32),
        'failure': _failure(snapshot.failure),
        'artifacts': [{'id':str(key), 'history':[{'retained_index':i, **_record(entry)} for i,entry in enumerate(result.history) if i>=max(0,len(result.history)-8)],
                       'history_omitted':max(0,len(result.history)-8),
                       'coverage':'Retained lifecycle entries; completeness unknown. Artifact payloads are not collected by dashboard.'}
                      for key,result in snapshot.artifacts[:8]],
        'artifacts_omitted':max(0,len(snapshot.artifacts)-8),
    }
    # Bound the shared fleet independently of the core's retention policy.
    # Full finalized evidence remains available through the accepted exports.
    for name, omitted in [('history','history_omitted'),('records','records_omitted'),('artifacts','artifacts_omitted'),('steps','steps_omitted')]:
        while result[name] and len(json.dumps(result,allow_nan=False).encode()) > 8192:
            result[name].pop(0)
            result[omitted] += 1
    if len(json.dumps(result,allow_nan=False).encode()) > 8192:
        result['failure'] = '[failure details exceed fleet row bound; use finalized report]'
    return result


class _Fleet:
    def __init__(self, controller_id, *, recent_window_seconds=1800, max_recent_contexts=1000):
        self.controller_id = str(controller_id)
        self.recent_window_seconds = recent_window_seconds
        self.max_recent_contexts = max_recent_contexts
        self.outcomes = {}
        self.counted = set()
        self.count_gap = None
        self.rows = OrderedDict()
        self.order = {}
        self.sequence = 0
        self.evicted = 0
        self.gap = None
        self.pending = OrderedDict()

    def update(self, snapshot):
        key = str(snapshot.context_id)
        previous = self.rows.get(key)
        if previous and previous.get('summary_only'):
            known = (previous.get('generation') or 0, previous.get('revision') or 0)
            if ((snapshot.generation, snapshot.revision) < known or
                    (snapshot.generation == known[0] and not snapshot.finalized)):
                return False
        order = (snapshot.generation, snapshot.revision, snapshot.progress.revision, snapshot.progress.observed_at)
        if key in self.order and (order <= self.order[key]):
            return False
        row = project(snapshot, own=key == self.controller_id)
        self.order[key] = order
        self.rows[key] = row
        self.rows.move_to_end(key)
        if snapshot.finalized and key not in self.counted:
            if len(self.counted)<100000:
                self.counted.add(key)
                self.outcomes[row['state']]=self.outcomes.get(row['state'],0)+1
            else:
                self.count_gap='Session outcome counting stopped at 100,000 identities.'
        self.sequence += 1
        self._prune()
        self.settle()
        self._prune()
        return True

    def recover(self, row):
        """A summary can fill a missing terminal row, never replace fuller evidence."""
        key = row['id']
        previous = self.rows.get(key)
        if previous:
            old_order = (previous.get('generation') or 0, previous.get('revision') or 0)
            new_order = (row.get('generation') or 0, row.get('revision') or 0)
            if old_order > new_order or (previous['finalized'] and old_order >= new_order):
                return False
        self.rows[key] = row
        self.rows.move_to_end(key)
        # Real snapshot ordering wins over summary-only fallback at equal revision.
        self.order.pop(key, None)
        self.sequence += 1
        self._prune()
        self.settle()
        return True

    def count_recovered(self, row):
        """Count a summary only when retained in this capture session."""
        key = row['id']
        if key not in self.counted:
            if len(self.counted) < 100000:
                self.counted.add(key)
                self.outcomes[row['state']] = self.outcomes.get(row['state'], 0) + 1
            else:
                self.count_gap = 'Session outcome counting stopped at 100,000 identities.'

    def _prune(self):
        now = datetime.now(timezone.utc)
        terminal = [k for k,v in self.rows.items() if v['finalized']]
        for key in terminal:
            stamp=datetime.fromisoformat(self.rows[key]['updated_at'])
            if (now-stamp).total_seconds()>self.recent_window_seconds:
                self._remove(key)
        terminal=[k for k,v in self.rows.items() if v['finalized']]
        for key in terminal[:-self.max_recent_contexts]:
            self._remove(key)
        active=[k for k,v in self.rows.items() if not v['finalized']]
        for key in active[:-LIMIT]:
            self._remove(key)  # Full active discovery remains available through paginated public lookup.

    def _remove(self, key):
        self.rows.pop(key, None); self.order.pop(key, None)
        self.evicted += 1

    def settle(self):
        for request in self.pending.values():
            if request['status'] != 'submitted':
                continue
            row = self.rows.get(request['context'])
            if row:
                action, state = request['action'], row['state']
                reached = (action == 'pause' and state == 'paused' or
                           action == 'resume' and state in {'running','placement_waiting','queued'} or
                           action == 'stop' and row.get('stop_requested', False) or action == 'abort' and state == 'aborted')
                if reached:
                    request['status'] = 'observed'
                    request['message'] = ('Stop accepted; current state: ' if action == 'stop' else 'Observed context state: ')+state.upper()+'.'
                elif row['finalized']:
                    request['status'] = 'superseded by terminal outcome: '+state
                    request['message'] = 'Finalized as '+state.upper()+' before the requested transition was observed.'
            if request['status'] == 'submitted' and monotonic()-request['_sent'] > 15:
                request['message'] = 'Still awaiting an observed transition; the scheduling boundary may not have been reached. No automatic retry.'

    def payload(self):
        self.settle()
        self._prune()
        return {'sequence': self.sequence, 'observed_at': datetime.now(timezone.utc).isoformat(),
                'contexts': [{**row,'export_available':row['finalized'] and not row.get('summary_only', False)} for key,row in self.rows.items()], 'evicted': self.evicted,
                'gap': self.gap, 'limit': LIMIT, 'terminal_limit': self.max_recent_contexts,
                'requests': [{k:v for k,v in r.items() if not k.startswith('_')} for r in self.pending.values()],
                'coverage': 'Live observations plus available retained terminal summaries. Full historical evidence is not guaranteed. Rows are bounded; engine IDs do not establish host health.'}
