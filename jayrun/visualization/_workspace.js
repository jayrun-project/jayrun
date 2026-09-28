/* Shared context presentation. Hosts own transport, lifecycle and navigation. */
(() => {
  if (globalThis.JayrunRunPanels) return;
function duration(value){
 if(typeof value!=='number'||!Number.isFinite(value)||value<0)return '—';
 if(value===0)return '0 s';
 if(value<0.001)return (value*1e6).toPrecision(3)+' µs';
 if(value<1)return (value*1000).toPrecision(3)+' ms';
 return value<60?value.toFixed(3)+' s':Math.floor(value/60)+'m '+(value%60).toFixed(1)+'s';
}
  function themeControl(value, onChange) {
    const group = document.createElement('fieldset');
    group.className = 'theme theme-switch'; group.setAttribute('aria-label', 'Theme');
    group.dataset.help = 'view.theme';
    const legend = document.createElement('legend'); legend.textContent = 'Theme'; group.append(legend);
    for (const mode of ['light', 'dark']) {
      const label = document.createElement('label'), input = document.createElement('input');
      input.type = 'radio'; input.name = 'theme'; input.value = mode; input.checked = value === mode;
      const title = mode === 'light' ? 'Light' : 'Dark'; input.setAttribute('aria-label', title);
      input.addEventListener('change', () => { if (input.checked) onChange(mode); });
      const text = document.createElement('span'); text.textContent = title;
      label.append(input, text); group.append(label);
    }
    return group;
  }
  function create(host) {
    const {make, note, button, sectionHeading, replaceStable, download, copyText, shortFailure} = host;


function localTime(value){if(value==null||value==='')return 'Unavailable';const date=new Date(value);return Number.isFinite(date.getTime())?new Intl.DateTimeFormat(undefined,{year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',timeZoneName:'short'}).format(date):'Unavailable'}

function tree(value,times=false){if(value===null)return make('span','None');if(typeof value!=='object')return make('span',typeof value==='string'?(value===''?'""':value):String(value));if(Array.isArray(value)){const box=make('div');value.forEach((v,i)=>{const d=make('details');d.append(make('summary','Entry '+(i+1)),tree(v,times));box.append(d)});return box}const dl=make('dl',null,{class:'tree'});Object.entries(value).forEach(([k,v])=>{const dd=make('dd');dd.append(times&&['recorded_at','occurred_at','submitted_at','observed_at','created_at','finished_at','updated_at'].includes(k)?make('span',localTime(v),{title:typeof v==='string'?v:''}):tree(v,times));dl.append(make('dt',k.replaceAll('_',' ')),dd)});return dl}

function conciseValue(value){
 if(value===null)return 'None';if(value===undefined)return 'Not captured';
 if(typeof value!=='object')return String(value)===''?'""':String(value);
 if(value.availability)return value.availability+(value.reason?' · '+value.reason:'');
 return Array.isArray(value)?value.length+' retained items':Object.keys(value).length+' retained fields';
}

function rawDetails(value,times=false){const d=make('details');d.append(make('summary','Full retained fields'),tree(value,times));return d}

function configurationCard(item){
 const box=make('section',null,{class:'box configuration-card'});box.append(make('h3',(item.owner||'Unknown owner')+' · '+(item.name||item.id||'Unnamed configuration')));
 if(item.type)box.append(make('p','Type: '+item.type));if(item.description)box.append(make('p',item.description));
 for(const [field,label]of [['effective','Effective'],['submitted','Submitted'],['declared_default','Declared default']])if(Object.hasOwn(item,field))box.append(make('p',label+': '+conciseValue(item[field])));
 if(item.provenance)box.append(note(item.provenance));box.append(rawDetails(item));return box;
}

function activitySummary(item){
 if(!item||typeof item!=='object')return conciseValue(item);
 const parts=[item.type||item.kind||(item.action?'Control request':'Retained event')];
 if(item.previous_state!=null||item.next_state!=null)parts.push((item.previous_state??'Unrecorded')+' → '+(item.next_state??'Unrecorded'));
 if(item.action)parts.push(item.action);if(item.status)parts.push(item.status);
 for(const [key,label]of [['step_index','Step'],['iteration','Iteration'],['revision','Revision'],['attempt','Attempt']])if(item[key]!=null)parts.push(label+' '+item[key]);
 const time=['occurred_at','recorded_at','submitted_at'].find(k=>item[k]!=null);if(time)parts.push(localTime(item[time]));
 return parts.join(' · ');
}

function activityList(items){
 const box=make('div',null,{class:'activity-list'});if(!items?.length)box.append(note('No retained entries; absence does not establish complete observation.'));
 for(const item of items||[]){const section=make('section',null,{class:'box activity-entry'});section.append(make('h3',activitySummary(item)));
  if(item?.message)section.append(make('p',item.message));if(item?.failure)section.append(note('Failure: '+shortFailure(item.failure),true));
  if(item?.availability)section.append(note(conciseValue(item)));section.append(rawDetails(item,true));box.append(section)}return box;
}

function stateBadge(row,historyOutcome=false,tableCell=false){
 const group=make('span',null,{class:'state-summary'+(historyOutcome?' history-outcome':'')}),badge=make('span',row.state==='stopped'?'Legacy stop outcome':row.state==='paused'?'Paused':row.state_label||row.state.toUpperCase(),{class:'badge state-'+row.state});group.append(badge);
 if(row.stop_requested&&!row.finalized&&!['stopped','failed','aborted','finished','rejected'].includes(row.state))group.append(make('span','Stop requested · draining iteration',{class:'stop-intent'}));
 if(row.state==='stopped')badge.title='Recorded by an older engine. Preserved as legacy evidence; not a current lifecycle state.';
 if(row.stop_requested&&row.finalized)group.append(make('span','Stop accepted',{class:'stop-record'}));
 if(row.finalized&&!historyOutcome)group.append(make('span','Finalized',{class:'outcome-label'}));
 if(tableCell){badge.classList.add('status-badge');badge.title=badge.title||badge.textContent;const primary=make('span',null,{class:'state-primary'}),secondary=make('span',null,{class:'state-secondary'});primary.append(badge);secondary.append(...group.childNodes);group.append(primary,secondary);group.classList.add('state-cell')}
 return group;
}

function contextProgress(row,compact=false){
 const pauseKey=JSON.stringify([host.serviceEpoch(),row.engine_id,row.id,row.generation,row.graph_id]);
 if(row.state==='paused'&&!row.finalized){
  if(!host.pausedDisplays.has(pauseKey)){host.pausedDisplays.set(pauseKey,{fraction:row.fraction,confidence:row.confidence,iteration:row.iteration,max_iterations:row.max_iterations});while(host.pausedDisplays.size>256)host.pausedDisplays.delete(host.pausedDisplays.keys().next().value)}
  row={...row,...host.pausedDisplays.get(pauseKey)};
 }else host.pausedDisplays.delete(pauseKey);
 const box=make('div',null,{class:'context-progress'+(compact?' compact':''),'data-state':row.state||'unavailable'}),finite=typeof row.fraction==='number'&&Number.isFinite(row.fraction),value=finite?Math.max(0,Math.min(1,row.fraction)):null;
 const paused=row.state==='paused'&&!row.finalized;
 const label=(paused?'Paused · work not advancing · ':'')+(row.summary_only?'Execution ended · progress not captured':finite?(row.finalized?'Execution ended · ':'Estimated progress · ')+(value*100).toFixed(1)+'%':row.max_iterations===null?'Unbounded context · no completion percentage':'Context progress estimate unavailable');
 const track=make('div',null,{class:'progress-track'+(finite?'':' unavailable'),role:'progressbar','aria-label':'Whole context progress','aria-valuemin':'0','aria-valuemax':'100','aria-valuetext':label});
 if(finite){track.setAttribute('aria-valuenow',String(value*100));const fill=make('span',null,{class:'progress-fill'});fill.style.width=(value*100)+'%';track.append(fill)}
 box.append(make('small',label),track);
 if(!compact){const parts=['Iteration '+(row.iteration??'unavailable')+(row.max_iterations!=null?' / '+row.max_iterations:''),paused?'Remaining work held':finite&&!row.finalized&&row.confidence!=null?'Timing sample support '+Math.round(row.confidence*100)+'% (not accuracy)':row.finalized?'Execution ended; percentage is not success':null];box.append(make('small',parts.filter(Boolean).join(' · ')));const facts=make('div',null,{class:'progress-facts'});facts.append(make('strong','Elapsed:'),make('span',duration(row.elapsed_seconds)),make('small',(row.elapsed_meaning||'Includes pauses and waits')+(paused?' · may continue while paused':'')));if(row.elapsed_seconds==null&&row.finalized)facts.append(make('small','Not retained for this historical entry'));box.append(facts)}return box;
}

function tabKeys(event){
 const buttons=[...event.currentTarget.querySelectorAll('[role=tab]')],index=buttons.indexOf(event.target);
 if(index<0)return;let next;
 if(event.key==='ArrowRight')next=(index+1)%buttons.length;
 else if(event.key==='ArrowLeft')next=(index+buttons.length-1)%buttons.length;
 else if(event.key==='Home')next=0;
 else if(event.key==='End')next=buttons.length-1;
 else return;
 event.preventDefault();buttons.forEach((b,i)=>b.tabIndex=i===next?0:-1);buttons[next].focus({preventScroll:true});
 const bar=event.currentTarget,button=buttons[next];if(button.offsetLeft<bar.scrollLeft)bar.scrollLeft=button.offsetLeft;
 else if(button.offsetLeft+button.offsetWidth>bar.scrollLeft+bar.clientWidth)bar.scrollLeft=button.offsetLeft+button.offsetWidth-bar.clientWidth;
 // Manual activation: Arrow/Home/End change focus only; Enter/Space activate.
}

function renderArtifacts(data,p){
 p.append(sectionHeading('Artifact history','evidence.artifacts','About artifact lifecycle evidence'));
 const artifacts=data.artifacts||[];
 if(artifacts.length)p.append(make('p','Showing retained artifact lifecycle evidence.',{class:'muted'}));
 if(data.artifacts_omitted)p.append(note(data.artifacts_omitted+' artifacts omitted by the display bound.'));
 if(!artifacts.length)p.append(note(data.artifact_history_availability||
  (data.artifacts_omitted?'Artifact lifecycle evidence was omitted by the display bound.':'No artifact lifecycle evidence is available in this captured view.')));
 for(const a of artifacts){
  const box=make('section',null,{class:'box'});
  box.append(make('h3','Artifact '+a.id+(a.name?' · '+a.name:'')));if(a.availability)box.append(make('p','Availability: '+a.availability));if(a.role)box.append(make('p','Role: '+a.role+(a.exit?' · exit':'')));box.append(note(a.coverage+(a.history_omitted?' '+a.history_omitted+' entries omitted by the display bound.':'')),artifactHistoryTable(a.history));p.append(box);
 }
}

function artifactHistoryTable(entries){
 const wrap=make('div',null,{class:'table-wrap artifact-history'}),table=make('table'),head=make('tr');
 ['Retained order','Iteration','Lifecycle event','Actor','Step'].forEach(t=>head.append(make('th',t)));table.append(head);
 for(const entry of entries){const row=make('tr');for(const value of [entry.retained_index,entry.iteration,entry.state,entry.actor,entry.step_index]){const cell=make('td');cell.append(value==null?make('span','Not recorded'):tree(value));row.append(cell)}table.append(row)}
 wrap.append(table);return wrap;
}

function identityFact(label,value){
 const line=make('div',null,{class:'identity-fact','data-copy-value':value||'','data-copy-label':label});
 line.append(make('strong',label),make('code',value||'Unavailable'));
 if(value){const row=make('span',null,{class:'copy-row'}),copy=button('Copy',event=>{void copyText(event.currentTarget,value)},{'aria-label':'Copy full '+label.toLowerCase(),'data-help':'action.copy'});
  row.append(copy,make('span','',{class:'copy-feedback',role:'status','aria-live':'polite','aria-atomic':'true'}));line.append(row,make('small','Manual copy: select the full value.',{class:'muted'}))}
 return line;
}

function renderSummary(data,p){
 const row=data.row||{},identities=make('section',null,{class:'summary-identities'});
 const intrinsic=data.intrinsic_graph_id||(data.archived?data.graph_id:null),current=typeof intrinsic==='string'&&/^jrg1:[0-9a-f]{64}$/.test(intrinsic);
 identities.append(sectionHeading('Identities','graph.identity','About full identities'),identityFact('Context',data.context_id),identityFact('Engine session',data.session),make('p',current?'Graph ID: '+intrinsic.slice(0,17)+'…':intrinsic?'Graph identity: legacy / unrecognized format':'Graph ID unavailable'));
 if(intrinsic){const full=make('details');full.append(make('summary','Full graph identity'),identityFact('Graph ID',intrinsic));identities.append(full)}
 if(data.graph_id&&!data.archived)identities.append(identityFact('Captured graph reference (not graph ID)',data.graph_id));
 if(row.version!=null)identities.append(identityFact('Graph version',row.version));if(row.graph_key!=null)identities.append(identityFact('Registry key',row.graph_key));
 identities.append(note('Graph ID correlates declarations; it is not context identity, exact layout identity or control authority.'));p.append(identities);
 const records=Array.isArray(data.records)?data.records.length:0;
 const imported=Boolean(row.imported),recordState=data.records_complete&&!data.records_omitted?records+' retained':records?records+' retained · Partial':imported&&data.legacy_evidence?.records?.length?'Partial · legacy display':'Not retained';
 const layout=data.graph_available?(imported?'Legacy layout':'Available'):'Unavailable';
 const config=data.configuration_retained||(!data.archived&&!data.summary_only&&Array.isArray(data.configuration))?'Available':imported&&data.configuration?.length?'Partial':'Unavailable';
 const report=data.report!=null?(imported?'Partial · legacy display':'Available'):data.evidence_coverage?'Partial':'Not retained';
 p.append(sectionHeading('Evidence',data.archived?'evidence.history':'evidence.retained','About summary evidence'),tree({Report:report,Records:recordState,'Graph layout':layout,Configuration:config}));
 p.append(tree({captured_at:data.captured_at!=null?localTime(data.captured_at*1000):'Not recorded',graph_coverage:data.graph_availability||'Captured in this dashboard session',observation_coverage:data.observation_coverage||'Observation completeness unavailable for this captured evidence',outcome:row.state,estimated_progress:row.fraction,iteration:row.iteration,failure:data.failure??row.failure,execution_location:host.locationDetails?.(row)??'Not captured'}));if(host.accessBox)p.append(host.accessBox(data.access||row.access));
 const keys=host.pins[host.workspace().id]||[];if(keys.length){p.append(make('h3','Records shown in Summary'));for(const key of keys){const last=(data.records||[]).filter(r=>r.key===key).at(-1);p.append(make('h3',key),tree(last?last.value:{availability:'not retained'}))}}
}

function renderFailure(data,p){
 p.append(sectionHeading('Failure details'));
 const failure=data.failure??data.row?.failure,step=data.failed_step??data.completed_evidence?.failed_step;
 if(data.row?.state!=='failed'&&!failure){p.append(note('No failure recorded for this context.'));return}
 if(failure){const box=make('section',null,{class:'box failure-detail'});box.append(make('h3','Failure'));if(typeof failure==='object'&&Array.isArray(failure.arguments)&&typeof failure.arguments[0]==='string')box.append(make('p',failure.arguments[0],{class:'failure-message'}));box.append(tree(failure));p.append(box)}
 else p.append(note('Failure details were not retained for this context.'));
 const box=make('section',null,{class:'box failure-detail'});box.append(make('h3','Failed step'));
 if(step){const display={...step};if(Array.isArray(step.layout_position))display.layout_position='('+step.layout_position.join(', ')+')';box.append(tree(display))}else box.append(make('p','No failed-step reference was captured.',{class:'muted'}));p.append(box);
 p.append(note('Traceback is not retained in dashboard evidence. The finalized report may contain additional recorded context.'));
}

function recordChart(entries,key,width){
 const ns='http://www.w3.org/2000/svg',el=(name,attrs={},text)=>{const n=document.createElementNS(ns,name);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!=null)n.textContent=text;return n};
 const box=make('div',null,{class:'record-chart'}),svg=el('svg',{viewBox:'0 0 '+width+' 220',class:'chart',role:'img','aria-label':key+' · recorded values by sequence'});
 const compact=width<420,left=compact?56:80,right=width-(compact?20:50),plotWidth=right-left,center=(left+right)/2,ticks=compact?3:5;
 const stride=Math.max(1,Math.ceil(entries.length/200)),sampled=entries.filter((r,i)=>i%stride===0);if(sampled.at(-1)!==entries.at(-1))sampled.push(entries.at(-1));
 const values=entries.map(r=>Number(r.value)),lo=Math.min(...values),hi=Math.max(...values),first=BigInt(entries[0].sequence),last=BigInt(entries.at(-1).sequence),span=last-first;
 const x=seq=>span?left+Number((BigInt(seq)-first)*BigInt(plotWidth*100)/span)/100:center;
 const y=value=>hi===lo?96:166-((value/2-lo/2)/(hi/2-lo/2))*132;
 const pretty=value=>Number.isInteger(value)&&Math.abs(value)<1e7?String(value):Number(value.toPrecision(4)).toString();
 for(let i=0;i<5;i++){
  const value=lo*(1-i/4)+hi*(i/4),cy=hi===lo?96:166-i*33;
  if(hi===lo&&i!==0)continue;
  svg.append(el('line',{x1:left,x2:right,y1:cy,y2:cy,stroke:'var(--line)'}),el('text',{x:left-8,y:cy+4,'text-anchor':'end',fill:'currentColor','font-size':12},pretty(value)));
 }
 for(let i=0;i<(span?ticks:1);i++){
  const seq=span?first+span*BigInt(i)/BigInt(ticks-1):first,cx=x(seq);
  const t=el('text',{x:cx,y:187,'text-anchor':'middle',fill:'currentColor','font-size':11},(span>1000000000000n||compact&&String(seq).length>8)?(i===0?'first':i===ticks-1?'last':'middle'):String(seq));t.append(el('title',{},String(seq)));
  svg.append(el('line',{x1:cx,x2:cx,y1:35,y2:166,stroke:'var(--line)'}),t);
 }
 svg.append(el('text',{x:center,y:212,'text-anchor':'middle',fill:'currentColor','font-size':13},'Recorded sequence'),el('text',{x:left,y:19,fill:'currentColor','font-size':13},'Recorded value'));
 const tooltip=make('p','Point details: hover or focus a point; exact values are also in the table.',{class:'chart-tooltip',role:'status'});
 for(const r of sampled){
  const label='Sequence '+r.sequence+' · '+key+': '+String(r.value)+['iteration','recorded_at','step_index','execution','attempt','generation'].filter(k=>r[k]!=null).map(k=>' · '+k.replaceAll('_',' ')+': '+(k==='recorded_at'?localTime(r[k]):r[k])).join('');
  const point=el('circle',{cx:x(r.sequence),cy:y(Number(r.value)),r:4,fill:'var(--accent)',tabindex:0,'aria-label':label});
  point.append(el('title',{},label));point.onmouseenter=point.onfocus=function(){this.closest('.record-chart').querySelector('.chart-tooltip').textContent=label};svg.append(point);
 }
 box.append(svg,tooltip,make('small',sampled.length+' / '+entries.length+' numeric points · '+(sampled.length<entries.length?'Downsampled · ':'')+'Exact retained values in table and export. Updates pause while inspecting a point.'));return box;
}

function renderRecords(data,p){
 const w=host.workspace(),all=data.records||[],keys=[...new Set(all.map(r=>r.key))];
 if(!w.recordUI){
  const coverage=note(''),empty=note(''),stamp=make('div',null,{class:'inline'}),layout=make('div',null,{class:'record-layout'}),keybox=make('div',null,{class:'keys'}),view=make('div',null,{class:'record-view'});layout.append(keybox,view);
  const title=make('h2'),latest=make('div',null,{class:'box record-latest'}),pin=button('',()=>{}),exp=button('Export retained records',()=>{}),search=make('input',null,{type:'search','aria-label':'Search record values',placeholder:'Filter table values only'}),toggle=button('Show chart',()=>{}),chart=make('div'),output=make('div');
  const actions=make('div',null,{class:'record-actions'});pin.dataset.help='dashboard.summary-pin';actions.append(pin,exp,toggle);const filter=make('div',null,{class:'record-filter'}),filterLabel=make('label','Table values only '),reset=button('Reset table filter',()=>{}),scope=note('Latest value, chart, Summary and export use all retained values for the selected key; this filter affects only the table.');filterLabel.append(search);filter.append(filterLabel,reset);view.append(title,latest,chart,actions,scope,filter,output);p.append(sectionHeading('Context records','evidence.records','About record and chart scope'),stamp,coverage,empty,layout);
  w.recordUI={coverage,empty,stamp,layout,keybox,title,latest,pin,exp,search,filter,reset,toggle,chart,output};
 }
 const ui=w.recordUI;ui.stamp.replaceChildren(make('small','Evidence sampled: '+localTime(data.evidence_sampled_at)));ui.coverage.textContent=(data.records_complete?'All committed records retained.':'Retained subset; earlier records may be pruned or unavailable.')+' Display omissions: '+(data.records_omitted||0)+'. Values belong to this context only.';
 ui.empty.hidden=Boolean(keys.length);ui.layout.hidden=!keys.length;ui.empty.textContent=data.record_sequence==='0'?'Verified empty committed record history.':'No displayed record keys; retained/pruned/display-limited evidence is unavailable.';if(!keys.length)return;
 if(!keys.includes(w.recordKey)){w.recordKey=keys[0];w.recordPage=0}
 const present=new Set(keys);for(const b of [...ui.keybox.children])if(!present.has(b.dataset.key))b.remove();
 for(const key of keys){let b=[...ui.keybox.children].find(n=>n.dataset.key===key);if(!b){b=button(key,()=>{w.recordKey=key;w.recordPage=0;ui.search.value='';renderRecords(w.data,p)},{'data-key':key});ui.keybox.append(b)}b.setAttribute('aria-pressed',String(key===w.recordKey))}
 const key=w.recordKey,entries=all.filter(r=>r.key===key),last=entries.at(-1);ui.title.textContent=key;
 const summary=make('div');summary.append(make('h3','Latest displayed · sequence '+last.sequence),tree(last.value));replaceStable(ui.latest,summary);
 ui.pin.textContent=(host.pins[w.id]||[]).includes(key)?'Remove from Summary':'Show in Summary';ui.pin.onclick=()=>{const values=host.pins[w.id]||[];host.pins[w.id]=values.includes(key)?values.filter(k=>k!==key):[...values.slice(-7),key];while(Object.keys(host.pins).length>32)delete host.pins[Object.keys(host.pins)[0]];host.savePins?.(host.pins);renderRecords(w.data,p)};
 ui.exp.onclick=()=>download('records-'+w.id+'.json',JSON.stringify({context_id:data.context_id||w.id,session:data.session,key,records:entries,omitted:data.records_omitted,complete:data.records_complete,display_complete:data.display_complete},null,2));
 const numeric=entries.filter(r=>r.numeric&&Number.isFinite(Number(r.value))),identity=w.id+'\n'+key;
 if(!host.chartVisibility.has(identity)){host.chartVisibility.set(identity,true);while(host.chartVisibility.size>256)host.chartVisibility.delete(host.chartVisibility.keys().next().value)}
 ui.filter.hidden=entries.length<=100&&!ui.search.value;ui.search.hidden=ui.filter.hidden;
 ui.toggle.hidden=false;ui.toggle.disabled=!numeric.length;ui.toggle.textContent=numeric.length&&host.chartVisibility.get(identity)?'Hide chart':'Show chart';ui.toggle.title=numeric.length?'Recorded numeric values':'No retained numeric scalar values for this key';
 ui.toggle.onclick=()=>{host.chartVisibility.set(identity,!host.chartVisibility.get(identity));while(host.chartVisibility.size>256)host.chartVisibility.delete(host.chartVisibility.keys().next().value);renderRecords(w.data,p)};
 const chartWidth=Math.max(240,Math.min(680,Math.floor(ui.layout.clientWidth-(matchMedia('(max-width:620px)').matches?18:34))));
 const signature=JSON.stringify([identity,host.chartVisibility.get(identity),chartWidth,numeric]);if(ui.chartSignature!==signature&&(ui.chartIdentity!==identity||!ui.chart.querySelector('circle:hover,circle:focus')||!host.chartVisibility.get(identity))){ui.chartSignature=signature;ui.chartIdentity=identity;if(host.chartVisibility.get(identity)&&numeric.length)replaceStable(ui.chart,recordChart(numeric,key,chartWidth));else ui.chart.replaceChildren()}
 const draw=()=>{
  const query=ui.search.value.toLowerCase(),rows=entries.filter(r=>(r.value===null?'None null':JSON.stringify(r.value)).toLowerCase().includes(query));ui.reset.disabled=!query;w.recordPage=Math.min(w.recordPage||0,Math.max(0,Math.ceil(rows.length/25)-1));const page=w.recordPage;
  const holder=make('div',null,{class:'record-table'}),table=make('table'),head=make('tr');['Sequence','Value','Execution step','Recorded iteration','Recorded time'].forEach(t=>head.append(make('th',t)));table.append(head);
  for(const r of rows.slice(page*25,page*25+25)){const tr=make('tr',null,{tabindex:'0','data-sequence':r.sequence});tr.append(make('td',r.sequence));const td=make('td');td.append(tree(r.value));tr.append(td,make('td',r.step_index==null?'Not captured':'Step '+r.step_index),make('td',r.iteration??'Unavailable'),make('td',localTime(r.recorded_at),{title:r.recorded_at||''}));table.append(tr)}
  if(!rows.length){const tr=make('tr');tr.append(make('td','No table values match this filter. Reset the table filter to show retained values.',{colspan:'5',role:'status'}));table.append(tr)}
  const pager=make('div',null,{class:'pager'});pager.append(button('Previous records',()=>{w.recordPage=Math.max(0,page-1);draw()}),make('span',(rows.length?page*25+1:0)+'–'+Math.min(page*25+25,rows.length)+' of '+rows.length),button('Next records',()=>{if((page+1)*25<rows.length){w.recordPage++;draw()}}));holder.append(table,pager);replaceStable(ui.output,holder);
 };ui.search.oninput=()=>{w.recordPage=0;draw()};ui.reset.onclick=()=>{ui.search.value='';w.recordPage=0;draw();ui.search.focus()};draw();
}
function renderPanel(tab,data,p){const w=host.workspace();
if(tab==='summary'){renderSummary(data,p)}else if(tab==='failure'){renderFailure(data,p)}else if(tab==='configuration'){p.append(sectionHeading('Captured configuration','evidence.configuration','About captured configuration'));if(!data.configuration?.length)p.append(note('No captured configuration declarations or values available.'));for(const item of data.configuration||[]){p.append(configurationCard(item))}}else if(tab==='settings'){p.append(sectionHeading('Execution settings','evidence.settings','About captured settings'),note(data.settings?.provenance||'Settings unavailable'));const values=data.settings?.values||{};for(const [title,names]of [['Iteration',['max_iterations','max_repeats']],['Recording',Object.keys(values).filter(k=>k.startsWith('record_'))],['Artifact retention',['artifact_policy']],['Failure policy',['retry_policy']]]){const present=Object.fromEntries(names.filter(k=>Object.hasOwn(values,k)).map(k=>[k,values[k]]));if(Object.keys(present).length)p.append(make('h3',title),tree(present))}if(data.settings?.requested!==undefined)p.append(make('h3','Requested overrides'),tree(data.settings.requested));p.append(make('h3','All captured effective settings'),tree(values));p.append(note(data.settings?.gap||'Stored requested/effective values; explicit omissions remain visible.'))}else if(tab==='records')renderRecords(data,p);else if(tab==='artifacts'){renderArtifacts(data,p)}else if(tab==='report'){p.append(sectionHeading('Finalized report','evidence.report','About finalized reports'));if(data.report==null)p.append(note(data.report_availability||'Not finalized'));else{p.append(button('Export report',()=>download('context-'+w.id+'.txt',data.report,'text/plain')),make('pre',data.report))}}else if(tab==='activity'){p.append(sectionHeading('Recorded lifecycle and controls','evidence.activity','About recorded activity'),note('Recorded order only; no inferred global timeline.'),note((data.activity_omitted||0)+' lifecycle entries omitted by the display bound; missing/pruned events cannot be reconstructed.'),make('h3','Retained lifecycle'),activityList(data.activity||[]),make('h3','Observed control requests · separate retained order'),activityList((host.requests?.()||[]).filter(r=>r.context===w.id)))}
}

function embedGraph(viewer){const root=viewer.shadowRoot;if(!root||root.querySelector("[data-workspace-style]"))return;const style=make('style','.top,.theme,.progress-summary{display:none!important}.shell{height:100%;min-height:0}.graph-heading h2{display:none}.graph-heading{padding:6px 10px}.graph-heading .description{display:none}.toolbar{padding:6px 10px}@media(max-width:620px){.shell{min-height:0}.graph-heading{padding:4px 8px}.toolbar{padding:4px 8px;gap:5px}.graph-heading{display:block;max-height:none}.graph-heading>div:first-child{margin:0 0 4px}.tools{flex-wrap:wrap;overflow:visible;max-width:100%;padding-bottom:2px}.tools>*{flex-shrink:0}.tools button{padding:3px 6px}.view-hint{max-height:28px;font-size:11px;padding:3px 8px;overflow:auto}}');style.dataset.workspaceStyle="";root.append(style);if(viewer.motion)viewer.motion.closest('label').hidden=true;const info=root.querySelector('.top button');if(info)root.querySelector('.graph-heading > div:first-child')?.prepend(info);}

return {tabs:['Graph','Summary','Failure','Configuration','Settings','Records','Artifacts','Report','Activity'],duration,localTime,tree,conciseValue,rawDetails,configurationCard,activitySummary,activityList,stateBadge,contextProgress,tabKeys,renderArtifacts,artifactHistoryTable,identityFact,renderSummary,renderFailure,recordChart,renderRecords,renderPanel,embedGraph};
}
globalThis.JayrunRunPanels={create,duration,themeControl};
})();
