"""Optional bounded HTTP adapter; scoped discovery and public runtime.apply."""
import asyncio
from collections import OrderedDict
import json
import re
from time import monotonic
from dataclasses import asdict, replace
from datetime import datetime, timezone

from ..engine.registry.context_status import ControlRequested
from ..engine.messages.origin import ContextOrigin, CommandOrigin
from urllib.parse import parse_qs, urlsplit

from ..context import ObserverOverflowError, ContextRequest
from ..settings import ContextSettings
from ._observation import _Fleet, actions, control_version, project
from ._history import history_row
from ._location import execution_location

MAX_BODY = 8192
MAX_RESPONSE = 4 * 1024 * 1024


class _Host:
    """Cached resource owns per-invocation services, never cached authority."""
    def __init__(self, host, port, **retention):
        self.host, self.port = host, port
        self.retention = retention
        self.services = set()

    async def open(self, runtime, context):
        if len(self.services) >= 8:
            raise RuntimeError('Dashboard resource service limit reached')
        service = _Service(runtime, context.id, **self.retention)
        service.owner_context = context
        self.services.add(service)
        try:
            await service.bind(self.host, self.port)
            return service
        except BaseException:
            try:
                await service.close()
            finally:
                self.services.discard(service)
            raise

    async def close(self):
        services = tuple(self.services)
        if not services:
            return
        drained = asyncio.gather(*(service.close() for service in services), return_exceptions=True)
        interrupted = False
        while not drained.done():
            try:
                await asyncio.shield(drained)
            except asyncio.CancelledError:
                interrupted = True
        self.services.difference_update(services)
        failures = [result for result in drained.result() if isinstance(result, BaseException)]
        if failures:
            raise BaseExceptionGroup('Dashboard service cleanup failures', failures)
        if interrupted:
            raise asyncio.CancelledError


class _Service:
    def __init__(self, runtime, context_id, *, recent_window_seconds=1800, max_recent_contexts=1000):
        self.runtime = runtime
        self.context_id = context_id
        self._self_projection = None
        self._self_order = None
        self.fleet = _Fleet(context_id, recent_window_seconds=recent_window_seconds, max_recent_contexts=max_recent_contexts)
        from ._workspace import _Workspace
        try:
            history = getattr(runtime, 'history', None)
        except PermissionError:
            history = None  # Existing live-only supervisor dashboards remain live-only.
        self.workspace = _Workspace(self, history=history)
        self.active_counts = {}
        self.active_counts_sampled_at = None
        self.observed_work = None
        self.active_locations = {}
        self.location_overflow = False
        self.pressure = None
        self.pressure_gap = None
        self.server = None
        self.observer = None
        self.consumer = None
        self.clients = set()
        self.handlers = set()
        self.url = ''
        self.closed = False
        self.ready = False
        self._close_task = None
        self._sample_cursor = 0
        self._projection_times = OrderedDict()
        self._projection_interval = 0.1
        self._coalesced_events = 0
        self._terminal_cursor = None
        self._terminal_recovery_gap = None
        self._terminal_recovery_pending = False

    async def bind(self, host, port):
        # Establish the observer before discovery, so terminal transitions in
        # the startup/discovery window can still supply public snapshots.
        self.observer = self.runtime.events
        self.server = await asyncio.start_server(self._http, host, port, limit=16384)
        address, actual_port = self.server.sockets[0].getsockname()[:2]
        authority = f'[{address}]:{actual_port}' if ':' in address else f'{address}:{actual_port}'
        self.url = 'http://'+authority
        self.authority = authority

    async def _events(self):
        try:
            count = 0
            async for event in self.observer:
                try:
                    self._capture_event(event.snapshot)
                finally:
                    del event
                count += 1
                if count % 64 == 0:
                    await asyncio.sleep(0)
        except ObserverOverflowError:
            self._observation_gap()

    def _observation_gap(self):
        self.fleet.gap = ('Observer overflow: event history is incomplete. Public authority queue cannot be replaced; '
                          'polling resynchronizes visible runs; terminal recovery supplies only summaries still retained by the engine.')

    def _capture_event(self, snapshot):
        # Only safe detached projections survive this immediate observation.
        try:
            key = str(snapshot.context_id)
            if key == str(self.context_id):
                order = (snapshot.generation, snapshot.revision, snapshot.progress.revision)
                if self._self_order is None or order >= self._self_order:
                    row = project(snapshot, own=True)
                    # Dedicated bounded presentation metadata; no run, snapshot,
                    # records, artifact history or control capability is retained.
                    self._self_projection = {name: row[name] for name in (
                        'id', 'graph', 'version', 'state', 'finalized', 'iteration',
                        'fraction', 'max_iterations', 'completed_iterations',
                        'created_at', 'updated_at', 'generation', 'revision',
                        'stop_requested', 'elapsed_seconds', 'confidence')}
                    self._self_order = order
            marker = (snapshot.engine_id, snapshot.generation, snapshot.state,
                      snapshot.finalized, snapshot.stop_requested)
            now = monotonic()
            previous = self._projection_times.get(key)
            if not snapshot.finalized and previous is not None and previous[0] == marker and now - previous[1] < self._projection_interval:
                self._coalesced_events += 1
                return
            if snapshot.finalized:
                self._projection_times.pop(key, None)
            else:
                self._projection_times[key] = (marker, now)
                self._projection_times.move_to_end(key)
                while len(self._projection_times) > 256:
                    self._projection_times.popitem(last=False)
            if self.fleet.update(snapshot):
                self.workspace.observe(snapshot)
        except Exception as error:
            self.workspace.gap = 'Event evidence copy failed: '+type(error).__name__

    async def serve(self, duration):
        self.workspace.start()
        self.consumer = asyncio.create_task(self._events())
        deadline = None if duration is None else monotonic()+duration
        while not self.closed and self.runtime.alive and (deadline is None or monotonic() < deadline):
            if self.consumer.done():
                self.consumer.result()
            self._sample_visible()
            self._recover_terminals()
            self.workspace.prune()
            self.ready = True
            await asyncio.sleep(.1)

    def _recover_terminals(self):
        reader = getattr(self.runtime, 'terminal_history', None)
        if reader is None:
            self._terminal_recovery_gap = 'Terminal summary recovery is unavailable from this observation source.'
            return
        # Recovery is a bounded memory-only presentation pass. The engine's
        # publication lifecycle is independent of dashboard queue capacity.
        try:
            page = reader(after=self._terminal_cursor, limit=128)
        except PermissionError:
            self._terminal_recovery_gap = 'Terminal recovery requires Controller authority; scoped observation continues.'
            return
        if page.gap:
            self._terminal_recovery_gap = 'Some terminal summaries expired from the engine window before recovery; full evidence remains incomplete.'
        for summary in page.entries:
            # Supervision services are not ordinary workload cards. Their
            # summaries remain available through the authorized engine read API.
            if str(summary.context_id) != str(self.context_id) and not summary.supervising:
                self.workspace.recover_terminal(summary)
        self._terminal_cursor = page.next_cursor
        self._terminal_recovery_pending = page.has_more

    def execution_location(self, engine_id):
        return execution_location(engine_id, local_engine_id=self.runtime.engine_id,
                                  local_name=self.runtime.name)

    def location_summary(self):
        """Bounded current-owner groups; retained outcomes are not session totals."""
        local = self.execution_location(self.runtime.engine_id)
        groups = {key: {**value, 'active_counts': dict(value['active_counts']),
                        'retained_outcomes': {}}
                  for key, value in self.active_locations.items()}
        groups.setdefault(local['id'], {**local, 'active_counts': {}, 'retained_outcomes': {}})
        omitted = self.location_overflow
        for row in self.fleet.rows.values():
            if row.get('controller'):
                continue
            location = row.get('execution_location') or self.execution_location(row.get('engine_id'))
            if location['id'] == local['id']:
                location = local
            key = location['id']
            if key not in groups and len(groups) >= 128:
                omitted = True
                continue
            group = groups.setdefault(key, {**location, 'active_counts': {}, 'retained_outcomes': {}})
            if row['finalized']:
                outcomes = group['retained_outcomes']
                outcomes[row['state']] = outcomes.get(row['state'], 0) + 1
        return {'locations': sorted(groups.values(), key=lambda g: g['id']),
                'complete': not omitted,
                'coverage': 'Authorized current owners and bounded retained observations; not host discovery. Scoped outcomes are retained counts, not cumulative totals.'}

    def self_row(self):
        """Identity/activity of this executing service; no synthetic core snapshot."""
        key = str(self.context_id)
        row = dict(self._self_projection or self.fleet.rows.get(key, {}))
        if not row:
            row = {'id':key, 'graph':'Dashboard service', 'version':'Unavailable',
                   'state':'unknown', 'state_label':'SERVING', 'finalized':False,
                   'iteration':None, 'fraction':None, 'created_at':'', 'updated_at':None,
                   'generation':None, 'revision':None,
                   'state_provenance':'Dashboard operator is serving; own core snapshot unavailable'}
        row.update({'engine_id':self.runtime.engine_id,
                    'execution_location':self.execution_location(self.runtime.engine_id),
                    'controller':True, 'actions':[], 'access':{
            'observes':'Yes', 'controls':'Yes',
            'scope':'Authorized submission scope. Exact grant and graph scope unavailable; successful authority observer access verifies a supervisor/controller grant.'}})
        return row

    def _sample_visible(self):
        # All run/tuple/snapshot references die before serve() awaits again.
        try:
            pressure = self.runtime.pressure
            self.pressure = {**asdict(pressure), 'sampled_at': pressure.sampled_at.isoformat()}
            self.pressure_gap = None
        except Exception as error:
            # A sampling error must not erase the last useful sample or stop
            # observation/control. Retain only its type, never the exception.
            self.pressure_gap = 'Pressure sample unavailable: '+type(error).__name__
        self.active_counts = {}
        self.active_locations = {}
        self.location_overflow = False
        runs = self.runtime.unfinished_contexts
        observed_work = {}
        count = len(runs)
        start = self._sample_cursor % count if count else 0
        sampled = {(start + index) % count for index in range(min(256, count))}
        self._sample_cursor = (start + len(sampled)) % count if count else 0
        for index, run in enumerate(runs):
            if str(run.context_id) == str(self.context_id):
                continue
            state = run.state
            if not state.is_terminal:
                self.active_counts[state.value] = self.active_counts.get(state.value, 0) + 1
                engine_id = run.engine_id
                engine_id = engine_id if isinstance(engine_id, str) and engine_id else None
                counts = observed_work.setdefault(engine_id, {})
                counts[state.value] = counts.get(state.value, 0) + 1
                location = self.execution_location(engine_id)
                key = location['id']
                if key in self.active_locations or len(self.active_locations) < 127:
                    group = self.active_locations.setdefault(key, {**location, 'active_counts': {}})
                    group['active_counts'][state.value] = group['active_counts'].get(state.value, 0) + 1
                else:
                    self.location_overflow = True
            if index in sampled or str(run.context_id) in self.workspace.selected:
                # A handle discovered as nonterminal may have finalized before
                # this read. Capture that evidence too; never fetch its results.
                snapshot = run.snapshot()
                self.fleet.update(snapshot)
                try:
                    self.workspace.acquire(run, snapshot)
                except Exception as error:
                    self.workspace.gap = 'Temporary evidence read failed: '+type(error).__name__
        self.observed_work = [
            {'engine_id': engine_id, 'counts': counts}
            for engine_id, counts in observed_work.items()
        ]
        self.active_counts_sampled_at = datetime.now(timezone.utc).isoformat()

    async def close(self):
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        interrupted = False
        while not self._close_task.done():
            try:
                await asyncio.shield(self._close_task)
            except asyncio.CancelledError:
                interrupted = True
        self._close_task.result()
        if interrupted:
            raise asyncio.CancelledError

    async def _close(self):
        if self.closed:
            return
        self.closed = True
        failures = []

        def attempt(operation):
            try:
                operation()
            except BaseException as error:
                failures.append(error)

        if self.server is not None:
            attempt(self.server.close)
        observer = self.observer
        if observer is not None:
            # Detach first. An authentic closed observer remains synchronously
            # drainable. Do not wait for the dashboard's own finalization.
            try:
                observer.close()
            except BaseException as error:
                failures.append(error)
            else:
                try:
                    for event in observer:
                        try:
                            self._capture_event(event.snapshot)
                        finally:
                            del event
                except ObserverOverflowError:
                    self._observation_gap()
                except BaseException as error:
                    failures.append(error)
        attempt(self._recover_terminals)
        if self._terminal_recovery_pending:
            self._terminal_recovery_gap = 'Service closed before pending terminal summaries were recovered.'
            self.workspace.gap = self._terminal_recovery_gap
        self._projection_times.clear()
        self.observer = observer = None
        tasks = tuple(dict.fromkeys(t for t in (self.consumer, *self.handlers)
                      if t is not None and t is not asyncio.current_task()))
        cancelled = {task for task in tasks if not task.done()}
        for task in cancelled:
            task.cancel()
        for writer in tuple(self.clients):
            attempt(writer.close)
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for task, result in zip(tasks, results):
                if isinstance(result, asyncio.CancelledError) and task in cancelled:
                    continue  # This owner explicitly requested cancellation.
                if isinstance(result, BaseException):
                    failures.append(result)
        if self.server is not None:
            try:
                await self.server.wait_closed()
            except BaseException as error:
                failures.append(error)
        try:
            await self.workspace.close()
        except BaseException as error:
            failures.append(error)
        finally:
            self._self_projection = None
            self._self_order = None
            self.fleet.rows.clear()
            self.fleet.order.clear()
            self.fleet.pending.clear()
            self.fleet.counted.clear()
            self.clients.clear()
            self.handlers.clear()
            self.pressure = None
            self.observed_work = None
            self.consumer = None
            self.runtime = None
            self.owner_context = None
        if failures:
            raise BaseExceptionGroup('Dashboard shutdown failures', failures)

    def control(self, body):
        if not isinstance(body, dict) or set(body) not in ({'id','context','action','generation','revision'}, {'id','context','action','generation','revision','control_version'}):
            raise ValueError('Expected id, context, action, generation and revision')
        request_id, context_id, action = body['id'], body['context'], body['action']
        if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',request_id):
            raise ValueError('Invalid request identity')
        if not isinstance(context_id,str) or not context_id.isdecimal() or len(context_id)>19:
            raise ValueError('Invalid context identity')
        if action not in {'pause','resume','stop','abort'}:
            raise ValueError('Unsupported action')
        if any(type(body[k]) is not int or body[k]<0 for k in ('generation','revision')):
            raise ValueError('Invalid observed version')
        old = self.fleet.pending.get(request_id)
        if old is not None:
            if old['_body'] != body:
                raise ValueError('Request identity reused with different content')
            return {k:v for k,v in old.items() if not k.startswith('_')}
        # Refresh authorization at every request; cached detached handles never
        # substitute for current authority-scoped discovery.
        visible = {str(run.context_id):run for run in self.runtime.unfinished_contexts}
        run = visible.get(context_id)
        if run is None:
            raise PermissionError('Context is terminal, unavailable or outside current authority')
        snapshot = run.snapshot()
        current = control_version(snapshot) if 'control_version' in body else snapshot.revision
        expected = body.get('control_version', body['revision'])
        if snapshot.generation != body['generation'] or current != expected:
            raise ValueError('State changed; refresh before submitting')
        if action not in actions(snapshot, own=context_id==str(self.context_id)):
            raise ValueError('Action is unavailable in observed state')
        if any(r['context']==context_id and r['status']=='submitted' for r in self.fleet.pending.values()):
            raise ValueError('A control request is already pending for this context')
        # A minimal request omits all payload-bearing checkpoint/report fields.
        # The existing authority owner validates identity/revision and intent.
        now = datetime.now(timezone.utc)
        intent = ContextRequest(action)
        # These are the existing ContextSnapshot history value types. Apply
        # authorizes its caller independently of the descriptive actor.
        history = tuple(replace(entry, actor=ContextOrigin(entry.actor.context_id)
                                if hasattr(entry.actor, "context_id") else CommandOrigin())
                        for entry in snapshot.history)
        history += (ControlRequested(ContextOrigin(self.context_id), intent, None,
                                     now, snapshot.revision + 1),)
        request_snapshot = replace(snapshot, request=intent,
                                   revision=snapshot.revision + 1, updated_at=now, history=history,
                                   request_duration=None, artifact_context=(), artifacts=(),
                                   config_context=(), records=(), reports=(), report=None,
                                   context_settings=ContextSettings())
        self.runtime.apply(request_snapshot)
        request = {'id':request_id,'context':context_id,'action':action,'status':'submitted',
                   'submitted_at':now.isoformat(),
                   'message':'Submitted through authorized API; completion awaits observation.',
                   '_body':dict(body),'_sent':monotonic()}
        self.fleet.pending[request_id] = request
        while len(self.fleet.pending)>256:
            self.fleet.pending.popitem(last=False)
        return {k:v for k,v in request.items() if not k.startswith('_')}

    def _get(self, path):
        from ._page import PAGE
        parsed = urlsplit(path)
        if parsed.path == '/':
            return 'text/html; charset=utf-8', PAGE.encode()
        if parsed.path == '/viewer.js':
            from ..visualization.renderer import viewer_script
            return 'text/javascript; charset=utf-8', viewer_script().encode()
        if parsed.path.startswith('/api/') and parsed.path != '/api/fleet':
            return 'application/json',json.dumps(self.workspace.get(parsed),allow_nan=False).encode()
        if parsed.path == '/api/fleet':
            from .. import __version__
            serialized_pressures = None
            try:
                pressures = self.runtime.pressures
                local_pressure = pressures[0]
                serialized_pressures = [
                    {**asdict(pressure), 'sampled_at':pressure.sampled_at.isoformat()}
                    for pressure in pressures
                ]
                self.pressure = {**asdict(local_pressure), 'sampled_at':local_pressure.sampled_at.isoformat()}
                self.pressure_gap = None
            except Exception as error:
                self.pressure_gap = 'Pressure sample unavailable: '+type(error).__name__
            payload = self.fleet.payload()
            local = self.execution_location(self.runtime.engine_id)
            for row in payload['contexts']:
                if row.get('execution_location', {}).get('id') == local['id'] or row.get('engine_id') == self.runtime.engine_id:
                    row['execution_location'] = local
            payload.update({'version': __version__, 'execution_locations': self.location_summary(),
                            'local_location': local})
            payload['presentation_sampling'] = {'minimum_interval_seconds': self._projection_interval,
                'coalesced_events': self._coalesced_events,
                'coverage': 'Live display snapshots are sampled; committed records and terminal capture are not sampled.'}
            payload['terminal_recovery'] = {'gap': self._terminal_recovery_gap,
                'pending': self._terminal_recovery_pending,
                'coverage': 'Ordinary-workload terminal summaries only; supervision services are excluded from automatic recovery. Missing full reports, graphs and records cannot be reconstructed.'}
            payload.update({'ready':self.ready,'engine':self.runtime.name,'engine_id':self.runtime.engine_id,
                            'controller':str(self.context_id),'self':self.self_row()})
            payload.update({'active_counts':self.active_counts,'session_outcomes':dict(self.fleet.outcomes),
                            'active_counts_sampled_at':self.active_counts_sampled_at,
                            'observed_work':self.observed_work,
                            'history_session':self.workspace.partition or str(self.context_id),
                            'pressure':self.pressure,'pressure_gap':self.pressure_gap,
                            'pressures':serialized_pressures,
                            'count_gap':self.fleet.count_gap,'persistence':self.workspace.persistence,
                            'states':[state.value for state in __import__('jayrun.context',fromlist=['ContextState']).ContextState]})
            return 'application/json', json.dumps(payload,allow_nan=False).encode()
        match = re.fullmatch(r'/context/(\d+|archive-[0-9a-f]+)/(graph|report|live)',parsed.path)
        if match:
            key,kind=match.groups()
            data=self.workspace.context(key)
            if data.get('loading'):
                raise LookupError('Evidence capture pending; retry observation')
            if kind=='report':
                if data.get('report') is None:raise LookupError(data['report_availability'])
                return 'text/plain; charset=utf-8',data['report'].encode()
            if kind=='live':return 'application/json',json.dumps(self.workspace.live(key),allow_nan=False).encode()
            return 'text/html; charset=utf-8',self.workspace.export(key).encode()
        raise LookupError('Not found')

    async def _http(self, reader, writer):
        task = asyncio.current_task()
        if self.closed or len(self.clients)>=32:
            writer.close();return
        self.clients.add(writer);self.handlers.add(task)
        status=200; kind='application/json'; content=b''
        try:
            async with asyncio.timeout(5):
                raw = await reader.readuntil(b'\r\n\r\n')
                if len(raw)>16384:
                    raise ValueError('Headers too large')
                lines=raw.decode('ascii').split('\r\n')
                method,path,version=lines[0].split(' ')
                if version != 'HTTP/1.1' or not path.startswith('/') or path.startswith('//'):
                    raise ValueError('Invalid request target')
                headers={}
                for line in lines[1:]:
                    if not line:continue
                    key,value=line.split(':',1);key=key.lower()
                    if key in headers:raise ValueError('Duplicate header')
                    headers[key]=value.strip()
                if headers.get('host') != self.authority:
                    raise PermissionError('Host does not match listening address')
                if 'origin' in headers and headers['origin'] != self.url:
                    raise PermissionError('Unauthorized origin')
                if headers.get('sec-fetch-site') not in {None,'same-origin','none'}:
                    raise PermissionError('Cross-site request rejected')
                if method=='GET':
                    parsed = urlsplit(path)
                    if parsed.path == '/api/history-summary':
                        query = parse_qs(parsed.query, keep_blank_values=True)
                        if set(query) - {'engine_session', 'refresh'} or any(len(values) != 1 for values in query.values()):
                            raise ValueError('Unsupported or repeated history-summary filter')
                        refresh = query.get('refresh', ['0'])[0]
                        if refresh not in ('0', '1'):
                            raise ValueError('refresh must be 0 or 1')
                        summary = await self.workspace.history_summary_request(query.get('engine_session', [''])[0], refresh=refresh == '1')
                        kind,content='application/json',json.dumps(summary,allow_nan=False).encode()
                    elif parsed.path == '/api/history' and self.workspace.archive_enabled:
                        history = await self.workspace.history_request(parsed)
                        values = history['rows']
                        result = {**history, 'rows':[history_row(v) for v in values],
                                  'persistence':self.workspace.persistence}
                        kind,content = 'application/json', json.dumps(result,allow_nan=False).encode()
                    elif parsed.path in ('/api/sessions', '/api/session'):
                        query = parse_qs(parsed.query, keep_blank_values=True)
                        if set(query) - ({'id'} if parsed.path == '/api/session' else set()):
                            raise ValueError('Unsupported engine-session query')
                        result = await self.workspace.sessions_request(query.get('id', [None])[-1])
                        kind,content = 'application/json', json.dumps(result,allow_nan=False).encode()
                    else:
                        key = parse_qs(parsed.query).get('id', [''])[0]
                        export_match = re.fullmatch(r'/context/(archive-[0-9a-f]+)/(graph|report|live)', parsed.path)
                        if export_match is not None:
                            key = export_match.group(1)
                        await self.workspace.load_archive(key)
                        kind,content=self._get(path)
                elif method=='POST' and path in {'/api/control','/api/owner'}:
                    if headers.get('origin')!=self.url or headers.get('content-type')!='application/json':
                        raise PermissionError('Same-origin JSON required')
                    if 'transfer-encoding' in headers:raise ValueError('Transfer encoding unsupported')
                    size=int(headers.get('content-length','0'))
                    if not 0<size<=MAX_BODY:raise ValueError('Invalid body size')
                    body=json.loads(await reader.readexactly(size))
                    if path=='/api/owner':
                        if not isinstance(body,dict) or set(body)!={'action'} or body['action'] not in {'stop','abort'}:
                            raise ValueError('Only deliberate owner stop/abort is supported')
                        getattr(self.owner_context,body['action'])()
                        result={'status':'submitted','message':'Dashboard owner shutdown requested; disconnect is expected.'}
                    else:
                        result=self.control(body)
                    content=json.dumps(result,allow_nan=False).encode()
                    status=202
                else:
                    raise LookupError('Unsupported endpoint')
                if len(content)>MAX_RESPONSE:
                    raise ValueError('Response exceeds bounded output; narrow the retained evidence')
        except asyncio.CancelledError:
            raise
        except (Exception,) as error:
            status=403 if isinstance(error,PermissionError) else 404 if isinstance(error,LookupError) else 409
            args=BaseException.args.__get__(error)
            message=args[0][:500] if type(error) in (ValueError,PermissionError,LookupError,RuntimeError,TimeoutError) and len(args)==1 and type(args[0]) is str else type(error).__name__+'; details omitted'
            del args
            content=json.dumps({'error':message}).encode();kind='application/json'
        finally:
            if not task.cancelling():
                try:
                    writer.write((f'HTTP/1.1 {status} Response\r\nContent-Type: {kind}\r\nContent-Length: {len(content)}\r\nConnection: close\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nReferrer-Policy: no-referrer\r\nContent-Security-Policy: default-src \'self\'; script-src \'self\' \'unsafe-inline\'; style-src \'self\' \'unsafe-inline\'; frame-ancestors \'self\'\r\n\r\n').encode()+content)
                    await asyncio.wait_for(writer.drain(),2)
                except (ConnectionError,TimeoutError):pass
            writer.close()
            self.clients.discard(writer);self.handlers.discard(task)
