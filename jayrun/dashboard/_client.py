"""Dashboard transport, navigation and live actions around shared run panels."""
from importlib.resources import files
from ..visualization._help import _script as _help_script
from ..visualization._workspace import panels_script

CLIENT = panels_script() + r'''
(()=>{'use strict';
const $=s=>document.querySelector(s), make=(tag,text,attrs={})=>{const n=document.createElement(tag);if(text!=null)n.textContent=String(text);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);return n}, main=$('#main');
let fleet=null,stale=true,received=0,route='',epoch=0,serviceEpoch=0,timer,disposed=false,activeFetch=new Set(),reads=new Map(),list=null,workspace=null,overview=null,graphList=null,engines=null,lastGraphNavigation=null;
const routeStates=JSON.parse(sessionStorage.getItem('jayrun.routes')||'{}'), pending=new Map(), pins=JSON.parse(sessionStorage.getItem('jayrun.pins')||'{}');
// Apply the new default to tabs that retained the previous default as a filter.
if(sessionStorage.getItem('jayrun.sort-default')!=='oldest'){
 for(const kind of ['contexts','history'])if(routeStates[kind])routeStates[kind]={...routeStates[kind],sort:'oldest',page:0};
 const [path,search]=location.hash.slice(1).split('?');
 if(['/contexts','/history'].includes(path)){
  const query=new URLSearchParams(search||'');query.set('sort','oldest');
  history.replaceState(null,'','#'+path+'?'+query);
 }
 sessionStorage.setItem('jayrun.routes',JSON.stringify(routeStates));
 sessionStorage.setItem('jayrun.sort-default','oldest');
}
let connectionLost=false,connectionFailure='',pageState=null,polling=false;
// Last rendered responses are presentation-only and scoped to the current service.
const lastViewResponses=new Map();
const chartVisibility=new Map(),pausedDisplays=new Map();
const runPanels=globalThis.JayrunRunPanels.create({make,note,button,sectionHeading,replaceStable,download,copyText:(...args)=>copyText(...args),shortFailure,
 workspace:()=>workspace,pins,chartVisibility,pausedDisplays,serviceEpoch:()=>serviceEpoch,
 locationDetails,accessBox,requests:()=>fleet?.requests||[],savePins:value=>sessionStorage.setItem('jayrun.pins',JSON.stringify(value))});
const {duration,localTime,tree,conciseValue,rawDetails,configurationCard,activitySummary,activityList,stateBadge,contextProgress,tabKeys,renderArtifacts,artifactHistoryTable,identityFact,renderSummary,renderFailure,recordChart,renderRecords}=runPanels;

const theme=()=>document.documentElement.dataset.theme||'light';
function setTheme(value){value=['light','dark'].includes(value)?value:'light';document.documentElement.dataset.theme=value;localStorage.setItem('jayrun.theme',value);document.querySelectorAll('input[name=theme]').forEach(n=>n.checked=n.value===value);document.querySelectorAll('jayrun-graph').forEach(n=>n.setAttribute('theme',value))}
document.querySelector('#theme-control').replaceWith(globalThis.JayrunRunPanels.themeControl(localStorage.getItem('jayrun.theme')||'light',setTheme));
setTheme(localStorage.getItem('jayrun.theme')||'light');
const dashboardHeader=document.querySelector('.dashboard-header');
new ResizeObserver(()=>document.documentElement.style.setProperty('--dashboard-header-height',dashboardHeader.getBoundingClientRect().height+'px')).observe(dashboardHeader);
async function api(path,body){
 if(!body&&reads.has(path))return reads.get(path).promise;
 const c=new AbortController();activeFetch.add(c);let timedOut=false;
 const timeout=setTimeout(()=>{timedOut=true;c.abort()},5000);
 const promise=(async()=>{try{
  const r=await fetch(path,{signal:c.signal,...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});
  const value=await r.json();if(!r.ok){const e=Error(value.error||'Request rejected');e.rejected=true;throw e}return value;
 }catch(e){if(timedOut)throw Error('Request timed out');throw e}
 finally{clearTimeout(timeout);activeFetch.delete(c);if(reads.get(path)?.controller===c)reads.delete(path)}})();
 if(!body)reads.set(path,{promise,controller:c});return promise;
}
function cancelReads(keep){for(const [path,r]of reads)if(path!=='/api/fleet'&&!keep(path)){reads.delete(path);r.controller.abort()}}
// Reconcile presentation nodes without replacing focused buttons, open details,
// scroll containers or filter inputs. Callbacks are refreshed on retained nodes.
function sync(target,source){
 if(target.nodeType!==source.nodeType||target.nodeName!==source.nodeName){target.replaceWith(source);return}
 if(target.nodeType===3){if(target.data!==source.data)target.data=source.data;return}
 if(target.hasAttribute('data-copy-value')||source.hasAttribute('data-copy-value')){
  if(target.getAttribute('data-copy-value')===source.getAttribute('data-copy-value')&&target.getAttribute('data-copy-label')===source.getAttribute('data-copy-label'))return;
  target.replaceWith(source);return; // A changed identity invalidates pending copy feedback.
 }
 help.reconcile(target,source);
 const open=target.tagName==='DETAILS'?target.open:null;
 for(const a of [...target.attributes])if(!source.hasAttribute(a.name))target.removeAttribute(a.name);
 for(const a of source.attributes)if(target.getAttribute(a.name)!==a.value)target.setAttribute(a.name,a.value);
 for(const event of ['onclick','onkeydown','onmouseenter','onfocus'])target[event]=source[event];
 if('disabled'in target)target.disabled=source.disabled;
 let i=0;for(const child of [...source.childNodes]){const old=target.childNodes[i];if(old)sync(old,child);else target.append(child);i++}
 while(target.childNodes.length>i)target.lastChild.remove();if(open!==null)target.open=open;
}
function replaceStable(target,source){if(target.firstChild)sync(target.firstChild,source);else target.append(source)}
function readNotice(target,message,retry){let n=target.querySelector(':scope > .read-status');if(!n){n=make('div',null,{class:'read-status',role:'status'});target.prepend(n)}n.replaceChildren(note(message,true),button('Retry',retry));return n}
function clearReadNotice(target){target.querySelector(':scope > .read-status')?.remove()}
function note(text,error=false){return make('p',text,{class:'notice'+(error?' error':'')})}
function button(text,fn,attrs={}){const n=make('button',text,attrs);n.onclick=fn;return n}
function sampleTimestamp(stamp){
 const time=make('time',null,{datetime:stamp||'',title:stamp||'Not reported'}),date=new Date(stamp||'');
 if(!stamp||!Number.isFinite(date.getTime())){time.textContent=stamp?'Unavailable':'—';return time}
 const parts=new Intl.DateTimeFormat(undefined,{year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',timeZoneName:'short'}).formatToParts(date);
 time.append(make('span',parts.filter(p=>p.type!=='timeZoneName').map(p=>p.value).join('').trim()),make('span',parts.find(p=>p.type==='timeZoneName')?.value||''));return time;
}
function mountPageStatus(parent){
 const region=make('div',null,{class:'page-notification'}),banner=make('div',null,{class:'stale-banner'}),message=make('span','',{role:'status','aria-live':'polite'}),retry=button('Retry',()=>retryPage());
 banner.append(message,retry);region.append(banner);parent.append(region);banner.hidden=true;
 pageState={region,banner,message,retry,loaded:false,issues:new Map(),shell:null,empty:null};return region;
}
function pageIssue(key,message,retry){if(!pageState)return;pageState.issues.set(key,{message,retry});updatePageStatus()}
function pageAccepted(key){if(!pageState)return;pageState.loaded=true;if(key)pageState.issues.delete(key);updatePageStatus()}
async function retryPage(){const current=pageState;if(!current)return;await poll();if(pageState!==current||connectionLost)return;for(const issue of [...current.issues.values()])await issue.retry()}
function updatePageStatus(){
 const p=pageState;main.toggleAttribute('data-disconnected',Boolean(connectionLost&&p));if(!p)return;
 const issue=p.issues.values().next().value,failed=connectionLost||Boolean(issue),initial=failed&&!p.loaded;
 const text=connectionLost?'Connection lost — showing last received data.':'Could not refresh this view — showing last received data.';
 const focused=p.restoreFocus||p.banner.contains(document.activeElement)||p.empty?.contains(document.activeElement);
 if(p.message.textContent!==(failed&&!initial?text:''))p.message.textContent=failed&&!initial?text:'';
 if(p.footer)p.footer.style.visibility=initial?'hidden':'';
 p.banner.title=connectionLost?connectionFailure:issue?.message||'';p.banner.hidden=!failed||initial;
 if(initial&&p.shell){
  if(!p.empty){p.empty=make('div',null,{class:'initial-view-error',role:'status'});p.empty.append(make('strong','Data unavailable'),make('span','The dashboard could not load this view.'),button('Retry',()=>retryPage()));p.shell.append(p.empty)}
  p.empty.hidden=false;p.empty.title=connectionLost?connectionFailure:issue?.message||'';
 }else if(p.empty)p.empty.hidden=true;
 if(focused&&!failed){p.restoreFocus=false;const target=p.shell?.querySelector('.table-wrap:not([hidden])')||p.region;target.tabIndex=-1;target.focus({preventScroll:true})}
}
function workStatus(row){const node=$('#work-state');node.replaceChildren(stateBadge(row),make('span',' '+row.graph+(row.display_id?'':' · '+row.version)));replaceStable($('#work-progress'),contextProgress(row))}

function accessBox(access){const d=make('div');d.append(make('h3','Cross-context access'),make('span','Observes: '+(access?.observes||'Unknown'),{class:'badge','data-help':'evidence.access'}),' ',make('span','Controls: '+(access?.controls||'Unknown'),{class:'badge'}),make('p',access?.scope||'The target’s access to other contexts is not available.',{class:'muted'}));return d}

// Display metadata never grants authority or implies a physical engine_id.
function locationOf(row){return row?.execution_location||{id:row?.engine_id||'unknown',engine_id:row?.engine_id||null,engine_name:null,physical_machine:null,provenance:'Recorded routing owner; physical host unknown'}}
function locationName(value){return value.engine_name|| (value.engine_id?'Engine '+sessionIdentity(value.engine_id):'Unknown location')}
function sessionIdentity(value){
 const full=String(value||'');if(!full)return 'Unknown engine session';if(full.length<=30)return full;
 const separator=Math.max(full.indexOf('@'),full.indexOf(':'));
 const prefix=separator>0?full.slice(0,Math.min(separator+1,18)):full.slice(0,12);
 return prefix+'…'+full.slice(-8);
}
function locationCell(row){const v=locationOf(row),box=make('div',null,{class:'provenance'});box.append(make('span',locationName(v)),make('small',v.physical_machine||'Physical host unknown'));box.title=[v.engine_id||'Engine instance unknown',v.provenance||''].join('\n');return box}
function locationDetails(row){const v=locationOf(row);return {engine_name:v.engine_name||'Unknown',engine_session:v.engine_id||'Unknown',physical_machine:v.physical_machine||'Unknown',identity_coverage:v.identity_omitted?'Long identity display truncated; grouping retains full identity':v.provenance||'Captured execution owner'}}
function identityText(row){const value=row.display_id||row.id;return make('span',value,{class:'context-identity',title:value})}
// Shared portable help owns behavior and generic meanings. Only dashboard
// navigation/control meanings extend the same private catalog here.
const help=__JAYRUN_HELP__.mount(document,[
 ['dashboard.controls',{brief:'Controls submit authority-checked requests, not completed transitions.',detail:'Pause takes effect at a scheduling boundary; already admitted work may finish. Resume permits paused work to continue. Stop prevents another iteration after accepted work drains. Abort prevents further dispatch and drains running work. Neither forcibly kills arbitrary executing code. Availability and disabled reasons follow visible observations.'}],
 ['dashboard.pause',{brief:'Pause takes effect at a scheduling boundary; admitted work may finish first.',detail:'A pause request is not a completed state transition. Wait for the observed PAUSED state. Context wall elapsed can continue while work estimates are held.'}],
 ['dashboard.resume',{brief:'Resume permits paused work to continue; observed state confirms the transition.',detail:'Resume uses existing control authority. It does not reset context wall elapsed or promise immediate dispatch.'}],
 ['dashboard.stop',{brief:'Stop drains the accepted iteration and prevents another; it does not forcibly kill executing code.',detail:'Failure or abort still determines the actual outcome. A request is not a completed transition; watch the visible observed state and request status.'}],
 ['dashboard.abort',{brief:'Abort prevents further dispatch and drains running work; it does not forcibly kill arbitrary code.',detail:'The confirmation states the destructive consequence. Help never submits a request or changes authority, and already executing code may still complete.'}],
 ['dashboard.session',{brief:'An engine session is an engine incarnation, not a physical host.',detail:'A capture session identifies a dashboard observation partition. Session labels describe retained provenance and selected scope, not access grants or physical-engine_id discovery.'}],
 ['dashboard.history',{brief:'History combines scoped retained terminal evidence with bounded recent observations; it is not cumulative engine activity.',detail:'Database rows follow committed publication ordering. Search and filters use full context, graph-version and session identities even when labels are abbreviated. Totals describe matching committed headers; page completeness and older or pruned evidence are not inferred. Historical rows are read-only and may lack capability or workload detail. Recent observations are bounded and may not yet have verified publication status. Database and Recent rows reconcile by routing identity so one context is not shown twice.'}],
 ['dashboard.summary-pin',{brief:'Shows this record’s latest retained value in this context’s Summary.',detail:'Saved only in this browser tab. Pinning does not change execution, recording, table filtering or other contexts.'}],
 ['dashboard.refresh-unavailable',{brief:'Refresh is unavailable because database persistence is disabled.',detail:'The dashboard still shows retained observations. Database Refresh requires an enabled historical reader.'}],
 ['dashboard.refresh',{brief:'Reload retained history from the database.',detail:'Repeated pending requests coalesce and stale responses are ignored. Refresh does not flush persistence, recompute progress or grant control. Unavailable history is not zero. Visible loading, failure and stale notices describe the last attempted read.'}],
 ['dashboard.active',{brief:'Current authorized contexts observed in this dashboard session.',detail:'Counts come from the complete authorized current-context observation, excluding this dashboard, and can include work executing on multiple Engines. The dashboard itself remains separately identifiable in Contexts. Completed contexts appear in retained history.'}],
 ['dashboard.history-outcomes',{brief:'Retained terminal outcomes are read from the granted historical source.',detail:'These counts follow committed retained evidence visible to this controller, not cumulative engine activity or lifetime totals. Refresh performs the existing explicit historical read; unavailable or incomplete evidence is not inferred as zero.'}],
 ['dashboard.pressure',{brief:'Reported scheduling pressure, one producer per row. Context counts use a separate source.',detail:'The local row is authoritative for this engine. Remote rows are retained reports; identity does not authenticate a producer or grant control. Tasks in use may include ordinary and supervising work. Ordinary and supervising capacities are separate, not utilization ratios. Memory admission pressure is a boolean scheduler signal, not RAM usage or health. No device/GPU pressure is available. Sampled is producer time, not receipt time. Older sample appears after 30 seconds relative to the local sample clock, advanced with monotonic browser elapsed time between successful samples. Remote clocks may differ; this does not establish that an engine is offline. A sample more than 30 seconds ahead has unknown age (time mismatch). Failed reads do not renew timestamps or discard last displayed values. No complete-fleet or liveness claim is made.'}],
 ['dashboard.observed-work',{brief:'Authorized observed context states, grouped by current execution owner.',detail:'These use the same complete authorized context pass and dashboard exclusion as Overview, grouped by canonical execution-owner identity, never pressure counters or paginated Contexts rows. Zero means no contexts in that state within an observed group, not an idle engine. Pressure-only engines have no observed context detail and show dashes. Unattributed work remains in overall counts without inventing an engine. History outcomes remain a separate retained historical read.'}],
 ['dashboard.engines',{brief:'Distinct observed engine incarnations, not active connections or healthy hosts.',detail:'Includes this engine, retained pressure producers, and current execution-engine_id identities from the authorized context pass. Historical session names and unattributed work are excluded. Full identities determine grouping; shortened labels are display-only. Rows open details with the full canonical engine_id identity. An incarnation is not necessarily a physical host. Pressure uses producer-reported PressureSnapshots; Observed work uses authorized ContextSnapshots. They may legitimately disagree in time or scope. Device/GPU pressure is not included. Observation does not prove liveness, fleet completeness, physical host/device identity or control authority.'}],
 ['dashboard.locations',{brief:'Observed execution locations are bounded routing identities, not discovered physical hosts.',detail:'Engine sessions identify routing incarnations; display coverage never grants authority or establishes complete physical-engine_id discovery.'}],
 ['dashboard.failures',{brief:'Recently observed failures visible to this controller.',detail:'The bounded list follows current retained observations. Older, pruned or uncaptured failures may not appear. Long lists scroll within this section without changing navigation.'}],
 ['dashboard.control-outcomes',{brief:'Recent control requests and their observed outcomes.',detail:'Submitting a request does not mean the transition has completed. The bounded list records whether the requested action was observed, rejected or remains unconfirmed; absence does not establish lifetime absence.'}],
 ['dashboard.overview',{brief:'Visible work and outcomes observed in this dashboard session.',detail:'Overview always summarizes the complete current authorized context observation, excluding this dashboard; work may execute on multiple Engines. Retained history outcomes use their separate bounded/history source and Refresh behavior. Observed engines is the union of the local incarnation, current authorized execution-engine_id identities and retained pressure reports. Observed does not prove liveness or complete fleet membership. Open Engines for per-engine pressure and observed work; its filters never change Overview.'}],
 ['dashboard.contexts',{brief:'Lists currently observed nonterminal work in the selected scope.',detail:'Quick details and the workspace use retained observations. Capability labels do not confer permission. Engine-session labels are not physical hosts. Control requests are confirmed by observed state, not by clicking a button.'}],
 ['dashboard.graphs',{brief:'Lists captured registered and local definitions, not every graph that could exist.',detail:'Opening a captured definition does not execute it. Registry key/version, intrinsic graph ID and presentation identity remain distinct. Related contexts follow the current visible scope.'}],
 ['dashboard.stop-owner',{brief:'Stops this controller and closes its local dashboard service.',detail:'This is separate from controlling a selected workload. The existing confirmation explains the consequence; viewing help does not stop the dashboard.'}]
],['graph.reiteration','graph.requirements','progress.fraction','progress.elapsed','evidence.access','evidence.artifacts','evidence.retained','evidence.records','evidence.configuration','evidence.settings','evidence.activity','evidence.history','evidence.report','graph.identity','graph.captured','view.theme','action.copy']);
const copyText=__JAYRUN_COPY__;
function helpButton(topic,label,variant=''){return help.info(topic,label,variant)}
function sectionHeading(title,topic,label){const heading=make('div',null,{class:'section-heading'});heading.append(make('h2',title));if(topic)heading.append(helpButton(topic,label||'About '+title));return heading}
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&engines?.selected&&!document.querySelector('dialog[open]')){closeEngineDetails();e.preventDefault();return}if(e.key==='Escape'&&!document.querySelector('dialog[open]')&&e.composedPath()[0]?.getRootNode()===document&&list?.selected){clearQuickSelection();e.preventDefault()}},true);
window.addEventListener('resize',()=>{if(workspace?.tab==='records'&&workspace.data)renderRecords(workspace.data,workspace.body)});
// Keep the select and its option nodes alive. While a native popup has focus,
// defer option changes to blur so a polling response cannot change its target.
function reconcileOptions(select,options,value){
 const signature=JSON.stringify([options,value]);if(select.dataset.signature===signature)return;
 const apply=()=>{const ids=new Set(options.map(([id])=>id));for(const option of [...select.options])if(!ids.has(option.value))option.remove();options.forEach(([id,label],i)=>{let n=[...select.options].find(o=>o.value===id);if(!n)n=make('option',null,{value:id});if(n.textContent!==label)n.textContent=label;n.title=id;if(select.options[i]!==n)select.insertBefore(n,select.options[i]||null)});select.value=value;select.dataset.signature=signature};
 if(document.activeElement===select){select.pendingOptions=apply;if(!select.optionBlur){select.optionBlur=true;select.addEventListener('blur',()=>{const pending=select.pendingOptions;select.pendingOptions=null;pending?.()})}}else{select.pendingOptions=null;apply();}
}

function saveRoute(){if(graphList?.catalog){const c=graphList.catalog;routeStates.graphs={...c.state,tableScroll:c.scroll?.scrollTop||0};sessionStorage.setItem('jayrun.routes',JSON.stringify(routeStates))}if(engines){routeStates.engines={tab:engines.tab,search:engines.search,...engines.filters,scrolls:Object.fromEntries(Object.entries(engines.views).map(([key,v])=>[key,v.scroll.hidden?(v.savedScroll||[0,0]):[v.scroll.scrollTop,v.scroll.scrollLeft]]))};sessionStorage.setItem('jayrun.routes',JSON.stringify(routeStates))}if(route&&list){routeStates[route]={...list.filters,page:list.page,scroll:window.scrollY,tableScroll:list.body.closest('.table-wrap')?.scrollTop||0};sessionStorage.setItem('jayrun.routes',JSON.stringify(routeStates))}}
function go(path){saveRoute();location.hash=path}
function openList(kind,filters={}){
 // A drill-down is a fresh query. Ordinary Back/sidebar navigation still restores
 // the current list's filters, page and scroll. Quick selection is visit-local.
 saveRoute();list=null;routeStates[kind]={search:'',state:'',graph_id:'',capability:'',sort:'oldest',session:'',date:'',workloads:'',engine_session:'',page:0,...filters};
 sessionStorage.setItem('jayrun.routes',JSON.stringify(routeStates));location.hash='/'+kind+'?'+new URLSearchParams(filters);
}
function contextLink(id,tab='graph',origin=list?.kind||'contexts'){return '/context/'+id+'/'+tab+'?origin='+origin}
function confirmAction(title,text,fn){$('#confirm-title').textContent=title;$('#confirm-text').textContent=text;$('#confirmation').showModal();$('#confirm-yes').onclick=()=>{$('#confirmation').close();fn()};$('#confirm-cancel').onclick=()=>$('#confirmation').close()}
function controlIcon(action){const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');const path=document.createElementNS(ns,'path');path.setAttribute('d',{pause:'M6 4h4v16H6zM14 4h4v16h-4z',resume:'M7 3v18l16-9z',stop:'M4 4h16v16H4z',abort:'M12 2 1 22h22L12 2zm-1 7h2v6h-2zm0 8h2v2h-2z'}[action]);path.setAttribute('fill','currentColor');svg.append(path);return svg}
function lifecycle(row,readonly=false){
 const box=make('div'),group=make('div',null,{class:'controls workload-controls'}),message=make('p','',{class:'reason',role:'status'});box.append(group,message);
 if(readonly||row.archived){box.append(note('Historical evidence · read-only'));return box}
 if(row.controller){box.append(note('This dashboard · use the separate Stop dashboard action above.'));return box}
 const actions=row.actions||[],p=pending.get(row.id)||fleet?.requests.find(r=>r.context===row.id&&r.status==='submitted');
 const toggle=p?.action==='resume'?'resume':row.state==='paused'?'resume':'pause';
 for(const action of [toggle,'stop','abort']){
  let label=action[0].toUpperCase()+action.slice(1);if(p?.action===action)label+=' requested';
  const b=button(null,()=>{const run=()=>send(row,action,message);if(action==='abort')confirmAction('Abort context '+row.id,'Prevent further dispatch and drain running work. This does not forcibly kill arbitrary executing code.',run);else run()},{'data-action':action,'data-help':'dashboard.'+action,'aria-label':label});
  b.append(controlIcon(action),make('span',label));b.disabled=stale||Boolean(p)||!actions.includes(action);
  group.append(b);
 }
 group.append(helpButton('dashboard.controls','About Pause, Stop and Abort'));
 const receiptKey='jayrun.control.'+row.id,receipt=sessionStorage.getItem(receiptKey)||'';
 if(/^(pause|resume|abort) · observed$/i.test(receipt))sessionStorage.removeItem(receiptKey);
 message.textContent=p?.message||(/^(pause|resume|abort) · observed$/i.test(receipt)?'':receipt);
 const disabledReason=stale?'Controls unavailable: observation disconnected or stale.':p?'Controls unavailable while a request remains unconfirmed.':[toggle,'stop','abort'].filter(a=>!actions.includes(a)).map(a=>a[0].toUpperCase()+a.slice(1)).join(', ');
 box.append(make('small',disabledReason?(stale||p?disabledReason:disabledReason+' unavailable in the observed state.'):'',{class:'control-disabled-reason'}));return box;
}
async function send(row,action,message){if(pending.has(row.id))return;sessionStorage.removeItem('jayrun.control.'+row.id);pending.set(row.id,{action,status:'sending',message:'Refreshing state before submission'});refreshControls();let sent=false,request=null;try{const fresh=await api('/api/context?id='+row.id);if(!fresh.row||fresh.row.state!==row.state||fresh.row.generation!==row.generation||fresh.row.control_version!==row.control_version){const e=Error('State changed; review the refreshed context before submitting');e.rejected=true;throw e}request={id:crypto.randomUUID(),context:row.id,action,generation:fresh.row.generation,revision:fresh.row.revision,control_version:fresh.row.control_version};if(workspace?.id===row.id){workspace.data=fresh;workStatus(fresh.row)}sent=true;const r=await api('/api/control',request);pending.set(row.id,{...r,message:'Request submitted; awaiting observed state.'})}catch(e){if(e.rejected||!sent){pending.delete(row.id);message.textContent=(e.rejected?'Rejected: ':'Not submitted: ')+e.message;sessionStorage.setItem('jayrun.control.'+row.id,message.textContent)}else pending.set(row.id,{id:request?.id,action,status:'unknown',message:'Delivery unknown. Observe the context before any new request; no automatic retry.'})}refreshControls()}
function refreshControls(){if(workspace?.data?.row){const target=$('#work-controls');if(target)replaceStable(target,lifecycle(workspace.data.row,workspace.origin==='history'));}if(list?.detail)renderQuick(list.detail)}
function routeTo(){const next=location.hash.slice(1)||'/overview';if(route==='overview'&&next==='/overview'&&overview)return;help.dismiss();if(list)clearQuickSelection(false);if(engines)closeEngineDetails(false);saveRoute();const graphView=workspace||graphList?.graphView;if(graphView?.viewer){if(graphView.tab==='graph')captureGraphState(graphView);lastGraphNavigation=graphView.graphState}const [path,q]=next.split('?'),parts=path.split('/').filter(Boolean),query=new URLSearchParams(q||'');epoch++;cancelReads(path=>parts[0]==='context'&&['/api/context?id=','/api/canvas?id='].some(prefix=>path===prefix+parts[1]));route=parts[0]||'overview';pageState=null;list=null;overview=null;graphList=null;engines=null;const same=route==='context'&&workspace?.id===parts[1];if(!same){document.querySelectorAll('jayrun-graph').forEach(v=>v.dispose());workspace=null;main.replaceChildren()}
 document.querySelectorAll('.sidebar a').forEach(a=>a.setAttribute('aria-current',a.hash==='#/'+route?'page':'false'));
 if(route==='overview')mountOverview();else if(route==='engines')mountEngines();else if(route==='contexts'||route==='history')mountList(route,query);else if(route==='graphs')mountGraphs(query);else if(route==='context')mountContext(parts[1],parts[2]||'graph',query.get('origin')||'contexts',same);else{main.replaceChildren(note('Page unavailable'));} }
window.addEventListener('hashchange',routeTo);
const PRESSURE_OLDER_SAMPLE_MS=30_000;
let pressureReference=null;
const activeCards=['running','paused','queued','routing','placement_waiting'],outcomeCards=['finished','failed','aborted','rejected'];
function stateIcon(state){const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg'),path=document.createElementNS(ns,'path');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');path.setAttribute('fill','currentColor');path.setAttribute('d',{running:'M7 3v18l15-9z',paused:'M6 4h4v16H6zM14 4h4v16h-4z',queued:'M3 4h18v3H3zM3 10h18v3H3zM3 16h12v3H3z',routing:'M3 4h10v3H6v10h7v-3l8 5-8 5v-4H3z',placement_waiting:'M4 3h16v6l-6 3 6 3v6H4v-6l6-3-6-3z',finished:'m2 12 4-4 5 5 9-9 4 4-13 13z',failed:'M10 3h4v12h-4zM10 18h4v4h-4z',aborted:'m5 2 7 7 7-7 3 3-7 7 7 7-3 3-7-7-7 7-3-3 7-7-7-7z',rejected:'M3 10h18v4H3z'}[state]);svg.append(path);return svg}
function mountOverview(){
 const title=make('div',null,{class:'section-heading overview-page-heading'}),headingCopy=make('div',null,{class:'overview-heading-copy'}),headingLine=make('div',null,{class:'section-heading'});
 headingLine.append(make('h1','Overview'),helpButton('dashboard.overview','About Overview evidence'));
 headingCopy.append(headingLine,make('p','Current authorized work and retained outcomes visible to this dashboard.',{class:'subhead'}));title.append(headingCopy);
 main.append(title);mountPageStatus(main);
 overview={counts:make('div',null,{class:'cards','data-scope':'active'}),outcomes:make('div',null,{class:'cards','data-scope':'outcomes'}),recent:make('div',null,{class:'overview-table-body'}),controls:make('div',null,{class:'overview-table-body'}),coverage:make('div'),legacy:make('p',null,{class:'muted'}),other:make('p',null,{class:'muted'})};
 overview.engineCount=make('strong','—');
 const entry=button(null,()=>go('/engines'),{class:'overview-engines','data-help':'dashboard.engines','aria-label':'Open Engines'});
 entry.append(make('span','Observed engines'),overview.engineCount,make('small','Open Engines →'));title.append(entry);
 overview.refreshStatus=make('p','',{role:'status',class:'overview-refresh-status'});overview.refresh=button('Refresh',()=>loadOverviewOutcomes(true),{'aria-label':'Refresh retained history','data-help':'dashboard.refresh',class:'history-refresh'});overview.historyHeading=make('div',null,{class:'overview-section-header history-heading'});const historyLabel=sectionHeading('Retained history outcomes','dashboard.history-outcomes','About retained history outcomes'),historyActions=make('div',null,{class:'overview-heading-actions'});overview.historyRead=make('small','',{class:'history-read'});historyActions.append(overview.historyRead,overview.refresh);overview.historyHeading.append(historyLabel,historyActions);
 for(const [target,states]of [[overview.counts,activeCards],[overview.outcomes,outcomeCards]])for(const state of states){const card=button(null,()=>openList(target===overview.counts?'contexts':'history',target===overview.counts?{state,workloads:'1'}:{state,session:fleet.history_session}),{class:'card state-'+state,'data-state':state,'aria-label':state+' contexts'});const label=make('span',state.replaceAll('_',' '),{class:'card-label'});label.prepend(stateIcon(state));card.append(label,make('strong','—'));target.append(card)}
 const activeSection=make('section',null,{class:'box overview-section active-overview'});activeSection.append(sectionHeading('Current authorized active contexts','dashboard.active'),overview.counts,overview.other);
 const historySection=make('section',null,{class:'box overview-section history-overview'});historySection.append(overview.historyHeading,overview.outcomes,overview.refreshStatus,overview.legacy);
 main.append(activeSection,historySection);
 const split=make('div',null,{class:'split overview-tables'});for(const [title,node,topic]of [['Recent failures',overview.recent,'dashboard.failures'],['Recent control outcomes',overview.controls,'dashboard.control-outcomes']]){const box=make('section',null,{class:'box overview-table-card'});box.append(sectionHeading(title,topic),node);split.append(box)}main.append(split,overview.coverage);updateOverview();void loadOverviewOutcomes();
}
function capturePressureReference(data){
 const local=Array.isArray(data.pressures)?data.pressures[0]:null;
 if(pressureReference&&pressureReference.engine_id!==data.engine_id)pressureReference=null;
 if(data.pressure_gap||!local||local.engine_id!==data.engine_id)return;
 const sample=Date.parse(local.sampled_at);
 if(Number.isFinite(sample)&&(!pressureReference||pressureReference.sample!==sample))pressureReference={engine_id:data.engine_id,sample,at:performance.now()};
}
function pressureSampleAge(stamp){
 const sample=Date.parse(stamp||'');
 if(!pressureReference||!Number.isFinite(sample))return ['Age unknown','No valid local sample clock or producer timestamp is available.'];
 const age=pressureReference.sample+Math.max(0,performance.now()-pressureReference.at)-sample;
 const explanation="Based on producer timestamps relative to this engine's sample clock. Remote clocks may differ; this does not establish that an engine is offline.";
 if(age < -PRESSURE_OLDER_SAMPLE_MS)return ['Time mismatch · age unknown',explanation];
 return age>PRESSURE_OLDER_SAMPLE_MS?['Older sample',explanation]:['',explanation];
}
function observedEngines(){
 if(!fleet)return [];
 const local=fleet.engine_id,pressure=new Map((fleet.pressures||[]).map(p=>[p.engine_id,p]));
 const known=fleet.ready&&Array.isArray(fleet.observed_work),work=new Map((known?fleet.observed_work:[]).map(g=>[g.engine_id,g.counts]));
 const machines=new Set([local,...pressure.keys(),...work.keys()].filter(m=>typeof m==='string'&&m.length));
 const entries=[...machines].sort((a,b)=>a===local?-1:b===local?1:a<b?-1:a>b?1:0).map(engine_id=>({engine_id,local:engine_id===local,pressure:pressure.get(engine_id),counts:work.get(engine_id)??(engine_id===local&&known?{}:null),context:work.has(engine_id)}));
 if(work.has(null))entries.push({engine_id:null,counts:work.get(null),context:true});
 return entries;
}
function engineDisplay(entry){return entry.engine_id===null?'Unattributed':entry.local?'This engine':entry.engine_id.length>32?entry.engine_id.slice(0,20)+'…'+entry.engine_id.slice(-9):entry.engine_id}
function pressureReport(p){
 if(!p)return {key:'missing',label:'Not reported',detail:'No pressure report is available in this observation.'};
 const [age,detail]=pressureSampleAge(p.sampled_at);
 return {key:age==='Older sample'?'older':age?'unknown':'reported',label:age||'Reported',detail};
}
function updatePressureAges(){if(engines)updateEngines()}
// Shared geometry; each view keeps ownership of its controls and data.
function dataView(title,subtitle,topic,className=''){
 const root=make('section',null,{class:'data-view '+className}),header=make('div',null,{class:'data-header'}),heading=make('div',null,{class:'section-heading'}),content=make('div',null,{class:'data-content'});
 heading.append(make('h1',title),helpButton(topic,'About '+title));header.append(heading,make('p',subtitle,{class:'subhead'}));root.append(header);mountPageStatus(root);root.append(content);main.append(root);return {root,content};
}
function controlDeck(content){
 const deck=make('div',null,{class:'control-deck'}),utility=make('div',null,{class:'data-utility'}),filters=make('div',null,{class:'filters data-filters'});
 deck.append(utility,filters);content.append(deck);return {deck,utility,filters};
}
function tableShell(content){
 const shell=make('div',null,{class:'data-table-shell'}),stage=make('div',null,{class:'table-stage data-table-stage'}),footer=make('div',null,{class:'data-footer'});
 shell.append(stage,footer);content.append(shell);if(pageState){pageState.restoreFocus=pageState.restoreFocus||Boolean(pageState.empty?.contains(document.activeElement));pageState.empty?.remove();pageState.empty=null;pageState.shell=stage;pageState.footer=footer;updatePageStatus()}return {stage,footer};
}
function mountEngines(){
 const saved=routeStates.engines||{},view=dataView('Engines','Observed execution engines and reported runtime pressure','dashboard.engines','engines-view'),root=view.root;
 const deck=controlDeck(view.content),toolbar=deck.filters,search=make('input',null,{type:'search',placeholder:'Search engine identity','aria-label':'Search engine identity'});toolbar.classList.add('engines-toolbar');
 const e=engines={root,tab:saved.tab==='work'?'work':'pressure',search:saved.search||'',filters:{memory:saved.memory||'',report:saved.report||'',state:saved.state||'',workReport:saved.workReport||'',pressureSort:saved.pressureSort||'',workSort:saved.workSort||''},views:{},selected:null,rows:[],quick:make('aside',null,{class:'box quick engine-details','aria-label':'Selected engine details',tabindex:'-1'})};
 e.quick.hidden=true;e.quick.inert=true;search.value=e.search;search.oninput=()=>{e.search=search.value;updateEngines();saveRoute()};toolbar.append(search);
 const change=(key,value)=>{e.filters[key]=value;updateEngines();saveRoute()};
 e.pressureFilters=make('div',null,{class:'engine-filter-slots'});e.workFilters=make('div',null,{class:'engine-filter-slots'});
 e.pressureFilters.append(inputFilter('Memory','memory',[['','Any memory'],['pressured','Pressured'],['clear','No pressure'],['unknown','Unknown']],e.filters.memory,change),inputFilter('Report','report',[['','Any report'],['reported','Reported'],['older','Older sample'],['missing','Not reported'],['unknown','Age unknown / time mismatch']],e.filters.report,change),inputFilter('Sort','pressureSort',[['','Engine identity'],['occupied_tasks','Tasks in use'],['pending_placements','Pending placements'],['task_capacity','Ordinary capacity']],e.filters.pressureSort,change));
 e.workFilters.append(inputFilter('State','state',[['','Any state'],...activeCards.map(s=>[s,s.replaceAll('_',' ')])],e.filters.state,change),inputFilter('Pressure report','workReport',[['','Any report'],['reported','Reported'],['missing','Not reported']],e.filters.workReport,change),inputFilter('Sort','workSort',[['','Engine identity'],...activeCards.map(s=>[s,s.replaceAll('_',' ')])],e.filters.workSort,change));
 toolbar.append(e.pressureFilters,e.workFilters);
 const tabs=make('div',null,{class:'engine-tabs',role:'tablist','aria-label':'Engine data'});tabs.onkeydown=tabKeys;deck.utility.append(tabs);
 const {stage,footer}=tableShell(view.content);stage.classList.add('engines-stage');
 e.gap=make('div','',{class:'engine-gap',role:'status'});footer.append(e.gap);
 for(const [key,label,headers]of [['pressure','Pressure',['Engine','Memory','Tasks in use','Ordinary capacity','Supervising capacity','Pending placements','Sampled','Report']],['work','Observed work',['Engine','Running','Paused','Queued','Routing','Placement waiting']]]){
  const tab=button(label,()=>selectEngineTab(key),{id:'engines-'+key+'-tab',role:'tab','aria-controls':'engines-'+key+'-view'});tabs.append(tab);
  const scroll=make('div',null,{class:'table-wrap engine-scroll',id:'engines-'+key+'-view',role:'tabpanel','aria-labelledby':tab.id,tabindex:'-1'}),table=make('table',null,{class:'engine-table '+key+'-table'}),head=make('thead'),labels=make('tr'),body=make('tbody');
  for(const title of headers)labels.append(make('th',title,{scope:'col'}));head.append(labels);table.append(head,body);scroll.append(table);
  const empty=make('div','No engines match these filters.',{class:'engine-empty',role:'status'});scroll.append(empty);stage.append(scroll);
  e.views[key]={tab,scroll,table,body,empty,rows:new Map()};
 }
 stage.append(e.quick);selectEngineTab(e.tab);
 for(const [key,v]of Object.entries(e.views)){const pos=saved.scrolls?.[key];if(pos){v.scroll.scrollTop=pos[0];v.scroll.scrollLeft=pos[1];v.savedScroll=pos}}
}
function selectEngineTab(key){
 if(!engines)return;const e=engines,previous=e.views[e.tab];if(previous)previous.savedScroll=[previous.scroll.scrollTop,previous.scroll.scrollLeft];e.tab=key;
 for(const [name,v]of Object.entries(e.views)){v.scroll.hidden=name!==key;v.tab.setAttribute('aria-selected',String(name===key));v.tab.tabIndex=name===key?0:-1}
 e.pressureFilters.hidden=key!=='pressure';e.workFilters.hidden=key!=='work';updateEngines();
 const v=e.views[key];if(v.savedScroll){v.scroll.scrollTop=v.savedScroll[0];v.scroll.scrollLeft=v.savedScroll[1]}saveRoute();
}
function engineEntriesForTab(entries,key){
 const e=engines,f=e.filters,query=e.search.toLowerCase();
 let rows=entries.filter(entry=>(key==='work'||entry.engine_id!==null)&&(!query||(entry.engine_id||'').toLowerCase().includes(query)||(entry.local&&(fleet.engine||'').toLowerCase().includes(query))));
 if(key==='pressure')rows=rows.filter(entry=>{const p=entry.pressure,memory=p?.memory_pressured===true?'pressured':p?.memory_pressured===false?'clear':'unknown';return (!f.memory||memory===f.memory)&&(!f.report||pressureReport(p).key===f.report)});
 else rows=rows.filter(entry=>(!f.state||(entry.counts?.[f.state]||0)>0)&&(!f.workReport||(entry.pressure?'reported':'missing')===f.workReport));
 const sort=key==='pressure'?f.pressureSort:f.workSort;
 if(sort)rows.sort((a,b)=>{if(a.local!==b.local)return a.local?-1:1;if(a.engine_id===null||b.engine_id===null)return a.engine_id===null?1:-1;const av=key==='pressure'?a.pressure?.[sort]:a.counts?.[sort]??(a.counts?0:null),bv=key==='pressure'?b.pressure?.[sort]:b.counts?.[sort]??(b.counts?0:null);return av==null?(bv==null?0:1):bv==null?-1:bv-av});
 return rows;
}
function reconcileEngineRows(view,entries,key){
 const scroll=view.scroll,top=scroll.scrollTop,left=scroll.scrollLeft,edge=scroll.getBoundingClientRect().top+view.table.tHead.getBoundingClientRect().height;
 const anchors=[...view.body.children].filter(row=>row.getBoundingClientRect().bottom>edge).map(row=>[row.engineMachine,row.getBoundingClientRect().top]);
 const keys=new Set(entries.map(entry=>entry.engine_id));
 for(const [engine_id,row]of view.rows)if(!keys.has(engine_id)){const focused=row.contains(document.activeElement);row.remove();view.rows.delete(engine_id);if(focused)scroll.focus({preventScroll:true})}
 let cursor=view.body.firstChild;
 for(const entry of entries){
  let row=view.rows.get(entry.engine_id);
  if(!row){row=make('tr',null,{tabindex:entry.engine_id===null?'-1':'0'});row.engineMachine=entry.engine_id;if(entry.engine_id!==null)row.dataset.engine_id=entry.engine_id;
   for(let i=0;i<(key==='pressure'?8:6);i++)row.append(make('td'));
   row.onclick=()=>{if(entry.engine_id!==null){engines.selected=entry.engine_id;updateEngines()}};
   row.onkeydown=event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();row.click()}};view.rows.set(entry.engine_id,row);
  }
  if(row!==cursor)view.body.insertBefore(row,cursor);else cursor=cursor.nextSibling;
  row.classList.toggle('selected',entry.engine_id!==null&&engines.selected===entry.engine_id);row.classList.toggle('unattributed',entry.engine_id===null);
  row.setAttribute('aria-label',entry.engine_id===null?'Unattributed work; not an engine':(entry.local?'This engine: ':'Engine: ')+entry.engine_id);
  const identity=make('div',null,{class:'engine-identity'});identity.append(make('strong',engineDisplay(entry),{title:entry.engine_id||'Not an engine'}));
  identity.append(make('small',entry.engine_id===null?'Non-engine grouping':entry.local?fleet.engine:key==='work'&&!entry.counts?'No observed context detail':'',{title:entry.engine_id||''}));replaceStable(row.cells[0],identity);
  if(key==='pressure'){
   const p=entry.pressure,values=[p?.memory_pressured===true?'Pressured':p?.memory_pressured===false?'No pressure':'—',p?.occupied_tasks??'—',p?.task_capacity??'—',p?.supervision_capacity??'—',p?.pending_placements??'—'];
   values.forEach((value,i)=>{row.cells[i+1].textContent=String(value)});row.cells[1].classList.toggle('state-paused',p?.memory_pressured===true);
   replaceStable(row.cells[6],sampleTimestamp(p?.sampled_at));
   const report=pressureReport(p);const badge=make('span',report.label,{class:'badge status-badge engine-report '+(report.key==='older'||report.key==='unknown'?'sample-warning':''),title:report.label+' · '+report.detail});replaceStable(row.cells[7],badge);
  }else activeCards.forEach((state,i)=>{row.cells[i+1].textContent=entry.counts?String(entry.counts[state]||0):'—';row.cells[i+1].className='state-'+state;row.cells[i+1].title=entry.counts?'Authorized observed contexts':'No context detail observed'});
 }
 view.empty.hidden=Boolean(entries.length);
 const anchor=anchors.find(([engine_id])=>view.rows.has(engine_id));scroll.scrollTop=anchor?top+view.rows.get(anchor[0]).getBoundingClientRect().top-anchor[1]:top;scroll.scrollLeft=left;
}
function closeEngineDetails(restoreFocus=true){
 if(!engines)return;const e=engines,engine_id=e.selected;e.selected=null;e.quick.hidden=true;e.quick.inert=true;e.quick.replaceChildren();for(const v of Object.values(e.views))for(const row of v.rows.values())row.classList.remove('selected');
 if(restoreFocus)(e.views[e.tab].rows.get(engine_id)||e.views[e.tab].scroll).focus({preventScroll:true});
}
function renderEngineDetails(entry){
 const e=engines,q=make('div',null,{class:'quick-content'}),heading=make('div',null,{class:'quick-heading'});
 heading.append(sectionHeading(engineDisplay(entry),'dashboard.engines'),button('Close details',()=>closeEngineDetails(),{'aria-label':'Close engine details'}));q.append(heading);
 q.append(make('h3','Identity'),make('p',entry.local?'Local engine':'Other observed engine'),make('code',entry.engine_id,{class:'engine-full-identity'}));
 if(entry.local)q.append(make('p',fleet.engine,{class:'muted'}));
 q.append(sectionHeading('Reported pressure','dashboard.pressure'));
 const p=entry.pressure;if(p){const report=pressureReport(p);q.append(engineFacts([['Memory admission',p.memory_pressured?'Pressured':'No pressure'],['Tasks in use',p.occupied_tasks],['Ordinary capacity',p.task_capacity],['Supervising capacity',p.supervision_capacity],['Pending placements',p.pending_placements],['Sampled',p.sampled_at],['Report',report.label]]),make('small',report.detail,{class:'engine-age-detail'}))}else q.append(make('p','Pressure not reported',{class:'muted'}));
 q.append(sectionHeading('Observed work','dashboard.observed-work'));
 if(entry.counts)q.append(engineFacts(activeCards.map(state=>[state.replaceAll('_',' '),entry.counts[state]||0])));else q.append(make('p','No context detail observed',{class:'muted'}));
 q.append(make('h3','Observation coverage'),make('p',p&&entry.context?'Both: pressure report and context observation':p?'Pressure report':entry.context?'Context observation':'Local engine identity; no report or attributed contexts'));
 if(!entry.context&&entry.counts)q.append(make('small','No current contexts attributed to this engine in the authorized view.',{class:'muted'}));
 const old=e.quick.querySelector('.quick-content');if(old)sync(old,q);else e.quick.replaceChildren(q);e.quick.hidden=false;e.quick.inert=false;
}
function engineFacts(values){const dl=make('dl',null,{class:'engine-facts'});for(const [label,value]of values)dl.append(make('dt',label),make('dd',value));return dl}
function updateEngines(){
 if(!engines||!fleet)return;if(fleet.ready)pageAccepted();const e=engines,entries=observedEngines();
 e.gap.textContent=[fleet.pressure_gap,!fleet.ready||!Array.isArray(fleet.observed_work)?'Context detail unavailable':null].filter(Boolean).join(' · ');
 const selected=entries.find(entry=>entry.engine_id===e.selected);
 if(e.selected&&!selected){closeEngineDetails(false);e.views[e.tab].scroll.focus({preventScroll:true})}
 reconcileEngineRows(e.views[e.tab],engineEntriesForTab(entries,e.tab),e.tab);
 if(selected&&e.selected)renderEngineDetails(selected);
}

function overviewTable(headers,rows,empty,label='Overview data'){
 const wrap=make('div',null,{class:'table-wrap overview-table','aria-label':label}),table=make('table'),head=make('thead'),titles=make('tr'),body=make('tbody');headers.forEach(t=>titles.append(make('th',t)));head.append(titles);
 for(const cells of rows){const tr=make('tr');for(const content of cells){const td=make('td');td.append(content instanceof Node?content:document.createTextNode(String(content??'Unavailable')));tr.append(td)}body.append(tr)}
 table.append(head,body);wrap.append(table);if(!rows.length)wrap.append(make('div',empty,{class:'overview-empty',role:'status'}));return wrap;
}
function shortFailure(value){if(value==null)return 'Failure details unavailable';if(typeof value==='string')return value.slice(0,240);return ((value.type||'Failure')+(value.arguments?' · '+JSON.stringify(value.arguments):'')).slice(0,240)}
async function loadOverviewOutcomes(force=false){
 if(!overview||!fleet||disposed)return;const current=overview;
 const database=Boolean(fleet.persistence?.enabled),key=JSON.stringify([serviceEpoch,database]);
 if(current.outcomeKey!==key){current.outcomeData=lastViewResponses.get('outcomes')?.data||null;current.outcomeError=null;current.outcomeAt=0;current.outcomeKey=key;current.outcomeRead=null;current.outcomeLoading=false;current.outcomeSequence=(current.outcomeSequence||0)+1;updateOverview()}
 // One initial cached read makes retained history visible; live polling never re-queries it.
 if(database&&!force&&current.outcomeAt)return;
 if(!database&&force)return;
 if(current.outcomeRead)return current.outcomeRead;
 if(!force&&current.outcomeAt&&Date.now()-current.outcomeAt<1500)return;
 const refreshFocus=Boolean(current.refresh&&document.activeElement===current.refresh);
 const ticket=epoch,service=serviceEpoch,sequence=(current.outcomeSequence||0)+1;current.outcomeSequence=sequence;
 const params=new URLSearchParams();if(database)params.set('refresh','1');
 const path='/api/history-summary'+(params.size?'?'+params:'');
 const applicable=()=>!disposed&&epoch===ticket&&serviceEpoch===service&&overview===current&&current.outcomeKey===key&&current.outcomeSequence===sequence;
 current.outcomeLoading=true;current.outcomeError=null;
 const read=(async()=>{try{const data=await api(path);if(!applicable())return;current.outcomeData=data;lastViewResponses.set('outcomes',{data});current.outcomeAt=Date.now()}
 catch(e){if(applicable()){current.outcomeError=e.message;current.outcomeAt=Date.now()}}
 finally{if(applicable()){current.outcomeRead=null;current.outcomeLoading=false;updateOverview();if(refreshFocus&&!current.refresh.disabled&&(document.activeElement===document.body||document.activeElement===current.refresh))current.refresh.focus({preventScroll:true})}}})();
 current.outcomeRead=read;updateOverview();return read;
}

function updateOverview(){
 if(!overview)return;if(pageState){pageState.shell=main.querySelector('.active-overview');updatePageStatus()}if(!fleet)return;if(fleet.ready)pageAccepted();
 const database=Boolean(fleet.persistence?.enabled);
 overview.refresh.disabled=!database||Boolean(overview.outcomeLoading);
 overview.refresh.dataset.help=database?'dashboard.refresh':'dashboard.refresh-unavailable';
 overview.refresh.textContent=overview.outcomeLoading&&database?'Refreshing…':'Refresh';
 overview.refreshStatus.textContent=!database?'Database refresh unavailable. Showing retained observations.':overview.outcomeLoading?'Loading retained history…':overview.outcomeError?(overview.outcomeData?'Could not refresh history. Previous results are still shown.':'Could not load history. Try Refresh again.'):'';
 overview.refresh.setAttribute('aria-busy',String(Boolean(overview.outcomeLoading)));
 const active=fleet.active_counts,outcomes=overview.outcomeData?.counts;
 overview.historyHeading.querySelector('h2').textContent='Retained history outcomes';
 overview.historyRead.textContent=overview.outcomeData?'Read '+localTime(overview.outcomeAt):'';
 for(const target of [overview.counts,overview.outcomes])for(const card of target.children)card.onclick=()=>openList(target===overview.counts?'contexts':'history',{state:card.dataset.state,...(target===overview.counts?{workloads:'1'}:{})});
 const contextRows=fleet.contexts;
 for(const [target,counts]of [[overview.counts,active],[overview.outcomes,outcomes]])for(const card of target.children){const unavailable=target===overview.outcomes&&!counts;card.disabled=unavailable;card.querySelector('strong').textContent=fleet.ready&&!unavailable?String(counts?.[card.dataset.state]||0):'—'};
 const legacy=outcomes?.stopped||0;overview.legacy.hidden=!legacy;if(legacy)overview.legacy.replaceChildren(document.createTextNode(legacy+' legacy outcomes are outside the current outcome cards. '),button('View session history',()=>openList('history',{session:fleet.history_session})));
 const other=Object.entries(active||{}).filter(([state,count])=>!activeCards.includes(state)&&count);overview.other.textContent=other.length?'Other active transitions: '+other.map(([s,n])=>s+' '+n).join(' · '):'';
 const failed=contextRows.filter(r=>r.state==='failed').slice(-8).reverse();replaceStable(overview.recent,overviewTable(['Context / graph','Failure','Completed'],failed.map(r=>{const id=make('div');id.append(button(r.id,()=>go(contextLink(r.id,'summary'))),make('small',r.graph+' · '+r.version));return [id,shortFailure(r.failure),r.finished_at?localTime(r.finished_at):'Not captured']}),'No retained failures.','Recent failures'));
 replaceStable(overview.controls,overviewTable(['Context / action','Request outcome','Submitted'],fleet.requests.slice(-8).reverse().map(r=>{const id=make('div');id.append(button(r.context,()=>go(contextLink(r.context,'activity'))),make('small',r.action));const outcome=make('div',r.status);outcome.append(make('small',r.message));return [id,outcome,r.submitted_at?localTime(r.submitted_at):'Not captured']}),'No control requests observed.','Recent control outcomes'));
 overview.engineCount.textContent=String(observedEngines().filter(entry=>entry.engine_id!==null).length);
 const gaps=[fleet.gap,fleet.count_gap,fleet.terminal_recovery?.gap,fleet.persistence?.gap].filter(Boolean);
 overview.coverage.replaceChildren(...[...new Set(gaps)].map(gap=>note(gap)));
}

function inputFilter(label,key,options,value,onchange){const wrap=make('label',label),n=make('select',null,{'aria-label':label});for(const [v,t]of options)n.append(make('option',t,{value:v}));n.value=value||'';n.onchange=()=>onchange(key,n.value);if(key==='capability')n.dataset.help='evidence.access';if(key==='session')n.dataset.help='dashboard.session';wrap.append(n);return wrap}
function orderListRows(rows,kind,direction){
 const field=kind==='history'?'finished_at':'created_at',newest=direction==='newest';
 return rows.map((row,index)=>({row,index,time:Date.parse(row[field]||'')})).sort((a,b)=>{
  const aTimed=Number.isFinite(a.time),bTimed=Number.isFinite(b.time);
  if(aTimed!==bTimed)return aTimed?-1:1;
  if(aTimed&&a.time!==b.time)return newest?b.time-a.time:a.time-b.time;
  return a.index-b.index;
 }).map(item=>item.row);
}
function mountList(kind,query){const saved={...routeStates[kind],selection:null};const value=(name,fallback='')=>query.has(name)?query.get(name):(saved[name]??fallback);const filters={search:value('search'),state:value('state'),graph_id:value('graph_id'),capability:value('capability'),sort:value('sort','oldest'),session:value('session'),date:value('date'),workloads:value('workloads'),engine_session:value('engine_session')};const states=kind==='history'?outcomeCards:['queued','routing','running','placement_waiting','paused','aborting','failing'];const invalidState=filters.state&&!states.includes(filters.state);if(invalidState){const previous=filters.state;filters.state='';query.set('state','');history.replaceState(null,'','#/'+kind+'?'+query);main.append(note(kind==='history'&&previous==='stopped'?'Legacy Stop filter cleared. Older outcomes remain available without a state filter.':'Unavailable '+kind+' state filter cleared.'))}const view=dataView(kind==='history'?'History':'Contexts',kind==='history'?'Retained terminal evidence · read-only':'Current nonterminal work',kind==='history'?'dashboard.history':'dashboard.contexts',kind==='history'?'history-list':'contexts-view'),content=view.content,deck=controlDeck(content),controls=deck.filters,quick=make('aside',null,{class:'box quick'});quick.hidden=!saved.selection;const search=make('input',null,{type:'search',placeholder:'Search context identity or graph','aria-label':'Search contexts'});search.value=filters.search;controls.append(search);list={kind,filters,page:saved.page||0,selected:saved.selection,quick,content,controls,body:make('tbody'),total:make('span'),rows:[],detail:null};const change=(k,v)=>{list.filters[k]=v;list.page=0;saveRoute();history.replaceState(null,'','#/'+list.kind+'?'+new URLSearchParams(list.filters));loadList(true)};search.oninput=()=>change('search',search.value);controls.append(inputFilter('State','state',[['','Any state'],...states.map(s=>[s,s])],filters.state,change),inputFilter('Graph/version','graph_id',[['','All captured graphs']],filters.graph_id,change),inputFilter('Cross-context access','capability',[['','Any capability'],['unknown','Unknown'],['observes','Observes'],['controls','Controls'],['neither','Neither']],filters.capability,change),inputFilter('Sort','sort',[['oldest','Oldest first'],['newest','Newest first']],filters.sort,change));if(kind==='history'){const sessionField=make('div',null,{class:'session-filter'}),sessionFilter=inputFilter('Session','session',[['','All retained sessions'],...(filters.session?[[filters.session,sessionIdentity(filters.session)]]:[])],filters.session,change),inspect=button('Inspect',()=>inspectSessions(content,inspect),{'aria-label':'Inspect engine sessions',title:'Inspect engine sessions'});sessionField.append(sessionFilter,inspect);deck.utility.append(sessionField);const date=make('input',null,{type:'date','aria-label':'Since date'});date.value=filters.date;date.onchange=()=>change('date',date.value);const dateLabel=make('label','Since date');dateLabel.append(date);deck.utility.append(dateLabel)}list.coverage=make('p',null,{class:'muted list-coverage',role:'status'});list.sessionNotice=make('p',null,{class:'session-notice',role:'status'});const notices=make('div',null,{class:'data-notices'});notices.append(list.coverage,list.sessionNotice);if(kind==='contexts'){const label=make('label','Include this dashboard',{class:'dashboard-switch'}),toggle=make('input',null,{type:'checkbox',role:'switch','data-dashboard-toggle':''});toggle.checked=filters.workloads!=='1';toggle.onchange=()=>change('workloads',toggle.checked?'':'1');label.append(toggle);deck.utility.append(label)} const table=make('table'),head=make('thead'),tr=make('tr');(kind==='history'?['Context','Engine session','Graph','Outcome','Completed','Elapsed','Details']:['Context','Graph / version','Execution location','State','Cross-context access','Estimated progress','Iteration']).forEach(s=>tr.append(make('th',s,{scope:'col'})));head.append(tr);table.append(head,list.body);const tw=make('div',null,{class:'table-wrap',tabindex:'-1','aria-label':kind==='history'?'History results':'Context results'});list.focusTarget=tw;tw.append(table);const {stage,footer}=tableShell(content);stage.append(tw,quick);footer.append(notices);quick.setAttribute('aria-label','Selected context details');quick.setAttribute('tabindex','-1');quick.inert=quick.hidden;const pager=make('div',null,{class:'pager'});pager.append(button('Previous',()=>{list.page=Math.max(0,list.page-1);loadList(true)}),list.total,button('Next',()=>{if(list.hasMore??((list.page+1)*25<list.count)){list.page++;loadList(true)}}));footer.append(pager);quick.append(note(kind==='history'?'Select a row for a quick summary. Use View summary for the full workspace.':'Select a row for a quick summary. Use Open context for the full workspace.'));const ticket=epoch;const loadGraphChoices=()=>api('/api/graphs').then(data=>{if(epoch!==ticket||!list)return;const select=controls.querySelector('select[aria-label="Graph/version"]');reconcileOptions(select,[['','All captured graphs'],...data.graphs.map(g=>[g.id,(g.key||'Local definition')+' · '+g.version])],filters.graph_id);pageState?.issues.delete('graph-choices');updatePageStatus()}).catch(e=>{if(list?.controls===controls)pageIssue('graph-choices','Graph filters unavailable: '+e.message,loadGraphChoices)});if(kind!=='history')loadGraphChoices();loadList(true).then(()=>{window.scrollTo(0,saved.scroll||0);if(list?.body.isConnected)list.body.closest('.table-wrap').scrollTop=saved.tableScroll||0})}
async function inspectSessions(content,trigger){
 const existing=content.querySelector('dialog[data-session-inspector]');if(existing){if(!existing.open)existing.showModal();existing.querySelector('button')?.focus({preventScroll:true});return}
 const ticket=epoch,panel=make('dialog',null,{class:'session-inspector','data-session-inspector':'','aria-labelledby':'session-inspector-title'}),shell=make('div',null,{class:'session-inspector-shell'}),heading=make('div',null,{class:'session-inspector-heading'}),body=make('div',null,{class:'session-inspector-body'}),close=button('Close',()=>panel.close(),{'aria-label':'Close engine sessions'});
 heading.append(make('h2','Engine sessions · read-only',{id:'session-inspector-title'}),close);body.append(note('Loading scoped engine sessions…'));shell.append(heading,body);panel.append(shell);content.append(panel);
 panel.addEventListener('close',()=>{panel.remove();if(trigger?.isConnected)trigger.focus({preventScroll:true})},{once:true});panel.showModal();close.focus({preventScroll:true});
 try{const data=await api('/api/sessions');if(epoch!==ticket||!panel.isConnected)return;body.replaceChildren(note(data.coverage));
 for(const row of data.sessions){const item=make('details'),title=make('summary',sessionIdentity(row.session_id)+' · '+(row.engine_name||'Unnamed engine'),{title:row.session_id});item.append(title);item.addEventListener('toggle',async()=>{if(!item.open||item.dataset.loaded)return;try{const result=await api('/api/session?'+new URLSearchParams({id:row.session_id}));if(epoch!==ticket||!item.isConnected)return;item.append(make('pre',JSON.stringify(result,null,2)));item.dataset.loaded='1'}catch(e){item.append(note('Session unavailable: '+e.message,true))}});body.append(item)}
 }catch(e){if(epoch===ticket&&panel.isConnected)body.replaceChildren(note('Sessions unavailable: '+e.message,true))}
}
async function loadList(force=false){
 if(!list)return;const current=list,ticket=epoch;if(!force&&(Date.now()<(current.retryAt||0)||(current.kind==='history'&&Date.now()-(current.loadedAt||0)<2000)))return;
 const requestFilters={...current.filters};if(current.kind==='history')delete requestFilters.workloads;
 const path='/api/'+current.kind+'?'+new URLSearchParams({...requestFilters,page:current.page});if(current.path&&current.path!==path)reads.get(current.path)?.controller.abort();current.path=path;
 try{let data,failure=null;try{data=await api(path)}catch(e){const previous=lastViewResponses.get(current.kind);if(current.loadedAt||previous?.path!==path)throw e;data=previous.data;failure=e}if(epoch!==ticket||list!==current||current.path!==path)return;
  current.failures=0;current.retryAt=0;clearReadNotice(current.content);current.count=data.total;current.page=data.page;current.hasMore=data.has_more;current.loadedAt=Date.now();current.coverage.textContent=current.kind==='history'?(data.gap||data.capture_gap||''):[data.gap,data.capture_gap].filter(Boolean).join(' ');
  const durableCount=data.rows.length,limit=data.page_size||25;
  current.total.textContent=data.total==null?'Page '+(current.page+1)+' · '+durableCount+' committed headers · total unknown':(data.total?current.page*limit+1:0)+'–'+Math.min(current.page*limit+durableCount,data.total)+' of '+data.total;
  data.rows=orderListRows(data.rows,current.kind,current.filters.sort);
  if(current.kind==='history'){const ids=new Set(data.rows.map(r=>r.id));const recent=orderListRows((data.recent_rows||[]).filter(r=>!ids.has(r.id)).map(r=>r.finished_at||!r.updated_at?r:{...r,finished_at:r.updated_at}),current.kind,current.filters.sort);if(recent.length)data.rows=current.filters.sort==='newest'?[...recent,...data.rows]:[...data.rows,...recent]}
  const scroll=current.body.closest('.table-wrap'),top=scroll.scrollTop;
  const anchor=[...current.body.children].find(tr=>tr.offsetTop>=top),anchorY=anchor?.getBoundingClientRect().top;
  const ids=new Set(data.rows.map(r=>r.id));for(const tr of [...current.body.children])if(!ids.has(tr.dataset.context))tr.remove();
  data.rows.forEach((row,index)=>{
   let tr=current.body.querySelector('tr[data-context="'+row.id+'"]');
   if(!tr){tr=make('tr',null,{tabindex:'0','data-context':row.id});for(let i=0;i<7;i++)tr.append(make('td'))}
   const cells=tr.children,identity=make('div',null,{class:'identity-cell'+(current.kind==='history'?' history-context-cell':'')}),identityRegion=make('span',null,{class:'history-identity-region'});identityRegion.append(identityText(row));
   if(row.controller)identityRegion.append(make('span','This dashboard',{class:'badge'}));
   if(current.kind==='history'){const sourceRegion=make('span',null,{class:'history-source-region'});if(row.recent||row.imported){const badge=make('span',row.imported?'Imported':'Recent',{class:'badge history-source'});badge.title=row.imported?'Converted legacy evidence; original identity remains in Summary.':'Recent finalized observation; committed publication is not yet confirmed on this page.';sourceRegion.append(badge)}identity.append(identityRegion,sourceRegion)}else identity.append(identityRegion);
   replaceStable(cells[0],identity);
   if(current.kind==='history'){
    const session=make('div',null,{class:'provenance'}),l=locationOf(row),engineId=l.engine_id||'Unknown engine session';session.append(make('span',sessionIdentity(engineId)),make('small',l.physical_machine||'Physical host unknown'));session.title='Engine session: '+engineId+'\nRecording engine session: '+(row.session||'Unknown');replaceStable(cells[1],session);
    cells[2].textContent=row.graph;cells[2].title=row.graph_id||'Graph identity unavailable';replaceStable(cells[3],stateBadge(row,true,true));
    cells[4].textContent=row.finished_at?localTime(row.finished_at):'Not captured';cells[4].title=row.finished_at||'Completion time not captured';cells[5].textContent=duration(row.elapsed_seconds);
    const action=button('View summary',event=>{event.stopPropagation();go(contextLink(row.id,'summary','history'))});replaceStable(cells[6],action);
   }else{
    cells[1].textContent=row.graph+' · '+row.version;replaceStable(cells[2],locationCell(row));replaceStable(cells[3],stateBadge(row,false,true));
    cells[4].textContent='Observes: '+(row.access?.observes||'Unknown')+' · Controls: '+(row.access?.controls||'Unknown');
    replaceStable(cells[5],contextProgress(row,true));cells[6].textContent=row.iteration??'Unavailable';
   }
   tr.classList.toggle('selected',current.selected===row.id);
   tr.onclick=e=>{if(!e.target.closest('button,a')&&!window.getSelection()?.toString())selectRow(row,false)};
   tr.onkeydown=e=>{if(e.target===tr&&(e.key==='Enter'||e.key===' ')){e.preventDefault();selectRow(row,true)}};
   if(current.body.children[index]!==tr)current.body.insertBefore(tr,current.body.children[index]||null);
  });
  if(anchor?.isConnected)scroll.scrollTop+=anchor.getBoundingClientRect().top-anchorY;else scroll.scrollTop=top;
  if(current.kind==='history'){
   const graphSelect=current.controls.querySelector('select[aria-label="Graph/version"]');
   const choices=new Map((data.graphs||[]).map(g=>[g.id,g]));
   if(current.filters.graph_id&&!choices.has(current.filters.graph_id))choices.set(current.filters.graph_id,{id:current.filters.graph_id,key:'Selected graph (not in retained choices)',version:''});
   for(const option of [...graphSelect.options])if(option.value&&!choices.has(option.value))option.remove();
   for(const g of choices.values()){let option=[...graphSelect.options].find(o=>o.value===g.id);if(!option){option=make('option',null,{value:g.id});graphSelect.append(option)}option.textContent=(g.key||'Captured local definition')+(g.version?' · '+g.version:'');option.title=g.id}
   graphSelect.value=current.filters.graph_id;
   if(data.graphs_omitted)current.coverage.textContent+=' '+data.graphs_omitted+' graph choices omitted by the selector bound; the current filter is retained.';
   const select=current.content.querySelector('select[aria-label="Session"]'),sessions=[...new Set(data.sessions||data.rows.map(r=>r.session))].filter(Boolean).sort().slice(0,100);
   const complete=Array.isArray(data.sessions)&&data.sessions_complete!==false&&(data.sessions_omitted??0)===0;
   current.sessionSnapshot={sessions,complete};
   if(current.filters.session&&!sessions.includes(current.filters.session))current.sessionNotice.textContent='Selected engine session is not in the bounded retained choices. Its filter remains active; access is never widened.';
   else current.sessionNotice.textContent='';
   if(current.filters.session&&!sessions.includes(current.filters.session))sessions.push(current.filters.session);
   reconcileOptions(select,[['','All retained sessions'],...sessions.map(session=>[session,session===fleet?.history_session?'Current engine session':'Engine session · '+sessionIdentity(session)])],current.filters.session);
   if(data.sessions_omitted)current.coverage.textContent+=' '+data.sessions_omitted+' session choices omitted by the selector bound; the current filter is retained.';
  }
  current.rows=data.rows;if(!failure)lastViewResponses.set(current.kind,{path,data});pageAccepted('list');if(failure)pageIssue('list',failure.message,()=>loadList(true));if(!data.rows.length){const tr=make('tr');tr.append(make('td','No matching retained contexts.',{colspan:7}));current.body.append(tr)}
  if(current.selected)await refreshQuick(current);
 }catch(e){if(list===current&&current.path===path){current.failures=(current.failures||0)+1;current.retryAt=Date.now()+Math.min(30000,1000*2**Math.min(5,current.failures));pageIssue('list',e.message,()=>loadList(true))}}
}
async function selectRow(row,keyboard=false){if(!list)return;list.selected=row.id;list.detail=null;list.quick.hidden=false;list.quick.inert=false;list.returnFocus=list.body.querySelector('[data-context="'+row.id+'"]');saveRoute();for(const tr of list.body.children)tr.classList.toggle('selected',tr.dataset.context===row.id);list.quick.replaceChildren(note('Loading selected context…'));await refreshQuick(list);if(keyboard)list?.quick.querySelector('button')?.focus({preventScroll:true})}
async function refreshQuick(current){
 const key=current.selected;if(!key||current.quickReading)return;current.quickReading=true;
 try{const data=await api('/api/context?id='+key);if(list!==current||current.selected!==key)return;
 current.detail=data;renderQuick(data);clearReadNotice(current.quick);
 let gap=current.quick.querySelector('.filter-gap');
 if(!current.rows.some(r=>r.id===key)){if(!gap){gap=note('Selected context is outside this page or filter. Its details remain available.');gap.classList.add('filter-gap');current.quick.append(gap)}}else gap?.remove();
 }catch(e){if(list===current&&current.selected===key){if(!current.detail)current.quick.replaceChildren();readNotice(current.quick,'Selected evidence unavailable: '+e.message,()=>refreshQuick(current))}}
 finally{current.quickReading=false;if(list===current&&current.selected!==key)refreshQuick(current)}
}
function clearQuickSelection(restoreFocus=true){
 if(!list)return;list.selected=null;list.detail=null;list.quick.hidden=true;list.quick.inert=true;list.quick.replaceChildren();
 for(const row of list.body.children)row.classList.remove('selected');saveRoute();
 if(restoreFocus)(list.returnFocus?.isConnected?list.returnFocus:list.focusTarget)?.focus({preventScroll:true});list.returnFocus=null;
}
function renderQuick(data){if(!list)return;list.quick.hidden=false;list.quick.inert=false;const q=make('div',null,{class:'quick-content'}),row=data.row,top=make('div',null,{class:'quick-heading'});top.append(sectionHeading('Context '+(list.kind==='history'?(row?.display_id||'unavailable'):data.context_id),'evidence.retained','About retained context evidence'),button('Close details',clearQuickSelection,{'aria-label':'Close quick details'}));q.append(top);if(!row){q.append(note(data.error||'Evidence unavailable'));const old=list.quick.querySelector(':scope > .quick-content');if(old)sync(old,q);else list.quick.replaceChildren(q);return}
 q.append(stateBadge(row),contextProgress(row),tree({graph:row.graph,version:row.version,iteration:row.iteration}),accessBox(row.access));if(data.summary_only)q.append(note('Recovered terminal summary only; detailed evidence was not captured.'));
 q.append(make('details',null,{class:'quick-provenance'}));q.lastChild.append(make('summary','Execution provenance'),tree({...locationDetails(row),capture_session:data.session||'Unknown'}));
 const archived=list.kind==='history';
 q.append(button(archived?'View summary':'Open context',()=>go(contextLink(row.id,archived?'summary':'graph',list.kind)),{class:'wide'}),lifecycle(row,archived));const old=list.quick.querySelector(':scope > .quick-content');if(old)sync(old,q);else list.quick.replaceChildren(q);
}
function graphTitle(g){return g.key??'Local definition'}
function graphActions(g){
 const actions=make('div',null,{class:'graph-actions'});
 actions.append(button('Open definition',()=>go('/graphs?id='+encodeURIComponent(g.id))),
  button('Related contexts',()=>openList('contexts',{graph_id:g.id})));
 return actions;
}
function graphCatalog(data,target){
 const saved=routeStates.graphs||{},deck=controlDeck(target),{stage,footer}=tableShell(target),state={search:saved.search||'',registration:saved.registration||'',sort:saved.sort||'name-asc'};
 target.catalog={state,scroll:null};deck.filters.classList.add('graph-filters');
 deck.utility.append(make('p',(data.pending?'Captured definitions':data.graphs.length+' captured '+(data.graphs.length===1?'definition':'definitions'))+' · Structural views, not execution results.',{class:'muted graph-catalog-summary'}));
 const search=make('input',null,{type:'search',placeholder:'Search graph name or identity','aria-label':'Search graph name or identity'});search.value=state.search;
 const wrap=make('div',null,{class:'table-wrap graph-catalog',tabindex:'0','aria-label':'Captured graph definitions'});target.catalog.scroll=wrap;
 const table=make('table'),head=make('thead'),labels=make('tr'),body=make('tbody'),empty=make('p','No definitions match these filters.',{class:'engine-empty',role:'status'});
 for(const title of ['Graph','Version','Registration','Actions'])labels.append(make('th',title,{scope:'col'}));head.append(labels);
 const rows=new Map();for(const g of data.graphs){
  const row=make('tr',null,{'data-graph-id':g.id}),name=make('td'),version=make('td',g.version??'Unknown'),registration=make('td'),actions=make('td');
  name.append(make('strong',graphTitle(g)));if(!g.registered)name.append(make('small','Capture reference: '+g.id,{class:'graph-capture-reference'}));
  registration.append(make('span',g.registered?'Registered':'Local · unregistered',{class:'badge status-badge',title:g.registered?'Registered':'Local · unregistered'}));actions.append(graphActions(g));row.append(name,version,registration,actions);rows.set(g.id,row);
 }
 const update=()=>{
  const query=state.search.toLowerCase(),matches=data.graphs.filter(g=>(!query||[g.key,g.id].some(v=>String(v??'').toLowerCase().includes(query)))&&(!state.registration||String(Boolean(g.registered))===state.registration));
  const version=state.sort.startsWith('version'),direction=state.sort.endsWith('desc')?-1:1;
  matches.sort((a,b)=>direction*String(version?a.version??'':graphTitle(a)).localeCompare(String(version?b.version??'':graphTitle(b)),undefined,{numeric:version})||a.id.localeCompare(b.id));
  body.replaceChildren(...matches.map(g=>rows.get(g.id)));empty.hidden=matches.length>0;
  empty.textContent=data.pending?'Loading captured definitions…':data.graphs.length?'No definitions match these filters.':'No definition has been captured yet.';
  footer.replaceChildren();if(!data.pending){if(data.gap){const coverage=make('div',null,{class:'data-notices',tabindex:'0','aria-label':'Graph capture coverage'});coverage.append(make('p',data.gap));footer.append(coverage)}footer.append(make('span',matches.length+' of '+data.graphs.length+' captured definitions'))}saveRoute();
 };
 const change=(key,value)=>{state[key]=value;wrap.scrollTop=0;update()};search.oninput=()=>change('search',search.value);
 const statuses=[...new Set(data.graphs.map(g=>String(Boolean(g.registered))))].sort();
 deck.filters.append(search,inputFilter('Registration','registration',[['','Any status'],...statuses.map(v=>[v,v==='true'?'Registered':'Local · unregistered'])],state.registration,change),inputFilter('Sort','sort',[['name-asc','Graph name A–Z'],['name-desc','Graph name Z–A'],['version-asc','Version ascending'],['version-desc','Version descending']],state.sort,change));
 table.append(head,body);wrap.append(table,empty);stage.append(wrap);update();wrap.scrollTop=saved.tableScroll||0;
}
function mountGraphs(query){
 const view=dataView('Graphs','Captured definitions available to this dashboard','dashboard.graphs','graphs-view'),target=view.content;target.classList.add('graph-browser');graphList=target;
 const ticket=epoch,previous=lastViewResponses.get('graphs');
 if(previous&&!query.get('id')){graphCatalog(previous.data,target);pageAccepted()}
 else graphCatalog({graphs:[],pending:true},target);
 const load=async()=>{try{
  const data=await api('/api/graphs');if(epoch!==ticket||graphList!==target)return;
  if(query.get('id')){const chosen=data.graphs.find(g=>g.id===query.get('id'));if(chosen){pageState.issues.delete('graphs');await openDefinition(chosen);return}}
  saveRoute();pageState.restoreFocus=Boolean(pageState.empty?.contains(document.activeElement));target.replaceChildren();graphCatalog(data,target);if(query.get('id'))target.querySelector('.data-footer').prepend(make('span','Selected definition expired or unavailable.'));lastViewResponses.set('graphs',{data});pageAccepted('graphs');
 }catch(e){if(epoch===ticket&&graphList===target)pageIssue('graphs',e.message,load)}};load();
}
async function openDefinition(g){
 const ticket=epoch,target=graphList;
 try{
  const data=await api('/api/graph?id='+encodeURIComponent(g.id));
  if(epoch!==ticket||graphList!==target)return;
  const heading=make('div',null,{class:'graph-definition-heading'}),identity=make('div');
  identity.append(make('h2',graphTitle(g)),make('p','Version '+(g.version??'Unknown')+' · '+(g.registered?'Registered':'Local · unregistered'),{class:'muted'}));
  const actions=make('div',null,{class:'graph-actions'});
  actions.append(button('All captured graphs',()=>go('/graphs')),button('Related contexts',()=>openList('contexts',{graph_id:g.id})));
  heading.append(identity,actions);
  target.replaceChildren(heading,note('Structural definition only. No execution is implied.'),accessBox());
  const host=make('div',null,{class:'graph-host'});target.append(host);const w=target.graphView={id:'definition:'+g.id,data:{graph_id:g.id},canvasScope:g.id,tab:'graph',viewer:mountCanvas(host,data.definition),graphState:lastGraphNavigation};restoreGraphState(w);if(pageState){pageState.shell=host;pageAccepted('definition')}
 }catch(e){if(epoch===ticket&&graphList===target)pageIssue('definition',e.message,()=>openDefinition(g))}
}
function captureGraphState(w){
 const v=w.viewer;if(!v?._graph||!v.svg||!v.viewport.getClientRects().length)return;
 // Tab clicks capture before hiding the body. The later hashchange must not
 // replace that camera with the zero scroll offsets of a display:none viewport.
 w.graphState={context:w.id,scope:w.canvasScope??w.data?.graph_id,graph:v._graph.id,
  camera:[v.scale,v.viewport.scrollLeft,v.viewport.scrollTop,v.svg.style.margin,v.autoFit],
  margins:['marginLeft','marginTop','marginRight','marginBottom'].map(k=>v.svg.style[k]),
  selection:v.selected,info:!v.graphInfo.hidden,details:!v.inspector.hidden,
  active:v.activePanel===v.graphInfo?'info':'details',reiteration:v.reiteration.checked,
  iteration:v.iterationSelect?.value,search:v.search.value,searchOpen:Boolean(v.searchResults.childElementCount),issue:v._graph.findings[v.issueIndex]?.id,
  infoScroll:v.graphInfo.querySelector('.panel-content')?.scrollTop||0,
  detailScroll:v.inspector.querySelector('.panel-content')?.scrollTop||0};
}
function restoreGraphState(w){
 const v=w.viewer,state=w.graphState;w.graphState=null;
 if(!state||state.context!==w.id||state.scope!==w.data?.graph_id||state.graph!==v._graph?.id)return;
 const focused=document.activeElement;
 if(state.iteration!=null&&v.iterationSelect&&[...v.iterationSelect.options].some(o=>o.value===state.iteration)){v.iterationSelect.value=state.iteration;v.iterationSelect.dispatchEvent(new Event('change'))}
 if(state.reiteration&&!v.reiteration.disabled){v.reiteration.checked=true;v.reiteration.dispatchEvent(new Event('change'))}
 if(state.selection&&v.entities.has(state.selection))v.select(state.selection);
 v._openGraphInfo(state.info);
 v.openInspector(state.details&&Boolean(v.selected));
 v.activePanel=state.active==='info'?v.graphInfo:v.inspector;v._updateDrawers();
 v.search.value=state.search;v.searchEntities();if(!state.searchOpen)v.searchResults.replaceChildren();
 const issue=v._graph.findings.findIndex(f=>f.id===state.issue);
 if(issue>=0){v.issueIndex=issue;v.issueCount.textContent=`${issue+1} / ${v._graph.findings.length} issues`}
 v.zoom(state.camera[0]);for(const [i,k]of ['marginLeft','marginTop','marginRight','marginBottom'].entries())v.svg.style[k]=state.margins[i];
 // The graph body was display:none in the other tab; lay it out before restoring scroll.
 v.viewport.getBoundingClientRect();v.viewport.scrollTo(state.camera[1],state.camera[2]);v.autoFit=state.camera[4];
 // A revealed flex viewport can gain its final scroll extent in the next layout
 // frame. Restore that saved tab camera before paint if Chromium clamped it.
 requestAnimationFrame(()=>{if((workspace===w||graphList?.graphView===w)&&w.tab==='graph'&&w.viewer===v&&v.viewport.isConnected&&
   (v.viewport.scrollLeft!==state.camera[1]||v.viewport.scrollTop!==state.camera[2]))
   v.viewport.scrollTo(state.camera[1],state.camera[2])});
 for(const [panel,top]of [[v.graphInfo,state.infoScroll],[v.inspector,state.detailScroll]]){const content=panel.querySelector('.panel-content');if(content)content.scrollTop=top}
 // Restoring an existing narrow-screen selection is not a fresh user selection:
 // do not steal focus from the workspace tab that activated this remount.
 if(focused&&focused!==document.body&&focused.isConnected)focused.focus({preventScroll:true});
 v.hoverId=v.focusId=null;v.highlight();
}
const workspaceTabs=runPanels.tabs;
function mountContext(id,tab,origin,same){
 if(!workspaceTabs.some(n=>n.toLowerCase()===tab))tab='summary';
 if(!same){
  const header=make('section',null,{class:'workspace-head'}),identity=make('div',null,{class:'workspace-identity'});
  const back=button(null,()=>go('/'+origin),{class:'workspace-back','aria-label':'Back to '+origin});back.append(make('span','←',{'aria-hidden':'true'}),make('span','Back to '+origin));
  identity.append(back,make('h1',origin==='history'?'Opening context…':'Context '+id),make('div','Loading…',{id:'work-state'}),make('div',null,{id:'work-progress'}));
  const actions=make('div',null,{class:'workspace-actions'});actions.append(make('div',null,{id:'work-controls'}));header.append(identity,actions);
  const gap=make('p','',{id:'work-filter-gap',class:'workspace-notice',role:'status'});header.append(gap);
  const tabs=make('nav',null,{class:'tabs',role:'tablist','aria-label':'Context workspace'}),panel=make('section',null,{class:'tab-content workspace-stack',id:'workspace-panel',role:'tabpanel',tabindex:'0'});tabs.onkeydown=tabKeys;main.append(header,tabs,panel);
  workspace={id,origin,tab:null,data:null,tabs,panel,views:new Map(),body:null,viewer:null,graphFinalized:false,recordKey:null,recordPage:0,graphState:lastGraphNavigation};
  for(const name of workspaceTabs)tabs.append(button(name,()=>{const next=name.toLowerCase();if(w.body&&w.tab!==next){if(w.tab==='graph')captureGraphState(w);w.body.classList.add('inactive');w.body.inert=true;w.body.setAttribute('aria-hidden','true')}go(contextLink(id,next,origin))},{role:'tab',id:'workspace-tab-'+name.toLowerCase(),'aria-controls':'workspace-panel','aria-selected':'false',tabindex:'-1','data-tab':name.toLowerCase()}));
 }
 const w=workspace,changed=w.tab!==tab;w.origin=origin;
 if(changed&&w.tab==='graph'&&w.viewer){if(!w.graphState)captureGraphState(w);w.viewer.hoverId=w.viewer.focusId=null;w.viewer.highlight()}
 if(changed&&w.body){w.body.classList.add('inactive');w.body.inert=true;w.body.setAttribute('aria-hidden','true')}
 w.tab=tab;
 w.tabs.querySelectorAll('button').forEach(n=>{const selected=n.dataset.tab===tab;n.setAttribute('aria-selected',String(selected));n.tabIndex=selected?0:-1});
 w.panel.setAttribute('aria-labelledby','workspace-tab-'+tab);w.panel.dataset.tab=tab;
 let body=w.views.get(tab);if(!body){body=make('div',null,{class:'workspace-body','data-view':tab});w.views.set(tab,body);w.panel.append(body)}
 w.body=body;body.classList.remove('inactive');body.inert=false;body.removeAttribute('aria-hidden');
 if(changed&&tab==='graph'&&w.viewer)restoreGraphState(w);
 if(changed&&!window.matchMedia('(prefers-reduced-motion: reduce)').matches){body.getAnimations().forEach(a=>a.cancel());body.animate([{opacity:.55},{opacity:1}],{duration:120})}
 if(w.data){if(tab==='graph'&&w.viewer){refreshCanvas(w)}else renderTab(w.data,Boolean(body.childElementCount));}
 else if(!body.childElementCount)body.append(note(origin==='history'?'Opening…':'Loading '+tab+'…'));
 w.needsRender=!w.data;loadWorkspace(true);
}
async function loadWorkspace(render=false){
 if(!workspace)return;const current=workspace,requestServiceEpoch=serviceEpoch;current.needsRender||=!current.data;if(!render&&Date.now()<(current.retryAt||0))return;
 if(current.reading)return current.reading;
 current.reading=(async()=>{try{
  const data=await api('/api/context?id='+current.id);if(workspace!==current||requestServiceEpoch!==serviceEpoch)return;
  current.failures=0;current.retryAt=0;current.data=data;current.status=data.error?'unavailable':data.loading?'unavailable':'ready';clearReadNotice(current.body);
  const header=$('#work-state');
  if(data.row){header.parentNode.querySelector('h1').textContent='Context '+(data.row.display_id||data.row.id);workStatus(data.row);replaceStable($('#work-controls'),lifecycle(data.row,current.origin==='history'))}
  else header.textContent=data.error||'Context evidence unavailable';
  const f=routeStates[current.origin]||{},row=data.row;
  const mismatch=row&&((f.state&&f.state!==row.state)||(f.graph_id&&f.graph_id!==data.graph_id)||(f.search&&!`${row.id} ${row.graph} ${row.version}`.toLowerCase().includes(f.search.toLowerCase())));
  $('#work-filter-gap').textContent=mismatch?'This context no longer matches the originating list filter; the workspace remains open.':'';
  if(current.needsRender||data.error||data.loading){current.needsRender=false;renderTab(data)}
  else if(current.tab==='graph'){const stamp=current.body.querySelector('.evidence-stamp small');if(stamp)stamp.textContent='Evidence sampled: '+localTime(data.evidence_sampled_at);if(current.viewer&&current.canvasScope!==data.graph_id)await refreshCanvas(current);const caption=current.body.querySelector('.graph-caption');if(caption)caption.textContent=graphCaption(data);if(!current.viewer){const host=current.body.querySelector('.graph-host');if(host&&Date.now()>=(current.canvasRetryAt||0))await loadCanvas(host)}else await updateGraph()}
  else if(current.tab==='records')renderRecords(data,current.body);
  else renderTab(data,true);
 }catch(e){if(workspace!==current||requestServiceEpoch!==serviceEpoch)return;current.status='error';current.failures=(current.failures||0)+1;current.retryAt=Date.now()+Math.min(30000,1000*2**Math.min(5,current.failures));const header=$('#work-state');if(!current.data?.row)header.textContent='Context unavailable';
  if(!current.data)current.body.replaceChildren();readNotice(current.body,(current.data?'Evidence stale. ':'Context request failed. ')+e.message,()=>loadWorkspace(true));
 }finally{current.reading=null}})();return current.reading;
}
function renderTab(data,incremental=false){
 const w=workspace;if(!w)return;
 if(w.tab==='graph'&&w.viewer){updateGraph();return}
 if(w.tab==='records'){if(!w.recordUI)w.body.replaceChildren();renderRecords(data,w.body);return}
 if(incremental&&w.tab!=='graph'){
  const source=make('div',null,{class:'workspace-body','data-view':w.tab});buildTab(data,source);sync(w.body,source);
 }else{w.body.replaceChildren();buildTab(data,w.body)}
}
function graphCaption(data){return data.archived?'Captured definition for this archived run · read-only':data.finalized?'Captured definition with finalized execution evidence.':'Live graph · sampled iteration '+(data.observation?.progress?.iteration??'unavailable')+' · Short executions may finish between updates; execution counts restart each iteration.'}
function buildTab(data,p){const w=workspace;if(data.loading){p.append(note('Evidence capture pending…'));return}if(data.error){p.append(note(data.error,true));return}if(data.capture_gap)p.append(note(data.capture_gap));if(['graph','summary','failure','records','activity'].includes(w.tab)){const stamp=make('div',null,{class:'inline evidence-stamp'});stamp.append(make('small','Evidence sampled: '+localTime(data.evidence_sampled_at)));p.append(stamp)}if(w.tab==='graph'&&data.archived&&!data.graph_available){p.append(note((data.graph_availability||'Graph unavailable: no captured definition in this archive row.')+(data.summary_only?' Only the recovered terminal summary is available.':' Retained report, records and artifact history remain available.')));return}if(w.tab==='graph'){p.append(make('p',graphCaption(data),{class:'muted graph-caption'}));const exportLink=make('a','Export graph',{class:'graph-export',href:'/context/'+encodeURIComponent(w.id)+'/graph',download:'context-'+(data.context_id||'archive')+'.html'});p.append(exportLink);const host=make('div',null,{class:'graph-host'});p.append(host);loadCanvas(host);return}runPanels.renderPanel(w.tab,data,p)}
async function loadCanvas(host){const w=workspace,ticket=epoch,requestServiceEpoch=serviceEpoch;if(w.canvasReading)return;w.canvasReading=true;try{const data=await api('/api/canvas?id='+w.id);if(workspace!==w||ticket!==epoch||requestServiceEpoch!==serviceEpoch||!host.isConnected)return;if(data.loading){host.replaceChildren(note('Graph capture pending…'));return}w.canvasFailures=0;w.canvasRetryAt=0;w.viewer=mountCanvas(host,data.payload);w.canvasSignature=JSON.stringify(data.payload);w.canvasScope=w.data?.graph_id;restoreGraphState(w);w.graphFinalized=data.finalized;await updateGraph()}catch(e){if(workspace!==w||ticket!==epoch||requestServiceEpoch!==serviceEpoch)return;w.canvasFailures=(w.canvasFailures||0)+1;w.canvasRetryAt=Date.now()+Math.min(30000,1000*2**Math.min(5,w.canvasFailures));if(host.isConnected)host.replaceChildren(note('Graph unavailable: '+e.message,true),button('Retry graph',()=>loadCanvas(host)))}finally{w.canvasReading=false}}
function mountCanvas(host,payload){const viewer=make('jayrun-graph',null,{theme:theme()}),data=make('script',JSON.stringify({payload,display:{theme:theme(),motion:false}}),{type:'application/json'});viewer.append(data);host.replaceChildren(viewer);const root=viewer.shadowRoot;if(root){runPanels.embedGraph(viewer);viewer.addEventListener('jayrun-selection',()=>{if(!workspace)return;const inspector=root.querySelector('#component-details');if(inspector&&!inspector.hidden&&!inspector.querySelector('.context-links')){const links=make('div',null,{class:'context-links'});links.append(button('View configuration',()=>go(contextLink(workspace.id,'configuration',workspace.origin))),button('View settings',()=>go(contextLink(workspace.id,'settings',workspace.origin))));inspector.append(links)}})}return viewer}
async function refreshCanvas(w){
 if(w.refreshingCanvas||w.canvasReading||!w.viewer)return;
 w.refreshingCanvas=true;const requestServiceEpoch=serviceEpoch,requestEpoch=epoch;
 try{
  const data=await api('/api/canvas?id='+w.id);if(workspace!==w||requestEpoch!==epoch||requestServiceEpoch!==serviceEpoch||!w.viewer||data.loading)return;
  const signature=JSON.stringify(data.payload);
  if(signature!==w.canvasSignature){
   const host=w.viewer.parentNode;captureGraphState(w);w.viewer.dispose();
   w.viewer=mountCanvas(host,data.payload);w.canvasSignature=signature;w.canvasScope=w.data?.graph_id;w.graphFinalized=data.finalized;restoreGraphState(w);
  }
  await updateGraph();
 }catch(error){if(workspace===w&&requestEpoch===epoch&&requestServiceEpoch===serviceEpoch)readNotice(w.views.get('graph'),'Captured graph refresh unavailable; last captured view retained. '+error.message,()=>refreshCanvas(w))}
 finally{w.refreshingCanvas=false}
}
async function updateGraph(){const w=workspace;if(!w?.viewer||w.tab!=='graph')return;const ticket=epoch;if(w.data?.row?.finalized&&!w.graphFinalized){const host=w.viewer.parentNode;captureGraphState(w);w.viewer.dispose();w.viewer=null;await loadCanvas(host);return}if(w.data?.archived){w.views.get('graph')?.querySelector('.graph-error')?.remove();return}try{const value=w.data?.observation?{observation:w.data.observation}:await api('/api/live?id='+w.id);if(epoch===ticket&&workspace===w&&w.viewer){w.viewer.updateLive(value.observation);w.views.get('graph')?.querySelector('.graph-error')?.remove()}}catch(e){if(epoch===ticket){let n=w.views.get('graph')?.querySelector('.graph-error');if(!n){n=note('');n.classList.add('graph-error');w.views.get('graph')?.append(n)}n.textContent='Graph observation stale: '+e.message}}}
function download(name,text,type='application/json'){const url=URL.createObjectURL(new Blob([text],{type})),a=make('a',null,{href:url,download:name});a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
async function poll(){if(disposed||polling)return;clearTimeout(timer);if(document.hidden){timer=setTimeout(poll,1500);return}polling=true;try{const next=await api('/api/fleet');const switched=Boolean(fleet?.controller&&next?.controller&&String(fleet.controller)!==String(next.controller));if(switched){
  // A controller replacement changes the observation service, not the selected
  // workload. Invalidate in-flight evidence reads and keep the last usable
  // workspace/graph until the replacement service supplies fresh data.
  serviceEpoch++;epoch++;lastViewResponses.clear();pausedDisplays.clear();pending.clear();cancelReads(()=>false);if(workspace){workspace.retryAt=0;workspace.canvasRetryAt=0}
 }if(next.pressure_gap&&!Array.isArray(next.pressures)&&fleet?.engine_id===next.engine_id)next.pressures=fleet.pressures;fleet=next;connectionLost=false;connectionFailure='';capturePressureReference(next);stale=!next.ready;received=Date.now();$('#engine-name').textContent='Local engine · '+next.engine;$('#connection').className=stale?'state-paused':'state-running';$('#connection').textContent=switched?'Reconnected · refreshing selected context':stale?'Initializing':'● Connected';$('#owner-id').textContent='Controller '+next.controller;$('#app-version').textContent='Version '+(next.version||'unavailable');for(const [id,p]of pending){const r=next.requests.find(r=>r.id===p.id);if(r&&r.status==='submitted')pending.set(id,{...r,message:r.message});if(r&&r.status!=='submitted'){pending.delete(id);const key='jayrun.control.'+id;if(r.action==='stop'&&r.status==='observed')sessionStorage.setItem(key,'Stop · observed');else if(r.status==='observed')sessionStorage.removeItem(key);else sessionStorage.setItem(key,r.action+' · '+r.status)}}updateOverview();updateEngines();if(overview)void loadOverviewOutcomes();if(list)await loadList(false);if(workspace)await loadWorkspace(false);updatePageStatus()}catch(e){stale=true;connectionLost=true;connectionFailure=e.message;updatePageStatus();$('#connection').className='state-paused';$('#connection').textContent='Disconnected · stale view';refreshControls()}finally{polling=false;if(!disposed)timer=setTimeout(poll,750)}}
const receiptTimer=setInterval(()=>{updatePressureAges();$('#received').textContent=received?'Received '+Math.floor((Date.now()-received)/1000)+'s ago':''},1000);
$('#owner-stop').onclick=()=>confirmAction('Stop dashboard '+(fleet?.controller||''),'Stop this controller and close the local dashboard service.',async()=>{try{await api('/api/owner',{action:'stop'})}catch(e){$('#connection').textContent=e.rejected?'Rejected: '+e.message:'Shutdown delivery unknown'}});
window.addEventListener('pagehide',()=>{disposed=true;help.dispose();pausedDisplays.clear();clearTimeout(timer);clearInterval(receiptTimer);activeFetch.forEach(c=>c.abort());document.querySelectorAll('jayrun-graph').forEach(v=>v.dispose());saveRoute()},{once:true});
$('#about-open').onclick=()=>{$('#about-version').textContent='Jayrun '+(fleet?.version||'version unavailable');$('#about').showModal()};$('#about-close').onclick=()=>$('#about').close();
main.append(note('Connecting to dashboard…'));api('/api/fleet').then(data=>{fleet=data;capturePressureReference(data);routeTo();poll()}).catch(e=>{connectionLost=true;connectionFailure=e.message;routeTo();updatePageStatus();poll()});
})();
'''.replace('__JAYRUN_HELP__', _help_script()).replace(
    '__JAYRUN_COPY__', files('jayrun.visualization').joinpath('_copy.js').read_text(encoding='utf-8'))
