"""Bounded historical presentation through a borrowed reader, never a writer.

This module deliberately does not import the legacy archive implementation.
Routing IDs are local UI identifiers, not credentials or intrinsic graph IDs.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import re
from time import monotonic

from ..persistence import (DatabaseReader, HistoryQuery, SessionQuery,
                           PersistenceBackpressure, PersistenceTimeout, StorageUnavailable)
from ..persistence.records import ContextHistoryEntry, ContextHistoryHeader
from ..reporting._history import _configuration, _display, history_evidence
from ..visualization.adapters.history import history_payload
from ..visualization.layout import arrange
from ._evidence import safe, _artifact_history_availability, MAX_RECORDS

PAGE_SIZE = 25
CACHE_SECONDS = 2.0
MAX_FILTERS = 8
MAX_PAGES = 64
MAX_DETAIL_BYTES = 4 * 1024 * 1024
_GRAPH_ID = re.compile(r'jrg1:([0-9a-f]{64})\Z')
_IMPORTED_SESSION = re.compile(r'legacy-[0-9a-f]{64}:[0-9a-f]{64}\Z')


def _archive_key(session: str, context_id: str) -> str:
    if (type(session) is not str or not session or len(session) > 256
            or type(context_id) is not str or not context_id or len(context_id) > 128):
        raise ValueError('Invalid historical identity')
    return 'archive-' + json.dumps([session, context_id], separators=(',', ':')).encode().hex()


def _archive_identity(key: str) -> tuple[str, str]:
    if type(key) is not str or not key.startswith('archive-') or len(key) > 2048:
        raise ValueError('Invalid historical reference')
    try:
        value = json.loads(bytes.fromhex(key[8:]))
    except (ValueError, UnicodeError) as error:
        raise ValueError('Invalid historical reference') from error
    if type(value) is not list or len(value) != 2:
        raise ValueError('Invalid historical identity')
    _archive_key(*value)
    return value[0], value[1]


def _presentation(session: str, context_id: str, graph_id: str | None,
                  version: str | None) -> dict:
    """Human labels only; exact identities remain the routing and query keys."""
    imported = bool(_IMPORTED_SESSION.fullmatch(session))
    identity = json.dumps([session, context_id], separators=(',', ':'), ensure_ascii=False)
    reference = ('I-' if imported else 'C-') + sha256(identity.encode()).hexdigest()[:12]
    match = _GRAPH_ID.fullmatch(graph_id or '')
    graph = (f'{match.group(1)[:12]} · v{str(version or "1").removeprefix("v")}' if match else
             'Legacy graph' if imported else 'Graph unavailable')
    return {'display_id': reference, 'graph': graph,
            'graph_id': graph_id, 'imported': imported}


def history_row(value: dict, *, session_id: str | None = None,
                context_id: str | None = None) -> dict:
    row = dict(value['row'])
    row['evidence'] = {'report': value.get('report') is not None,
        'records': len(value.get('records', ())),
        'artifact_entries': sum(len(a.get('history', ())) for a in value.get('artifacts', ())),
        'graph': bool(value.get('graph_available')), 'details': True}
    session = session_id or value.get('session')
    context = context_id or value.get('context_id')
    if session and context:
        row.update(_presentation(session, str(context), value.get('intrinsic_graph_id') or
                                 value.get('graph_id'), row.get('version')))
    row.update(session=session, graph_id=value.get('intrinsic_graph_id') or value.get('graph_id'),
        captured_at=value.get('captured_at'))
    return row


def _header(header: ContextHistoryHeader) -> dict:
    key = _archive_key(header.session_id, header.context_id)
    row = {'id': key, **_presentation(header.session_id, header.context_id, header.graph_id, header.graph_version),
        'version': header.graph_version or '', 'engine_id': header.session_id,
        'state': header.outcome, 'finalized': True, 'archived': True, 'controller': False,
        'actions': [], 'control_version': '', 'iteration': None, 'completed_iterations': None,
        'elapsed_seconds': None, 'remaining_seconds': None, 'fraction': None,
        'created_at': None, 'updated_at': (header.finalized_at or header.captured_at).isoformat(),
        'finished_at': header.finalized_at.isoformat() if header.finalized_at else None, 'failure': None,
        'publication': header.publication}
    return {'context_id': header.context_id, 'archive_id': key, 'session': header.session_id,
        'graph_id': header.graph_id, 'row': row, 'finalized': True, 'archived': True,
        'database_history': True, 'header_only': True, 'records': [], 'artifacts': [],
        'graph_available': header.layout_schema is not None,
        'graph_availability': 'Stored layout advertised; schema/coverage checked on opening detail',
        'evidence_sampled_at': (header.captured_at or header.finalized_at).isoformat(),
        'access': {'observes': 'Granted historical scope', 'controls': 'No', 'scope': 'Read-only Database history'}}


def _present_configuration(values: list[dict]) -> list[dict]:
    return [{**item, 'effective': safe(item['effective'], key=item.get('name') or '')}
            for item in values[:128]]


def _detail(entry: ContextHistoryEntry) -> dict:
    """Detach safe presentation independently of live graphs and today's profiles."""
    value = _header(entry.header)
    value.update(header_only=False, configuration=_present_configuration(_configuration(entry)),
        configuration_retained=type(entry.configurations.decode()) is dict,
        settings={'values': safe(_display(entry.effective_settings.decode())),
                  'requested': safe(_display(entry.requested_settings.decode())),
                  'provenance': 'Captured effective settings and requested overrides'},
        coverage=list(entry.coverage), records_complete=False, report=None,
        report_availability='Stored report unavailable or unsupported',
        graph_available=False, graph_availability=entry.layout_unavailable_reason or 'Stored layout unavailable')
    try:
        evidence = history_evidence(entry)
    except (ValueError, KeyError, TypeError, OverflowError) as error:
        evidence = None
        value['report_availability'] = 'Stored report cannot be attributed safely: ' + type(error).__name__
    if evidence is not None:
        from ..reporting._completed import _format_evidence
        evidence['configuration_omitted'] = max(0, len(evidence['configuration'])-128)
        evidence['configuration'] = _present_configuration(evidence['configuration'])
        for name in ('values', 'requested'):
            evidence['settings'][name] = safe(evidence['settings'][name])
        original_records = evidence['records']
        evidence['records'] = [{**row, 'value': safe(row['value'], key=row['key'])}
                               for row in original_records[:MAX_RECORDS]]
        for row in evidence['records']:
            row['numeric'] = type(row['value']) in (int, float)
        for execution in evidence['executions']:
            for attempt in execution['attempts']:
                attempt['records'] = [safe(row) for row in attempt['records']]
        evidence['coverage']['display'] = 'Existing key-based display redaction and depth/count/text limits apply; free text is not a credential detector. Database evidence is unchanged.'
        value['records_omitted'] = max(0, len(original_records)-MAX_RECORDS)
        value['display_complete'] = original_records == evidence['records']
        value.update(configuration=evidence['configuration'], settings=evidence['settings'],
            records=evidence['records'], artifacts=[{**a, 'coverage': a['history_coverage'], 'payload': 'Excluded from durable history'} for a in evidence['artifacts']],
            records_complete=evidence['records_complete'], record_sequence=evidence['record_sequence'],
            activity=evidence['history'], failure=evidence['failure'],
            failed_step=evidence['failed_step'],
            frozen_progress=evidence['frozen_progress'], timing=evidence['timing'],
            evidence_coverage=evidence['coverage'])
        row = value['row']
        row.update(iteration=evidence['iteration_count'], completed_iterations=evidence['completed_iterations'],
            elapsed_seconds=evidence['elapsed_wall_seconds'], created_at=evidence['created_at'],
            failure=evidence['failure'], generation=evidence['generation'], revision=evidence['revision'])
        progress = evidence['frozen_progress']
        # Project the captured tracker values, never consult current profiles or
        # reinterpret a sum of step work as a whole-graph wall-clock prediction.
        for target, name, unit in (
                ('fraction', 'estimated_fraction', True),
                ('remaining_seconds', 'estimated_remaining_seconds', False),
                ('confidence', 'confidence', True)):
            number = progress.get(name)
            if type(number) in (int, float) and math.isfinite(number) and number >= 0 and (not unit or number <= 1):
                row[target] = number
        for name in ('sample_count', 'max_iterations'):
            number = progress.get(name)
            if type(number) is int and number >= 0:
                row[name] = number
        row['sampled_at'] = progress.get('observed_at')
        row['stop_requested'] = evidence['stop_requested']
        # Formatting never rebuilds a runtime report. Older capture lacks an exact
        # completed count; retain that limitation instead of inferring success.
        formatted = dict(evidence)
        if formatted['completed_iterations'] is None:
            formatted['completed_iterations'] = 'unknown (not captured)'
        try:
            value['report'] = _format_evidence(formatted)
            value['report_availability'] = 'Frozen stored evidence; original record classes were not captured'
        except (ValueError, TypeError, KeyError):
            value['report_availability'] = 'Formatted report unavailable under its schema/export bounds; inspect structured evidence'
    raw = entry.evidence.decode()
    if type(raw) is dict and raw.get("schema") == "jayrun.legacy-dashboard/1":
        source = raw.get("source")
        if type(source) is dict:
            # Preserve the old display contract without relabeling its effective
            # configuration, report completeness, timestamps, or live authority.
            value["legacy_evidence"] = safe(_display(source))
            value["report_availability"] = "Legacy display evidence; original report/configuration completeness is unknown"
            if type(source.get("report")) is str:
                value["report"] = safe(source["report"])
            if type(source.get("configuration")) is list:
                value["configuration"] = safe(_display(source["configuration"]))
            if type(source.get("settings")) is dict:
                value["settings"] = safe(_display(source["settings"]))
            value["row"]["evidence_lifetime"] = "Legacy imported observation"
            value["row"]["captured_at"] = entry.header.captured_at.isoformat() if entry.header.captured_at else None
            value["row"]["finished_at"] = None
    try:
        payload = arrange(history_payload(entry, evidence=evidence))
        value.update(captured_graph={'definition': payload}, graph_available=True,
                     graph_availability='Exact stored layout; no live definition or registry lookup',
                     artifact_history_availability=_artifact_history_availability(
                         retained=bool(value['artifacts']), finalized=True,
                         declared_count=len(payload['artifacts'])))
    except (ValueError, KeyError, TypeError, OverflowError) as error:
        value['graph_availability'] = 'Stored layout/association unavailable: ' + str(error)[:256]
    value.setdefault('artifact_history_availability', _artifact_history_availability(
        retained=bool(value['artifacts']), finalized=True))
    # Large details remain inspectable in bounded pieces; never pretend omitted
    # topology is complete. Full Database entries remain available to their owner.
    if len(json.dumps(value, allow_nan=False).encode()) > MAX_DETAIL_BYTES:
        value.pop('captured_graph', None)
        value.update(graph_available=False, graph_availability='Historical graph exceeds 4 MiB dashboard detail budget')
    if len(json.dumps(value, allow_nan=False).encode()) > MAX_DETAIL_BYTES:
        for field in ('records', 'artifacts', 'activity', 'report', 'configuration'):
            value[field] = None if field == 'report' else []
        value.update(records_complete=False, capture_gap='Historical detail exceeds 4 MiB display budget; large sections omitted',
                     artifact_history_availability='Artifact history omitted by the 4 MiB historical display bound.')
    if len(json.dumps(value, allow_nan=False).encode()) > MAX_DETAIL_BYTES:
        value = {**_header(entry.header), 'capture_gap': 'Historical detail exceeds display budget; use scoped Database reader'}
    return value


class _HistorySource:
    """Single presentation-lane reader; bounded header caches and cursor windows.

    Methods run on the workspace's existing presentation executor, not its event
    loop. Database retains its own handle lane. Cache hits recheck the grant;
    this component has no open, close, flush, prune or publication operation.
    """
    def __init__(self, reader: DatabaseReader):
        if type(reader) is not DatabaseReader:
            raise TypeError('history must be a DatabaseReader')
        self.reader = reader
        self.page_size = min(PAGE_SIZE, reader.max_page_size)
        self.pages: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()
        self.cursors: OrderedDict[tuple, dict[int, str | None]] = OrderedDict()
        self.summaries: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self.session_cache: tuple[float, dict] | None = None

    def check(self) -> None:
        self.reader._check_access()

    def query(self, query: dict[str, str]) -> dict:
        self.check()
        allowed = {'page', 'sort', 'search', 'state', 'session', 'engine_session', 'graph_id', 'date', 'capability', 'workloads'}
        if set(query) - allowed:
            raise ValueError('Unsupported history filter')
        page = int(query.get('page') or 0)
        if not 0 <= page < MAX_PAGES:
            raise ValueError('History cursor window exceeded; refine filters or restart from page 1')
        if query.get('capability', '') not in ('', 'unknown', 'neither', 'controls', 'observes'):
            raise ValueError('Unsupported historical capability filter')
        if query.get('sort', 'newest') not in ('oldest', 'newest'):
            raise ValueError('Unsupported history sort')
        session = query.get('session') or query.get('engine_session') or None
        if query.get('session') and query.get('engine_session') and query['session'] != query['engine_session']:
            raise ValueError('Conflicting engine-session filters')
        since = datetime.fromisoformat(query['date']).replace(tzinfo=timezone.utc) if query.get('date') else None
        filters = (session, query.get('graph_id') or None, query.get('state') or None,
                   query.get('sort', 'newest'), query.get('search') or None, query.get('date') or None)
        key = (filters, page, query.get('capability') or '')
        cached = self.pages.get(key)
        if cached is not None and monotonic()-cached[0] < CACHE_SECONDS:
            self.pages.move_to_end(key)
            return json.loads(json.dumps(cached[1]))
        cursors = self.cursors.setdefault(filters, {0: None})
        self.cursors.move_to_end(filters)
        while len(self.cursors) > MAX_FILTERS:
            self.cursors.popitem(last=False)
        if page not in cursors:
            raise ValueError('History page cursor expired; visit page 1 and use Next')
        if query.get('capability') in ('controls', 'observes'):
            # Historical rights never imply live authority, even for an old
            # controller outcome. The UI filter refers to live capabilities.
            result = {'rows': [], 'total': 0, 'has_more': False, 'page': page, 'boundary': None}
        else:
            try:
                response = self.reader.query_contexts(HistoryQuery(session_id=session, graph_id=filters[1],
                    outcome=filters[2], since=since, limit=self.page_size, cursor=cursors[page],
                    descending=filters[3] == 'newest', search=filters[4]), timeout=1.0)
            except (PersistenceTimeout, PersistenceBackpressure, StorageUnavailable) as error:
                self.check()
                # Operational unavailability is not an empty complete history.
                # Reuse only this exact-filter cached header page, visibly stale.
                stale = json.loads(json.dumps(cached[1])) if cached is not None else {
                    'rows': [], 'total': None, 'has_more': False, 'page': page,
                    'page_size': self.page_size, 'sessions': [], 'sessions_complete': False,
                    'graphs': [], 'boundary': None}
                stale.update(stale=True, query_error=type(error).__name__,
                    coverage='Historical query unavailable; retained headers may be stale and publication is not acknowledged',
                    scope='Explicit reader scope; operational read gap')
                if self.session_cache is not None:
                    stale['sessions'] = [v['session_id'] for v in self.session_cache[1]['sessions']]
                    stale['sessions_complete'] = False
                self.pages[key] = (monotonic(), stale)
                self.pages.move_to_end(key)
                while len(self.pages) > MAX_FILTERS:
                    self.pages.popitem(last=False)
                return stale
            # Restarting a head page or a pruning-changed continuation cannot
            # leave descendant pages cached under another publication boundary.
            if page == 0 or cursors.get(page+1) != response.next_cursor:
                for number in tuple(cursors):
                    if number > page:
                        del cursors[number]
                for cache_key in tuple(self.pages):
                    if cache_key[0] == filters and cache_key[1] > page:
                        del self.pages[cache_key]
            if response.next_cursor is not None and page+1 < MAX_PAGES:
                cursors[page+1] = response.next_cursor
            else:
                cursors.pop(page+1, None)
            result = {'rows': [_header(row) for row in response.items],
                'total': len(response.items) if page == 0 and response.next_cursor is None else None,
                'has_more': response.next_cursor is not None, 'page': page, 'boundary': response.boundary}
        try:
            sessions = self.sessions()
        except (PersistenceTimeout, PersistenceBackpressure, StorageUnavailable) as error:
            self.check()
            sessions = json.loads(json.dumps(self.session_cache[1])) if self.session_cache is not None else {'sessions': []}
            sessions['complete'] = False
            result['session_query_error'] = type(error).__name__
        result.update(page_size=self.page_size, sessions=[v['session_id'] for v in sessions['sessions']],
            sessions_complete=sessions['complete'], sessions_omitted=0 if sessions['complete'] else None,
            graphs=[{'id': g, 'key': g, 'version': v} for g, v in
                    dict.fromkeys((row['graph_id'], row['row']['version']) for row in result['rows'] if row['graph_id'])],
            graphs_omitted=None, scope='Explicitly granted Database history; bounded header-only pages',
            coverage='Order is committed publication, not execution start time. Search matches case-sensitive header identities/version. Totals are unknown unless the first page is complete. Historical headers have no live capability or dashboard/workload classification; workloads filter applies only to live lists.')
        self.check()
        self.pages[key] = (monotonic(), result)
        self.pages.move_to_end(key)
        while len(self.pages) > MAX_FILTERS:
            self.pages.popitem(last=False)
        return json.loads(json.dumps(result))

    def summary(self, session: str, *, refresh: bool = False) -> dict:
        self.check()
        if session and not self.reader._allowed(session):
            raise PermissionError('History summary unavailable in the granted session scope')
        cached = self.summaries.get(session)
        if not refresh and cached is not None and monotonic()-cached[0] < CACHE_SECONDS:
            return json.loads(json.dumps(cached[1]))
        page = self.reader.query_contexts(HistoryQuery(session_id=session or None, limit=min(100, self.reader.max_page_size), descending=True), timeout=1.0)
        counts: dict[str, int] = {}
        for header in page.items:
            counts[header.outcome] = counts.get(header.outcome, 0)+1
        result = {'counts': counts, 'total': len(page.items), 'complete': page.next_cursor is None,
            'source': 'All retained committed headers' if page.next_cursor is None else f'Most recent {len(page.items)} committed headers',
            'coverage': 'One publication-ordered committed-header snapshot. A bounded recent window can change as new outcomes arrive; these are not lifetime totals.'}
        self.check()
        self.summaries[session] = (monotonic(), result)
        self.summaries.move_to_end(session)
        while len(self.summaries) > MAX_FILTERS:
            self.summaries.popitem(last=False)
        return json.loads(json.dumps(result))

    def sessions(self) -> dict:
        self.check()
        if self.session_cache is not None and monotonic()-self.session_cache[0] < CACHE_SECONDS:
            return json.loads(json.dumps(self.session_cache[1]))
        page = self.reader.query_sessions(SessionQuery(limit=min(100, self.reader.max_page_size), descending=True), timeout=1.0)
        result = {'sessions': [_display(asdict(header)) for header in page.items],
            'complete': page.next_cursor is None, 'next_cursor': page.next_cursor,
            'boundary': page.boundary, 'coverage': 'At most 100 authorized recent engine sessions; no liveness inferred from absent shutdown'}
        self.check()
        self.session_cache = (monotonic(), result)
        return json.loads(json.dumps(result))

    def session(self, key: str) -> dict:
        self.check()
        record = self.reader.get_session(key, timeout=1.0)
        if record is None:
            raise LookupError('Engine session unavailable in the granted scope')
        result = {'header': _display(asdict(record.header)), 'settings': _display(record.settings.decode()),
            'environment': _display(record.environment.decode()), 'shutdown': _display(record.shutdown.decode()),
            'coverage': list(record.coverage), 'authority': 'Read-only; shutdown absence does not establish liveness'}
        self.check()
        return result

    def detail(self, key: str) -> dict | None:
        session, context = _archive_identity(key)
        record = self.reader.get_context(session, context, timeout=1.0)
        result = None if record is None else _detail(record)
        self.check()
        return result
