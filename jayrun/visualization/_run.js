/* Offline host for the same context panels used by the dashboard.
 * The graph remains a light-DOM child, projected into an isolated workspace.
 * No transport, polling, authority or live control is created here.
 */
(() => {
  if (customElements.get('jayrun-run')) return;
  const CSS = __RUN_STYLE__;
  const copyText = __RUN_COPY__;
  const make = (tag, text, attrs = {}) => {
    const node = document.createElement(tag);
    if (text != null) node.textContent = String(text);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    return node;
  };
  const button = (text, action, attrs = {}) => {
    const node = make('button', text, {type: 'button', ...attrs});
    node.onclick = action;
    return node;
  };
  const note = (text, error = false) => make('p', text, {class: 'notice' + (error ? ' error' : '')});
  function download(name, text, type = 'application/json') {
    const url = URL.createObjectURL(new Blob([text], {type}));
    const link = make('a', null, {href: url, download: name});
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function capturedData(graph, report) {
    const evidence = graph.completed;
    const records = evidence.records.map(record => ({...record,
      numeric: typeof record.value === 'number' && Number.isFinite(record.value)}));
    return {
      context_id: evidence.context_id, session: null,
      intrinsic_graph_id: graph.identity?.['Intrinsic graph ID'],
      finalized: true, graph_available: true, graph_availability: 'Captured declaration and finalized execution evidence.',
      captured_at: Date.parse(evidence.finished_at) / 1000,
      evidence_sampled_at: evidence.finished_at,
      row: {id: evidence.context_id, engine_id: evidence.engine_id,
        graph: evidence.graph_key || 'Local graph', version: evidence.graph_version,
        graph_key: evidence.graph_key, state: evidence.outcome, finalized: true,
        stop_requested: evidence.stop_requested, iteration: evidence.iteration_count,
        max_iterations: evidence.settings?.values?.max_iterations,
        fraction: 1, elapsed_seconds: evidence.elapsed_wall_seconds,
        elapsed_meaning: 'Submission to terminal state; excludes later cleanup'},
      failure: evidence.failure, failed_step: evidence.failed_step,
      completed_evidence: evidence, evidence_coverage: evidence.coverage,
      observation_coverage: evidence.coverage,
      configuration: evidence.configuration || [],
      configuration_omitted: evidence.configuration_omitted || 0,
      configuration_retained: Object.hasOwn(evidence, 'configuration'),
      settings: evidence.settings, report,
      records, record_sequence: evidence.coverage.committed_record_sequence,
      records_complete: evidence.coverage.context_records === 'complete retained history',
      records_omitted: 0, display_complete: false,
      artifacts: evidence.artifacts.map(artifact => ({...artifact, coverage: artifact.history_coverage})),
      activity: evidence.history, activity_omitted: 0,
    };
  }
  class RunWorkspace extends HTMLElement {
    connectedCallback() {
      if (this.shadowRoot) return;
      const graph = this.querySelector('jayrun-graph');
      const envelope = JSON.parse(graph.querySelector('script[type="application/json"]').textContent);
      const data = capturedData(envelope.payload, envelope.display.report);
      graph.style.height = 'max(420px, calc(100dvh - 310px))';
      graph.style.minHeight = '0';
      const root = this.attachShadow({mode: 'open'});
      this.setAttribute('data-theme', envelope.display.theme || 'light');
      const style = make('style', CSS + `
        :host{display:block;background:var(--bg);color:var(--ink)}
        .run-content{padding:16px;max-width:1600px;margin:auto;min-width:0}
        .workspace-head{min-height:0;padding:18px;gap:12px}
        .workspace-actions{align-self:start}.workspace-stack{min-height:440px}
        .run-graph{padding:0}.workspace-body[hidden]{display:none}
        .tabs{overflow-x:auto}.run-theme{display:flex;gap:8px}
        @media(max-width:620px){.run-content{padding:6px}.workspace-head{padding:12px}.workspace-actions{width:auto}}
      `);
      root.append(style);
      const state = {id: data.context_id, data, recordKey: null, recordPage: 0};
      const panels = globalThis.JayrunRunPanels.create({make, button, note, download, copyText,
        workspace: () => state, pins: Object.create(null), chartVisibility: new Map(),
        pausedDisplays: new Map(), serviceEpoch: () => 0,
        sectionHeading: title => make('h2', title),
        replaceStable: (target, source) => target.replaceChildren(source),
        shortFailure: failure => typeof failure === 'string' ? failure : JSON.stringify(failure),
        locationDetails: () => ({engine_id: data.row.engine_id, physical_machine: 'Not captured'})});
      this.panels = panels;
      const main = make('main', null, {class: 'run-content'});
      const header = make('section', null, {class: 'workspace-head visualization-header'});
      const identity = make('div', null, {class: 'workspace-identity visualization-identity'});
      identity.append(make('h1', 'Context ' + data.context_id));
      const metadata = make('div', null, {class: 'visualization-summary'});
      metadata.append(panels.stateBadge(data.row),
        make('p', 'Saved run · ' + data.row.graph + ' · version ' + data.row.version),
        panels.contextProgress(data.row));
      metadata.append(make('small', `${data.completed_evidence.completed_iterations} completed / ${data.completed_evidence.iteration_count} started iterations`));
      const actions = make('div', null, {class: 'workspace-actions run-theme visualization-appearance'});
      const changeTheme = value => {
        this.setAttribute('data-theme', value);
        graph.setAttribute('theme', value);
        for (const control of actions.querySelectorAll('input')) control.checked = control.value === value;
      };
      actions.append(globalThis.JayrunRunPanels.themeControl(envelope.display.theme || 'light', changeTheme));
      header.append(identity, actions, metadata);
      const tabs = make('nav', null, {class: 'tabs', role: 'tablist', 'aria-label': 'Context workspace'});
      tabs.onkeydown = panels.tabKeys;
      const container = make('section', null, {class: 'tab-content workspace-stack'});
      const views = new Map();
      const select = name => {
        state.tab = name;
        for (const [key, view] of views) {view.hidden = key !== name; view.inert = key !== name;}
        for (const control of tabs.children) {
          control.setAttribute('aria-selected', String(control.dataset.tab === name));
          control.tabIndex = control.dataset.tab === name ? 0 : -1;
        }
        let view = views.get(name);
        if (!view) {
          view = make('div', null, {class: 'workspace-body' + (name === 'graph' ? ' run-graph' : ''),
            'data-view': name, role: 'tabpanel', id: 'run-panel-' + name, 'aria-labelledby': 'run-tab-' + name});
          views.set(name, view); container.append(view);
          if (name === 'graph') view.append(make('slot'));
          else panels.renderPanel(name, data, view);
        } else if (name === 'summary') {
          view.replaceChildren(); panels.renderPanel(name, data, view);
        }
      };
      for (const title of panels.tabs) {
        const name = title.toLowerCase();
        tabs.append(button(title, () => select(name), {role: 'tab', 'data-tab': name,
          id: 'run-tab-' + name, 'aria-controls': 'run-panel-' + name}));
      }
      main.append(header, tabs, container); root.append(main);
      select('graph'); changeTheme(envelope.display.theme || 'light');
      panels.embedGraph(graph);
    }
  }
  customElements.define('jayrun-run', RunWorkspace);
})();
