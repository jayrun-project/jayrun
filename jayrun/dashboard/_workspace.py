"""Temporary public reads; only detached data crosses an asynchronous boundary."""
import asyncio
from collections import OrderedDict
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from urllib.parse import parse_qs
from uuid import uuid4
from weakref import WeakKeyDictionary
from time import monotonic

from ._evidence import detached, terminal_evidence, progress_view, declaration_bindings, correspond
from ._observation import project
from ..persistence import PersistenceTimeout, PersistenceBackpressure, StorageUnavailable
from ._history import _HistorySource, history_row, _presentation, _archive_identity, _archive_key

MAX_CONTEXT_BYTES = 512 * 1024
MAX_CACHE_BYTES = 16 * 1024 * 1024
OUTCOME_STATES = ('finished', 'failed', 'aborted', 'rejected', 'stopped')


class _Workspace:
    def __init__(self, service, *, history=None):
        self.service = service
        self.history_source = None if history is None else _HistorySource(history)
        self.archive_enabled = history is not None
        self.partition = service.runtime.engine_id if history is not None else None
        self.details = OrderedDict()
        self.detail_bytes = 0
        self.graphs = OrderedDict()
        self.graph_bytes = 0
        self.local_graphs = WeakKeyDictionary()
        self.selected = OrderedDict()
        self.queue = asyncio.Queue(maxsize=32)
        self.worker = self.executor = None
        self.layout_pending = {}
        self.summary_pending = {}
        self.closing = False
        self.gap = None
        self.archived = OrderedDict()
        self.archive_loaded_at = 0.0
        self.archive_bytes = 0
        self.persistence = {
            'enabled': self.archive_enabled,
            'status': 'Memory-only session history' if not self.archive_enabled else 'Explicitly scoped Database reader; engine owns recording',
            'gap': None,
        }

    def start(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='jayrun-dashboard-data')
        self.worker = asyncio.create_task(self._work())

    async def _work(self):
        loop = asyncio.get_running_loop()
        while True:
            job = await self.queue.get()
            if job is None:
                self.queue.task_done()
                break
            kind, key, data, future = job
            operation = None
            try:
                operation = loop.run_in_executor(self.executor, self._process, kind, key, data)
                result = await asyncio.shield(operation)
                if kind != 'layout':
                    self._check_history()
                if kind == 'layout' and not self.closing and self.graphs.get(key) is data:
                    self.graph_bytes -= data['_bytes']
                    result['_bytes'] = len(json.dumps({k:v for k,v in result.items() if k != '_bytes'}).encode())
                    self.graphs[key] = result
                    self.graph_bytes += result['_bytes']
                    self._prune_graphs()
                if future is not None and not future.done():
                    future.set_result(result)
            except asyncio.CancelledError as interrupted:
                self.gap = 'Detached '+kind+' interrupted; admitted work is being settled'
                if future is not None and not future.done():
                    future.set_exception(RuntimeError(self.gap))
                if operation is not None:
                    try:
                        await self._finish_io(operation)
                    except asyncio.CancelledError:
                        raise interrupted
                    except BaseException as failure:
                        raise BaseExceptionGroup('Detached operation failed during cancellation',
                                                 [interrupted, failure]) from None
                raise
            except Exception as error:
                message = 'Detached '+kind+' failed: '+type(error).__name__
                self.gap = message
                if kind == 'layout' and not self.closing and self.graphs.get(key) is data:
                    self.graph_bytes -= data['_bytes']
                    data['layout_error'] = message
                    data['_bytes'] = len(json.dumps({k:v for k,v in data.items() if k != '_bytes'}).encode())
                    self.graph_bytes += data['_bytes']
                    self._prune_graphs()
                if future is not None and not future.done():
                    future.set_exception(error)
            finally:
                if kind == 'layout' and self.layout_pending.get(key) is data:
                    self.layout_pending.pop(key, None)
                self.queue.task_done()
                job = data = result = future = operation = None

    @staticmethod
    async def _finish_io(future):
        # A thread cannot be cancelled halfway through acquiring/closing its
        # connection. Join that ownership boundary before propagating cancellation.
        interrupted = False
        while not future.done():
            try:
                await asyncio.shield(future)
            except asyncio.CancelledError:
                interrupted = True
        result = future.result()
        if interrupted:
            raise asyncio.CancelledError
        return result

    def _check_history(self):
        if self.history_source is None:
            raise LookupError('No historical reader was granted')
        try:
            self.history_source.check()
        except Exception:
            # Even a cached result cannot outlive its capability.
            self.archived.clear()
            self.archive_bytes = 0
            raise

    def _process(self, kind, key, data):
        if kind == 'layout':
            from ..visualization.layout import arrange
            definition = arrange(data['definition'])
            return {**data, 'definition': definition, 'live_graph': definition, 'ready': True, 'layout_error': None}
        source = self.history_source
        if source is None:
            raise LookupError('No historical reader was granted')
        if kind == 'history':
            return source.query(data)
        if kind == 'history-summary':
            return source.summary(data.get('engine_session', ''), refresh=data.get('refresh', False))
        if kind == 'archived':
            return source.detail(key)
        if kind == 'sessions':
            return source.sessions()
        if kind == 'session':
            return source.session(key)
        raise ValueError('Unknown detached presentation job')

    def _enqueue(self, kind, key, data, future=None):
        if self.closing:
            return False
        try:
            self.queue.put_nowait((kind, key, data, future))
            return True
        except asyncio.QueueFull:
            self.gap = 'Detached work queue full; some live evidence may not be retained or laid out; Database recording is independent.'
            return False

    def _ensure_layout(self, key):
        """Demand-driven retry; one accepted job per cached graph at a time."""
        data = self.graphs.get(key)
        if data is None or data['ready'] or key in self.layout_pending or self.closing:
            return
        if self._enqueue('layout', key, data):
            self.layout_pending[key] = data

    def _require_layout(self, key, graph):
        if not graph['ready']:
            self._ensure_layout(key)
            raise LookupError(graph.get('layout_error') or 'Definition layout pending; retry after queued work completes')

    def graph_id(self, graph, snapshot):
        if snapshot.graph_key is not None:
            return json.dumps([snapshot.graph_key, snapshot.graph_version], separators=(',', ':'))
        identity = self.local_graphs.get(graph)
        if identity is None:
            identity = 'local:' + uuid4().hex
            self.local_graphs[graph] = identity
        return identity

    def _prune_graphs(self):
        while len(self.graphs) > 64 or self.graph_bytes > 8*1024*1024:
            _, removed = self.graphs.popitem(last=False)
            self.graph_bytes -= removed['_bytes']

    def _graph(self, run, snapshot):
        from ..visualization.adapters.definition import definition_payload
        graph_id = self.graph_id(run.graph, snapshot)
        if graph_id not in self.graphs:
            # These public adapters summarize declarations, never artifact values.
            definition = definition_payload(run.graph)
            data = {'id': graph_id, 'key': snapshot.graph_key, 'version': snapshot.graph_version,
                    'registered': snapshot.graph_key is not None, 'definition': definition,
                    'live_graph': definition, 'bindings':declaration_bindings(run.graph,definition), 'ready': False,
                    'access': 'Unknown: requirements are not declared by the public inspection API.'}
            size = len(json.dumps(data, allow_nan=False).encode())
            if size > 2*1024*1024:
                raise ValueError('Definition exceeds 2 MiB display limit')
            data['_bytes'] = size
            self.graphs[graph_id] = data
            self.graph_bytes += size
            self._prune_graphs()
        self._ensure_layout(graph_id)
        return graph_id

    def acquire(self, run, snapshot):
        """Synchronous scope: never store the run/snapshot or schedule a closure."""
        key = str(snapshot.context_id)
        previous = self.details.get(key)
        if previous and self._supersedes(previous, snapshot):
            return
        graph_id = self._graph(run, snapshot)
        data = self._detach(snapshot, run.graph, previous, graph_id=graph_id)
        data['graph_id'] = graph_id
        data['intrinsic_graph_id'] = run.graph.graph_id
        # Progress access is public and returns numeric evidence only.
        progress = progress_view(snapshot.progress, self.graphs[graph_id]['definition'])
        data['live'] = {'context_id': key, 'graph_id': progress['graph_id'],
                        'generation': snapshot.generation, 'revision': snapshot.revision,
                        'sample': progress['observed_at'] if 'observed_at' in progress else snapshot.progress.observed_at.isoformat(),
                        'progress': progress}
        self._retain(key, data)

    def observe(self, snapshot):
        """Prompt terminal copy while consuming an existing public event."""
        key = str(snapshot.context_id)
        previous = self.details.get(key)
        if not snapshot.finalized and previous is None:
            return
        if previous and self._supersedes(previous, snapshot):
            return
        data = self._detach(snapshot, None, previous)
        self._retain(key, data)

    @staticmethod
    def _supersedes(previous, snapshot):
        row = previous['row']
        order = (row.get('generation') or 0, previous.get('revision') or 0)
        incoming = (snapshot.generation, snapshot.revision)
        if incoming < order:
            return True
        if previous.get('finalized') and snapshot.generation == order[0]:
            return not snapshot.finalized or not previous.get('summary_only')
        return False

    def recover_terminal(self, summary):
        """Store only the facts the bounded core summary actually supplies."""
        key = str(summary.context_id)
        previous = self.details.get(key)
        if previous:
            known = (previous['row'].get('generation') or 0, previous.get('revision') or 0)
            incoming = (summary.generation or 0, summary.revision or 0)
            if incoming < known or (previous.get('finalized') and incoming <= known):
                return
        stamp = summary.finished_at.isoformat()
        row = {
            'id': key, 'graph': summary.graph_key or 'Local or unavailable graph',
            'version': summary.graph_version or 'Unknown', 'engine_id': summary.engine_id,
            'execution_location': self.service.execution_location(summary.engine_id),
            'generation': summary.generation, 'revision': summary.revision or 0,
            'state': summary.state.value, 'finalized': True, 'summary_only': True,
            'controller': False, 'actions': [], 'control_version': '',
            'iteration': summary.iteration_count, 'completed_iterations': summary.completed_iterations,
            'max_iterations': None, 'fraction': None, 'remaining_seconds': None,
            'elapsed_seconds': None,
            'confidence': None, 'sample_count': 0, 'created_at': summary.created_at.isoformat(),
            'updated_at': stamp, 'finished_at': stamp, 'sampled_at': stamp,
            'stop_requested': summary.stop_requested, 'failure': summary.failure_type,
            'steps': [], 'history': [], 'records': [], 'artifacts': [],
            'records_complete': False, 'steps_omitted': 0, 'records_omitted': 0,
            'history_omitted': 0, 'artifacts_omitted': 0,
        }
        gap = ('Recovered terminal summary only. Full report, graph, records, artifact lifecycle '
               'and configuration were not captured; their contents are unknown. '
               'Measured execution elapsed time was not captured.')
        data = {
            'context_id': key, 'row': row, 'finalized': True, 'summary_only': True,
            'revision': summary.revision or 0, 'session': str(self.service.context_id),
            'evidence_sampled_at': stamp, 'configuration': [], 'settings': {},
            'records': [], 'records_complete': False, 'display_complete': False,
            'records_omitted': 0, 'record_sequence': None,
            'artifacts': [], 'artifacts_omitted': 0, 'artifact_history_availability': gap,
            'activity': [], 'activity_omitted': 0, 'failure': summary.failure_type,
            'report': None, 'report_availability': gap, 'graph_available': False,
            'graph_availability': gap, 'capture_gap': gap,
            'terminal_summary_omissions': list(summary.omitted_fields),
            'access': {'observes': 'Unknown', 'controls': 'No', 'scope': 'Read-only recovered terminal summary'},
        }
        if self.service.fleet.recover(row):
            self._retain(key, data)
            self.service.fleet.count_recovered(row)

    def _detach(self, snapshot, graph, previous, graph_id=None):
        from ..reporting._completed import _format_evidence
        # Event-only snapshots have no live graph handle. Reuse the already
        # captured declaration, never infer applicability from empty results.
        captured = self.graphs.get(graph_id or (previous or {}).get('graph_id'))
        data = detached(snapshot, graph, declared_artifact_count=(
            None if captured is None else len(captured['definition']['artifacts'])))
        if previous and not previous.get('summary_only'):
            data['configuration'] = previous['configuration']
            data['graph_id'] = previous.get('graph_id')
            data['intrinsic_graph_id'] = previous.get('intrinsic_graph_id')
            graph_data = self.graphs.get(data.get('graph_id'))
            if graph_data is not None:
                progress = progress_view(snapshot.progress, graph_data['definition'])
                data['live'] = {'context_id':data['context_id'],'graph_id':progress['graph_id'],
                                'generation':snapshot.generation,'revision':snapshot.revision,
                                'sample':snapshot.progress.observed_at.isoformat(),'progress':progress}
        data.update({'finalized': snapshot.finalized, 'revision': snapshot.revision,
                     'row': project(snapshot), 'session': str(self.service.context_id)})
        data['row']['execution_location'] = self.service.execution_location(snapshot.engine_id)
        evidence = terminal_evidence(snapshot)
        if evidence is not None:
            data['failed_step'] = evidence['failed_step']
            evidence['configuration'] = data['configuration']
            evidence['settings'] = data['settings']
            evidence['configuration_omitted'] = max(0, len(snapshot.config_context)-len(data['configuration']))
            if captured is not None:correspond(evidence,captured['bindings'])
            data['completed_evidence'] = evidence
            data['report'] = _format_evidence(evidence)
            data['report_availability'] = 'Finalized event report evidence; unavailable graph correspondence is disclosed'
            data['row']['elapsed_seconds'] = evidence['elapsed_wall_seconds']
        return data

    def _retain(self, key, data):
        data['observation_coverage'] = {
            'status': 'gap_detected' if self.service.fleet.gap or self.gap else 'not_guaranteed',
            'event_gap': self.service.fleet.gap,
            'capture_gap': self.gap,
            'terminal_recovery_gap': getattr(self.service, '_terminal_recovery_gap', None),
            'scope': 'Service-wide gaps known at capture time; not proof that this individual run lost evidence. Absence of a gap does not establish complete observation.',
        }
        data['graph_available'] = data.get('graph_id') in self.graphs
        # Trim only detached safe projections; never inspect artifact data size.
        size = len(json.dumps(data, allow_nan=False).encode())
        if size > MAX_CONTEXT_BYTES and 'completed_evidence' in data:
            data.pop('completed_evidence')
            data['completed_evidence_availability'] = 'Finalized graph overlay omitted by the 512 KiB context display bound; retained artifact history, records and report remain independently available'
            size = len(json.dumps(data, allow_nan=False).encode())
        if size > MAX_CONTEXT_BYTES and data.get('report') is not None:
            data['report'] = None
            data['report_availability'] = 'Formatted report omitted by the 512 KiB context display bound; inspect retained structured details'
            size = len(json.dumps(data, allow_nan=False).encode())
        if size > MAX_CONTEXT_BYTES:
            for field in ('records', 'artifacts', 'activity'):
                data[field+'_omitted'] = data.get(field+'_omitted', 0) + len(data.get(field, []))
                data[field] = []
            data['records_complete'] = False
            data.pop('completed_evidence',None)
            data['report'] = None
            data['report_availability'] = 'Finalized evidence exceeds 512 KiB display bound; report omitted'
            data['artifact_history_availability'] = 'Artifact history omitted by the 512 KiB context display bound.'
            data['capture_gap'] = 'Oversized detached details omitted'
            size = len(json.dumps(data, allow_nan=False).encode())
        if size > MAX_CONTEXT_BYTES:
            data = {k:data[k] for k in ('context_id','row','session','revision','finalized')}
            data['capture_gap'] = 'Oversized detached context details omitted'
            size = len(json.dumps(data).encode())
        data['_bytes'] = size
        old = self.details.pop(key, None)
        self.detail_bytes -= old['_bytes'] if old else 0
        self.details[key] = data
        self.detail_bytes += size
        self.prune()

    def sample(self, key):
        for run in self.service.runtime.unfinished_contexts:
            if str(run.context_id) == key:
                snapshot = run.snapshot()
                self.service.fleet.update(snapshot)
                self.acquire(run, snapshot)
                return

    def context(self, key):
        if key.startswith('archive-'):
            self._check_history()
            value = self.archived.get(key)
            if value is None:
                raise LookupError('Saved evidence expired or is unavailable')
            return {k:v for k,v in value.items() if k not in {'captured_graph', 'completed_evidence', '_bytes'}}
        if key == str(self.service.context_id):
            row = self.service.self_row()
            return {'context_id':key, 'row':row, 'access':row['access'],
                    'finalized':False, 'configuration':[], 'settings':{}, 'records':[],
                    'artifacts':[], 'artifact_history_availability':'Own lifecycle history unavailable through public self inspection.',
                    'graph_available':False, 'report':None,
                    'report_availability':'Dashboard is serving; finalized report unavailable',
                    'capture_gap':row.get('state_provenance')}
        self.selected[key] = None
        while len(self.selected) > 16:
            self.selected.popitem(last=False)
        if key not in self.details:
            self.sample(key)
        value = self.details.get(key) or self.archived.get(key)
        if value:
            row = value.get('row')
            if value.get('finalized') and row.get('generation') is not None:
                row = {**row, **_presentation(self.service.runtime.engine_id,
                    key+':'+str(row['generation']), value.get('intrinsic_graph_id'), row.get('version'))}
            return {k:v for k,v in {**value, 'row':row, 'observation':value.get('live')}.items() if k not in {'_bytes','live','completed_evidence'}}
        if key in self.service.fleet.rows:
            return {'context_id':key, 'row':self.service.fleet.rows[key],
                    'capture_gap':'Context ended before detailed evidence could be captured',
                    'graph_available':False, 'records':[], 'artifacts':[],
                    'report':None, 'report_availability':'Finalized evidence unavailable'}
        raise LookupError('Context expired or was not captured. Selection has not changed.')

    def _recent_archive_key(self, key):
        if not key.startswith('archive-'):
            return key
        self._check_history()
        raise LookupError('Historical context has frozen evidence, not live progress or control')

    def live(self, key):
        key = self._recent_archive_key(key)
        data = self.details.get(key)
        if not data or not data.get('live'):
            raise LookupError('Progress unavailable; no run is retained')
        graph = self.graphs.get(data.get('graph_id'))
        if not graph:
            raise LookupError('Definition expired')
        return {'graph':graph['live_graph'], 'observation':data['live']}

    def canvas(self, key):
        self.context(key)
        archived = self.archived.get(key) if key.startswith('archive-') else None
        if archived is not None:
            captured = archived.get('captured_graph')
            if captured is None:
                raise LookupError(archived.get('graph_availability', 'Stored layout unavailable'))
            return deepcopy(captured['definition'])
        data = self.details.get(key)
        graph = self.graphs.get(data.get('graph_id')) if data else None
        if not graph:
            raise LookupError('Graph unavailable; definition not captured or expired')
        self._require_layout(data.get('graph_id'), graph)
        payload=deepcopy(graph['definition'])
        if data.get('live'):
            # Bind only captured compiled references present in this observation.
            # Graphs/definition-only routes keep their declaration-only payload.
            subjects = {subject['id']: subject for node in payload['nodes']
                        for subject in (node, *node.get('resources', []))}
            for node in data['live']['progress']['nodes']:
                for step in node['steps']:
                    target = graph['bindings']['steps'].get(str(step['index']))
                    if target is None:
                        continue
                    if any(step[key] != target[key] for key in ('kind', 'name')):
                        raise ValueError('Progress disagrees with captured step identity')
                    subjects[target['id']]['identity'].setdefault('Execution steps', []).append(
                        {key: step[key] for key in ('index', 'kind', 'name')})
        if archived is not None:
            payload['details']['Archive'] = {
                'Evidence': 'Captured definition for this archived run; read-only',
                'Context': archived['context_id'], 'Session': archived['session'],
                'Captured at (Unix seconds)': archived.get('captured_at'),
                'Coverage': archived.get('capture_gap') or 'Only observed and retained evidence; not complete engine history',
                'Finalized overlay': archived.get('completed_evidence_availability', 'Retained finalized mapping' if data.get('completed_evidence') else 'Unavailable; no execution is inferred'),
            }
        evidence=data.get('completed_evidence')
        if evidence is not None:
            if str(evidence['context_id']) != str(data['context_id']) or not data.get('finalized'):
                raise ValueError('Final evidence belongs to another context or is not finalized')
            from ..visualization.contract import validate_payload
            payload['completed']=deepcopy(evidence)
            payload['details']['Execution coverage']=evidence['coverage']
            subjects={subject['id']:subject for node in payload['nodes'] for subject in (node,*node.get('resources',[]))}
            for session in evidence['executions']:
                target=graph['bindings']['steps'].get(str(session['step_index']))
                if target is None:continue
                if any(session[k]!=target[k] for k in ('kind','name','layout_position')):
                    raise ValueError('Final evidence disagrees with captured declaration identity')
                subject=subjects[target['id']]
                indices=subject.setdefault('execution_steps',[])
                if session['step_index'] not in indices:indices.append(session['step_index'])
            for edge in payload['edges']:edge['completed_connection']=edge['id']
            payload=validate_payload(payload)
        return payload

    def export(self, key):
        from ..visualization.renderer import _document
        return _document(self.canvas(key))

    def prune(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        if monotonic()-self.archive_loaded_at > min(60,self.service.fleet.recent_window_seconds):
            self.archived.clear()
            self.archive_bytes = 0
        terminals = [k for k,v in self.details.items() if v['finalized']]
        expired = {k for k in terminals if (now-datetime.fromisoformat(self.details[k]['row']['updated_at'])).total_seconds()>self.service.fleet.recent_window_seconds}
        expired.update(terminals[:-self.service.fleet.max_recent_contexts])
        active = [k for k,v in self.details.items() if not v['finalized']]
        expired.update(active[:-256])
        for key in expired:
            self.detail_bytes -= self.details.pop(key)['_bytes']
        while self.detail_bytes > MAX_CACHE_BYTES:
            _, old = self.details.popitem(last=False)
            self.detail_bytes -= old['_bytes']
            self.gap = 'Detached cache bound shortened retention'

    async def _request(self, kind, key='', data=None):
        self._check_history()
        future = asyncio.get_running_loop().create_future()
        if not self._enqueue(kind, key, data, future):
            raise RuntimeError('Historical presentation busy; retry later')
        result = await future
        self._check_history()
        return result

    def _recent_history(self, key):
        session, identity = _archive_identity(key)
        if session != self.partition or not self.history_source.reader._allowed(session):
            return None
        context, separator, generation = identity.rpartition(':')
        if not separator or not generation.isdecimal():
            return None
        value = self.details.get(context)
        if not value or not value.get('finalized') or value['row'].get('generation') != int(generation):
            return None
        result = deepcopy(value)
        result.update(archive_id=key, context_id=identity, session=session, archived=True,
            database_history=False, graph_id=value.get('intrinsic_graph_id'),
            publication_status='Recent finalized observation; no committed entry returned yet',
            access={'observes':'Explicit historical scope', 'controls':'No', 'scope':'Read-only recent handoff'})
        result['row'].update(id=key, actions=[], controller=False, control_version='')
        result['row'].update(_presentation(session, identity, result.get('graph_id'),
                                           result['row'].get('version')))
        try:
            result['captured_graph'] = {'definition': self.canvas(context)}
        except (LookupError, ValueError):
            result['graph_available'] = False
        result.pop('live', None)
        return result

    async def load_archive(self, key):
        if not key.startswith('archive-'):
            return
        self._check_history()
        cached = self.archived.get(key)
        # Pending observations are never cached as durable. Two-second bounded
        # caches reduce refresh I/O while preserving revocation checks.
        if cached is not None and cached.get('database_history') and monotonic()-cached.get('_loaded_at', 0) < 2:
            return
        try:
            value = await self._request('archived', key)
        except (PersistenceTimeout, PersistenceBackpressure, StorageUnavailable) as error:
            value = self._recent_history(key)
            if value is None:
                raise
            value['capture_gap'] = 'Historical read unavailable: '+type(error).__name__+'; showing recent finalized observation only'
        if value is None:
            value = self._recent_history(key)
        previous = self.archived.pop(key, None)
        if previous is not None:
            self.archive_bytes -= previous.get('_bytes', 0)
        if value is None:
            raise LookupError('Saved evidence expired or is unavailable within the granted scope')
        value['_loaded_at'] = monotonic()
        self._retain_archive(key, value)
        self.archive_loaded_at = monotonic()

    def _retain_archive(self, key, value):
        value = json.loads(json.dumps(value, allow_nan=False))
        if not isinstance(value, dict) or not isinstance(value.get('row'), dict):
            raise ValueError('Archive returned invalid detached evidence')
        if not key.startswith('archive-') or value.get('archive_id') != key:
            raise ValueError('Archive returned a different evidence identity')
        value['archived'] = True
        value['row'].update(id=key, archived=True, actions=[], controller=False)
        old = self.archived.pop(key, None)
        if old is not None:
            self.archive_bytes -= old.get('_bytes', 0)
        value['_bytes'] = len(json.dumps(value, allow_nan=False).encode())
        self.archived[key] = value
        self.archive_bytes += value['_bytes']
        while len(self.archived) > 25 or self.archive_bytes > MAX_CACHE_BYTES:
            _, old = self.archived.popitem(last=False)
            self.archive_bytes -= old['_bytes']

    async def history_request(self, parsed):
        query = {k:v[-1] for k,v in parse_qs(parsed.query,keep_blank_values=True).items()}
        result = await self._request('history', data=query)
        # A matching recent observation can supply factual wall time while the
        # committed header remains a header-only read. Keep exact IDs for joins.
        for item in result['rows']:
            context, sep, generation = item['context_id'].rpartition(':')
            observed = self.details.get(context) if sep and generation.isdecimal() and item['session'] == self.partition else None
            if observed and observed.get('finalized') and observed['row'].get('generation') == int(generation) and observed.get('intrinsic_graph_id') == item['graph_id']:
                item['row']['elapsed_seconds'] = observed['row'].get('elapsed_seconds')
        # A bounded recent section shares exact routing IDs with durable rows.
        # Never erase the detail cache merely because another page was listed.
        recent = []
        if result['page'] == 0 and self.partition in result.get('sessions', ()):
            seen = {value['archive_id'] for value in result['rows']}
            for context, value in reversed(self.details.items()):
                row = value['row']
                if not value.get('finalized') or row.get('generation') is None:
                    continue
                key = _archive_key(self.partition, context+':'+str(row['generation']))
                if key in seen or (query.get('state') and query['state'] != row['state']):
                    continue
                if query.get('session') and query['session'] != self.partition:
                    continue
                if query.get('engine_session') and query['engine_session'] != self.partition:
                    continue
                intrinsic = value.get('intrinsic_graph_id')
                if query.get('graph_id') and query['graph_id'] != intrinsic:
                    continue
                if query.get('search') and query['search'] not in ' '.join((context, self.partition, intrinsic or '', row.get('version') or '')):
                    continue
                if query.get('date') and (row.get('finished_at') or row.get('updated_at') or '')[:10] < query['date']:
                    continue
                if query.get('capability') in ('controls', 'observes'):
                    continue
                if self.history_source.reader._allowed(self.partition):
                    # Do not clone/render a captured graph merely to list a row.
                    projected = history_row(value, session_id=self.partition,
                                            context_id=context+':'+str(row['generation']))
                    projected.update(id=key, session=self.partition, graph_id=intrinsic,
                        actions=[], controller=False, control_version='', archived=True,
                        recent=True)
                    recent.append(projected)
                if len(recent) == 25:
                    break
        result['recent_rows'] = recent
        result['recent_coverage'] = 'At most 25 recent observations not on this committed page; publication status unverified. Matching routing IDs are deduplicated.'
        return result

    async def history_summary_request(self, engine_session='', *, refresh=False):
        if refresh and not self.archive_enabled:
            raise LookupError('Database refresh unavailable: no historical reader granted')
        if self.archive_enabled:
            self._check_history()
            if self.closing:
                raise RuntimeError('Historical reader workspace is closing')
            # Coalesce equal intents before admission to the existing single worker.
            # A disconnected HTTP waiter must not cancel work shared by other readers.
            key = (engine_session, bool(refresh))
            future = self.summary_pending.get(key)
            if future is None:
                if len(self.summary_pending) >= 8:
                    raise RuntimeError('Historical summary busy; retry later')
                future = asyncio.get_running_loop().create_future()
                if not self._enqueue('history-summary', '', {'engine_session':engine_session, 'refresh':refresh}, future):
                    raise RuntimeError('Historical presentation busy; retry later')
                self.summary_pending[key] = future
                def settled(value):
                    if self.summary_pending.get(key) is value:
                        self.summary_pending.pop(key, None)
                    if not value.cancelled():
                        value.exception()  # Observe failures even after every HTTP waiter disconnects.
                future.add_done_callback(settled)
            result = await asyncio.shield(future)
            self._check_history()
            if self.closing:
                raise RuntimeError('Historical reader workspace closed during refresh')
            return {**deepcopy(result), 'persistence': self.persistence}
        values = [value for value in self.details.values() if value.get('finalized')]
        if engine_session:
            values = [value for value in values if value.get('row', {}).get('engine_id') == engine_session]
        counts = {}
        for value in values:
            state = value.get('row', {}).get('state')
            if state in OUTCOME_STATES:
                counts[state] = counts.get(state, 0) + 1
        return {'counts': counts, 'total': sum(counts.values()), 'complete':True,
                'source': 'memory-only retained history', 'persistence': self.persistence}

    async def sessions_request(self, key=None):
        return await self._request('sessions' if key is None else 'session', key or '')

    def get(self, parsed):
        query = {k:v[-1] for k,v in parse_qs(parsed.query,keep_blank_values=True).items()}
        route = parsed.path
        if route == '/api/graphs':
            return {'graphs':[{k:v[k] for k in ('id','key','version','registered','access')} for v in self.graphs.values()],
                    'gap':'Definitions captured from authorized active runs; zero-run registry discovery is unavailable.'}
        if route == '/api/graph':
            graph = self.graphs.get(query.get('id'))
            if graph is None: raise LookupError('Definition unavailable or expired')
            self._require_layout(query.get('id'), graph)
            return {k:v for k,v in graph.items() if k != '_bytes'}
        if route == '/api/context': return self.context(query.get('id',''))
        if route == '/api/live': return self.live(query.get('id',''))
        if route == '/api/canvas':
            key=query.get('id','')
            data=self.context(key)
            return {'context_id':key,'payload':self.canvas(key),'finalized':data.get('finalized',False),
                    'coverage':'Captured definition, recorded progress and bounded finalized evidence only'}
        if route not in {'/api/contexts','/api/history'}: raise LookupError('Unknown dashboard route')
        page = max(0,int(query.get('page',0))); size = 25
        history = route == '/api/history'
        workloads = not history and query.get('workloads') == '1'
        rows = ({k:history_row(v, session_id=self.service.runtime.engine_id,
                              context_id=k+':'+str(v['row']['generation']))
                 for k,v in self.details.items() if v['finalized'] and v['row'].get('generation') is not None}
                if history else {})
        if not history:
            for run in self.service.runtime.unfinished_contexts:
                snapshot = run.snapshot(); key = str(snapshot.context_id)
                if snapshot.finalized or snapshot.state.is_terminal:
                    continue
                if workloads and key == str(self.service.context_id):
                    continue
                # List membership/state must follow current public discovery,
                # independently of bounded/slower detail capture.
                row = project(snapshot)
                row['execution_location'] = self.service.execution_location(snapshot.engine_id)
                rows[key] = {**row, 'graph_id':self.graph_id(run.graph,snapshot), 'session':str(self.service.context_id)}
        if not history and not workloads:
            rows[str(self.service.context_id)] = self.service.self_row()
        values = list(rows.values())
        sessions = sorted({r['session'] for r in values if r.get('session')})
        if query.get('engine_session'):
            values = [r for r in values if r.get('engine_id') == query['engine_session']]
        # Recent memory-only history must also offer graphs whose layout cache
        # was evicted. A label describes captured evidence, not current topology.
        graph_choices = {}
        if history:
            for row in values:
                if row.get('graph_id') is not None and (not query.get('session') or row.get('session') == query['session']):
                    graph_choices[row['graph_id']] = {'id': row['graph_id'], 'key': row['graph'], 'version': row['version']}
        for field in ('state','session','graph_id'):
            if query.get(field):
                values = [r for r in values if r.get(field)==query[field] or
                          (not history and field == 'state' and r.get('controller'))]
        capability = query.get('capability')
        if capability:
            values = [r for r in values if (capability == 'unknown' and not r.get('controller')) or
                      (capability in {'observes','controls'} and r.get('controller'))]
        if query.get('search'):
            term = query['search'].lower()
            values = [r for r in values if term in ' '.join([r['id'],r['graph'],r['version']]).lower()]
        if query.get('date'): values = [r for r in values if (r.get('updated_at') or '')[:10]>=query['date']]
        values.sort(key=lambda r:(r['created_at'],r['id']),reverse=query.get('sort','oldest')=='newest')
        page = min(page, max(0, (len(values)-1)//size))
        return {'rows':values[page*size:(page+1)*size], 'total':len(values), 'page':page, 'page_size':size,
                'scope':'Retained current-session history' if history else 'Active workloads only; dashboard excluded' if workloads else 'Authorized active contexts; included dashboard service is independent of the workload state filter',
                'persistence':self.persistence, 'gap':self.service.fleet.gap, 'capture_gap':self.gap,
                'graphs':list(graph_choices.values())[:256], 'graphs_omitted':max(0,len(graph_choices)-256),
                'sessions':sessions[:100], 'sessions_omitted':max(0,len(sessions)-100)}

    async def close(self):
        self.closing = True
        failures = []
        worker = self.worker
        if worker is not None:
            if not worker.done():
                # A failed worker cannot consume a full queue. Race admission
                # of the drain sentinel against worker termination, not a sleep.
                sentinel = asyncio.create_task(self.queue.put(None))
                try:
                    await asyncio.wait((sentinel, worker), return_when=asyncio.FIRST_COMPLETED)
                finally:
                    if not sentinel.done():
                        sentinel.cancel()
                    result, = await asyncio.gather(sentinel, return_exceptions=True)
                    if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                        failures.append(result)
            try:
                await worker
            except BaseException as error:
                failures.append(error)
        try:
            if self.executor is not None:
                self.executor.shutdown(wait=True, cancel_futures=True)
        except BaseException as error:
            failures.append(error)
        finally:
            # A failed worker may leave accepted jobs/futures in the queue.
            # Classify abandonment and release every detached payload owner.
            while not self.queue.empty():
                job = self.queue.get_nowait()
                try:
                    if job is not None:
                        self.gap = 'Dashboard closed before accepted detached work completed'
                        future = job[3]
                        if future is not None and not future.done():
                            future.set_exception(RuntimeError(self.gap))
                finally:
                    self.queue.task_done()
                    job = future = None
            self.details.clear(); self.detail_bytes = 0
            self.graphs.clear(); self.graph_bytes = 0
            self.local_graphs.clear(); self.selected.clear(); self.archived.clear()
            self.layout_pending.clear(); self.summary_pending.clear(); self.archive_bytes = 0
        if failures:
            raise BaseExceptionGroup('Dashboard workspace shutdown failures', failures)
