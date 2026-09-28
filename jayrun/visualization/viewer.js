/* Static portable graph viewer. No engine, network, polling, or execution APIs. */
(() => {
  "use strict";
  if (customElements.get("jayrun-graph")) return;
  const CSS = __JAYRUN_STYLE__;
  const sharedHelp = __JAYRUN_HELP__;
  const copyText = __JAYRUN_COPY__;
  const NS = "http://www.w3.org/2000/svg";
  const element = (tag, text, attrs = {}) => {
    const result = document.createElement(tag);
    if (text !== null && text !== undefined) result.textContent = String(text);
    for (const [key, value] of Object.entries(attrs)) result.setAttribute(key, String(value));
    return result;
  };
  const svgElement = (tag, attrs = {}, text = null) => {
    const result = document.createElementNS(NS, tag);
    for (const [key, value] of Object.entries(attrs)) result.setAttribute(key, String(value));
    if (text !== null) result.textContent = String(text);
    return result;
  };
  const short = (text, limit) => {
    const value = String(text);
    let result = "", used = 0;
    for (const char of value) {
      const units = /[MW@%mw]/u.test(char) ? 1.65 : /[ ilI.,:;!|']/u.test(char) ? .55 : char.codePointAt(0) > 0x2e80 ? 2 : /[A-Z]/u.test(char) ? 1.25 : 1;
      if (used + units > limit - 1) return result + "…";
      result += char; used += units;
    }
    return result;
  };
  const symbols = {match: "✓", mismatch: "!", unknown: "?", unchecked: "·"};

  const progressStates = new Set(["pending", "running", "placement_waiting", "completed", "skipped", "failed", "cancelled"]);
  const stateCaptions = {pending: "Pending", running: "Running", placement_waiting: "Awaiting placement", completed: "Completed", skipped: "Skipped", failed: "Failed", cancelled: "Cancelled"};
  const stateSymbols = {pending: "○", running: "●", placement_waiting: "◷", completed: "✓", skipped: "−", failed: "!", cancelled: "×"};
  const finite = value => typeof value === "number" && Number.isFinite(value) && value >= 0;
  const fraction = value => value == null || (finite(value) && value <= 1);
  const seconds = value => globalThis.JayrunRunPanels.duration(value);
  // Preserve the existing duration-estimate meter, not a measured work counter.
  const nodeFraction = progress => {
    if (!progress || progress.state === "skipped") return null;
    if (progress.state === "completed") return 1;
    if (progress.state === "pending" && !progress.steps.some(step => step.elapsed_seconds > 0 || step.state === "completed")) return 0;
    const steps = progress.steps.filter(step => step.state !== "skipped");
    if (!steps.length || steps.some(step => !finite(step.estimated_seconds) || step.estimated_seconds === 0)) return null;
    const total = steps.reduce((sum, step) => sum + step.estimated_seconds, 0);
    const done = steps.reduce((sum, step) => sum + step.estimated_seconds * (step.state === "completed" ? 1 : ["running", "pending", "placement_waiting"].includes(step.state) ? Math.min(.95, step.elapsed_seconds / step.estimated_seconds) : 0), 0);
    return Math.min(.99, done / total);
  };
  const roundedPath = points => {
    let result = `M${points[0].join(",")}`;
    for (let i=1; i<points.length-1; i++) {
      const [a,b,c] = [points[i-1], points[i], points[i+1]];
      const before = Math.hypot(b[0]-a[0],b[1]-a[1]), after = Math.hypot(c[0]-b[0],c[1]-b[1]);
      if (!before || !after) continue;
      const radius = Math.min(6,before/2,after/2);
      const entry = b.map((v,j)=>v+(a[j]-v)*radius/before), exit = b.map((v,j)=>v+(c[j]-v)*radius/after);
      result += ` L${entry.join(",")} Q${b.join(",")} ${exit.join(",")}`;
    }
    return result + ` L${points.at(-1).join(",")}`;
  };
  const checkRequirements = payload => {
    if (payload.kind !== "registry" || payload.requirements === undefined) return;
    const evidence = payload.requirements, ids = new Set((payload.graphs || []).map(g => g.id));
    const texts = (values, limit=50000) => Array.isArray(values) && values.length <= limit && values.every(v => typeof v === "string" && v.length > 0 && v.length <= 8192 && !/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(v));
    const fail = () => { throw new TypeError("Invalid registry requirement evidence or graph references"); };
    if (!evidence || !texts([evidence.source]) || !Array.isArray(evidence.graphs) || evidence.graphs.length !== ids.size || ids.size > 1000 || !texts(evidence.coverage,64)) fail();
    const rows = new Map();
    for (const row of evidence.graphs) {
      if (!row || !ids.has(row.graph_id) || rows.has(row.graph_id) || !["consistent","invalid","unavailable"].includes(row.status) || !texts(row.declarations) || (row.error !== undefined && !texts([row.error]))) fail();
      rows.set(row.graph_id, new Set(row.declarations));
    }
    const combined = evidence.combined;
    if (!combined || !["consistent","conflict","unavailable"].includes(combined.status) || !texts(combined.constraints) || !Array.isArray(combined.conflicts) || combined.conflicts.length > 50000) fail();
    if ((combined.status === "consistent" && combined.conflicts.length) || (combined.status === "conflict" && !combined.conflicts.length) || (combined.status !== "unavailable" && evidence.graphs.some(row=>row.status!=="consistent"))) fail();
    for (const conflict of combined.conflicts) {
      if (!conflict || !texts([conflict.name,conflict.message]) || (conflict.marker != null && !texts([conflict.marker])) || !Array.isArray(conflict.contributors) || !conflict.contributors.length || conflict.contributors.length > 50000) fail();
      for (const item of conflict.contributors) if (!item || !rows.get(item.graph_id)?.has(item.requirement)) fail();
    }
  };
  const normalizeLegacy = value => {
    if (!value || value.schema_version !== 1 || typeof value.graph_id !== "string" || !Array.isArray(value.nodes) || !Array.isArray(value.edges) || !Array.isArray(value.artifacts)) throw new TypeError("Expected Jayrun viewer data with schema_version 1");
    const data = structuredClone(value), ids = new Set(), edgeIds = new Set(), ports = new Map();
    if (!data.bounds || ![data.bounds.x,data.bounds.y,data.bounds.width,data.bounds.height].every(finite) || data.bounds.width <= 0 || data.bounds.height <= 0) throw new TypeError("Invalid graph bounds");
    if (!["validation","dashboard"].includes(data.mode)) throw new TypeError("Invalid presentation mode");
    const artifacts = data.artifacts.map(a => ({...a, id: `artifact-${a.id}`}));
    const nodes = data.nodes.map(n => {
      if (typeof n.id !== "string" || ids.has(n.id) || !["operator","entry","exit"].includes(n.kind) || ![n.x,n.y,n.width,n.height].every(finite) || n.width <= 0 || n.height <= 0 || !Array.isArray(n.inputs) || !Array.isArray(n.outputs)) throw new TypeError("Invalid or duplicate graph node");
      ids.add(n.id);
      const node = {...n, id: `node-${n.id}`, details: n.inspection || {Structure: n.details || ""}, resources: n.resources || [], identity: n.identity || {"Validation node": n.id, "Layout position": n.layout_position}, label_lines: n.label_lines || [short(n.label, n.kind === "operator" ? 26 : 15)], description_lines: n.description_lines || [], port_top: n.port_top ?? n.height/2};
      // Keep boundary metadata in the same namespace as palette/port/edge IDs.
      // A numeric zero is a supplied identity, not missing metadata.
      if (node.artifact_id != null) node.artifact_id = `artifact-${node.artifact_id}`;
      for (const side of ["inputs","outputs"]) node[side] = n[side].map((p,i) => {
        if (![p.x,p.y].every(finite)) throw new TypeError("Invalid graph port");
        const port = {...p, id: p.id || `${node.id}/${side}/${i}`, artifact_id: p.artifact_id == null ? null : `artifact-${p.artifact_id}`};
        if (p.edge_id != null) ports.set(JSON.stringify([n.id,side,p.edge_id]),port.id);
        return port;
      });
      return node;
    });
    const edges = data.edges.map(e => {
      if (typeof e.id !== "string" || edgeIds.has(e.id) || !ids.has(e.source) || !ids.has(e.target) || !Array.isArray(e.points) || e.points.length < 2 || !e.points.every(p => Array.isArray(p) && p.length === 2 && p.every(finite))) throw new TypeError("Invalid graph edge");
      edgeIds.add(e.id);
      const sourcePort = e.source_port_id || ports.get(JSON.stringify([e.source,"outputs",e.id]));
      const targetPort = e.target_port_id || ports.get(JSON.stringify([e.target,"inputs",e.id]));
      const source = nodes.find(n=>n.id === `node-${e.source}`)?.outputs.find(p=>p.id === sourcePort);
      const target = nodes.find(n=>n.id === `node-${e.target}`)?.inputs.find(p=>p.id === targetPort);
      if (!source || !target || source.artifact_id !== `artifact-${e.artifact_id}` || target.artifact_id !== source.artifact_id) throw new TypeError("Invalid graph edge port");
      return {...e, id: `edge-${e.id}`, artifact_id: `artifact-${e.artifact_id}`, source: {node: `node-${e.source}`, port: sourcePort}, target: {node: `node-${e.target}`, port: targetPort}, status: ["match","mismatch","unknown"].includes(e.validation) ? e.validation : "unchecked", details: e.inspection || {Structure: e.details || ""}, label_position: e.label_position || [(e.points[0][0]+e.points.at(-1)[0])/2,e.points.at(-1)[1]-10]};
    });
    const findings = data.findings || edges.filter(e=>["mismatch","unknown"].includes(e.status)).map(e=>({id:`finding-${e.id}`,subject:e.id,severity:e.status === "mismatch" ? "error" : "info",message:`${e.label}: ${e.status}. See this connection's contract details.`}));
    return {schema_version: "jayrun.viewer/1", kind:"graph", id:data.graph_id, graph_id:data.graph_id, label:data.label || "Graph definition", description:data.description || "", nodes, edges, artifacts, bounds:data.bounds, reiterations:data.reiterations || [], reiteration:data.reiteration || {eligibility:"unknown",reason:"Legacy data does not supply re-iteration eligibility."}, findings, identity:data.identity || {"Graph version":data.graph_version}, details:data.details || {}};
  };

  class GraphView extends HTMLElement {
    static get observedAttributes() { return ["theme"]; }
    attributeChangedCallback(name, oldValue, value) {
      if (name === "theme" && oldValue !== value && ["light", "dark"].includes(value)) {
        for (const radio of this.themeRadios || []) radio.checked = radio.value === value;
        this.dispatchEvent(new CustomEvent('jayrun-theme', {detail: {theme: value}, bubbles: true, composed: true}));
      }
    }
    set graph(value) {
      // Validate before replacing an existing instance. Legacy build() and
      // viewer_script()/element.graph embedding remain an established API.
      normalizeLegacy(value);
      checkRequirements(value);
      const source = element("script", JSON.stringify({payload: structuredClone(value), display: {theme: this.getAttribute("theme") || "light", motion: true}}), {type: "application/json"});
      this.disconnectedCallback();
      this.replaceChildren(source);
      if (this.isConnected) this.connectedCallback();
    }
    get graph() {
      if (this._legacyData) return structuredClone(this._legacyData);
      if (this._graph) return structuredClone(this._graph);
      // Setting graph before insertion, or temporarily detaching a host, must
      // not discard its caller-supplied legacy snapshot.
      const source = this.querySelector('script[type="application/json"]');
      if (!source) return null;
      const data = JSON.parse(source.textContent);
      const payload = data.payload || data;
      return payload.schema_version === 1 ? structuredClone(payload) : null;
    }

    connectedCallback() {
      if (this.events && !this.events.signal.aborted) return;
      const source = this.querySelector('script[type="application/json"]');
      if (!source || !source.textContent.trim()) {
        if (!this.payloadObserver) {
          this.payloadObserver = new MutationObserver(() => this.connectedCallback());
          this.payloadObserver.observe(this, {childList: true, subtree: true, characterData: true});
        }
        return;
      }
      this.payloadObserver?.disconnect();
      this.payloadObserver = null;
      this.root = this.shadowRoot || this.attachShadow({mode: "open"});
      this.root.replaceChildren();
      this.events = new AbortController();
      this.listen = (target, event, fn) => target.addEventListener(event, fn, {signal: this.events.signal});
      const style = element("style", CSS);
      if (this.getAttribute("nonce")) style.nonce = this.getAttribute("nonce");
      this.root.append(style);
      let envelope;
      try {
        envelope = JSON.parse(this.querySelector('script[type="application/json"]').textContent);
        if (!envelope.payload && envelope.schema_version === 1) envelope = {payload: envelope, display: {theme: this.getAttribute("theme") || "light", motion: true}};
        this._legacyData = envelope.payload.schema_version === 1 ? structuredClone(envelope.payload) : null;
        if (this._legacyData) envelope.payload = normalizeLegacy(this._legacyData);
        if (envelope.payload.schema_version !== "jayrun.viewer/1") throw new Error("Unsupported viewer schema");
        checkRequirements(envelope.payload);
      } catch (error) {
        this.root.append(element("p", "Unable to load graph: " + error.message, {role: "alert"}));
        return;
      }
      this.payload = envelope.payload;
      this._help = sharedHelp.mount(this.root, [], ["graph.navigation", "graph.identity", "graph.search", "graph.selection", "graph.snapshot", "registry.snapshot", "graph.reiteration", "graph.requirements", "step.identity", "graph.captured", "progress.fraction", "progress.elapsed", "evidence.retained", "evidence.history", "action.copy", "action.export-graph", "view.theme", "view.motion"]);
      const display = {theme: "light", motion: true, ...(envelope.display || {})};
      if (this.hasAttribute("theme")) display.theme = this.getAttribute("theme");
      this.setAttribute("theme", display.theme);
      this.shell = element("div", null, {class: "shell"});
      this.root.append(this.shell);
      const chrome = element("div", null, {class: "chrome"});
      this.shell.append(chrome);
      const top = element("header", null, {class: "top visualization-header"});
      const titleRow = element("div", null, {class: "title-row"});
      this.graphInfoButton = element("button", "Graph info", {type: "button", "aria-expanded": "false", "aria-controls": "graph-info", "data-help": "graph.snapshot"});
      this.graphInfoView = "definition";
      this.listen(this.graphInfoButton, "click", () => {
        const open = this.graphInfoView !== "definition" || this.graphInfo.hidden || this.graphInfo.inert;
        this.graphInfoView = "definition";
        if (open) this.inspectGraph(true);
        this._openGraphInfo(open, true);
      });
      titleRow.append(element("h1", this.payload.label), this.graphInfoButton);
      if (this.payload.kind === "registry") {
        this.requirementsButton = element("button", "Requirements", {type: "button", "aria-expanded": "false", "aria-controls": "graph-info", "data-help": "graph.requirements"});
        this.listen(this.requirementsButton, "click", () => {
          const open = this.graphInfoView !== "requirements" || this.graphInfo.hidden || this.graphInfo.inert;
          this.graphInfoView = "requirements";
          if (open) this.inspectGraph(true);
          this._openGraphInfo(open, true);
        });
        titleRow.append(this.requirementsButton);
      }
      const identity = element("div", null, {class: "visualization-identity"});
      identity.append(element("div", "JAYRUN / GRAPH EXPLORER", {class: "brand"}), titleRow);
      top.append(identity);
      this.subtitle = element("div", this.payload.kind === "registry" ? "Offline registry snapshot · every included graph remains selectable · show or save again to refresh" : "Definition snapshot · declared structure and bindings, not execution evidence", {class: "subtitle"});
      identity.append(this.subtitle);
      chrome.append(top);
      this.toolbar = element("div", null, {class: "toolbar", role: "toolbar", "aria-label": "Graph presentation"});
      chrome.append(this.toolbar);
      this.graphs = this.payload.kind === "registry" ? this.payload.graphs : [this.payload];
      if (this.payload.kind === "registry") {
        const label = element("label", "Registered graph", {class: "registry-label"});
        this.registrySelect = element("select", null, {"aria-label": "Registered graph", "data-help": "registry.snapshot"});
        for (const graph of this.graphs) this.registrySelect.append(element("option", graph.label, {value: graph.id}));
        if (!this.graphs.length) {
          this.registrySelect.append(element("option", "No registered graphs", {value: ""}));
          this.registrySelect.disabled = true;
        }
        label.append(this.registrySelect);
        this.toolbar.append(label);
        this.listen(this.registrySelect, "change", () => this.switchGraph(this.registrySelect.value));
      }
      if (this.payload.completed) {
        const label = element("label", "Iteration");
        this.iterationSelect = element("select", null, {"aria-label": "Completed iteration"});
        const count = this.payload.completed.iteration_count;
        for (let i = count ? 1 : 0; i <= count; i++) this.iterationSelect.append(element("option", count ? String(i) : "No iteration started", {value: String(i)}));
        this.iterationSelect.value = String(count);
        label.append(this.iterationSelect); this.toolbar.append(label);
        this.toolbar.append(element("small", "Bars compare active session durations, not progress or a timeline.", {class: "duration-key"}));
        this.listen(this.iterationSelect, "change", () => { this.refreshCompleted(); this.refreshInspector(); });
      }
      const searchWrap = element("div", null, {class: "search-wrap"});
      this.search = element("input", null, {type: "search", placeholder: "Search names or identities…", "aria-label": "Search names or identities"});
      this.searchResults = element("div", null, {class: "results", "aria-label": "Search results"});
      searchWrap.append(this.search);
      this.toolbar.append(searchWrap);
      this.listen(this.search, "input", () => this.searchEntities());
      this.listen(this.search, "keydown", event => {
        if (event.key === "Enter") { event.preventDefault(); this.searchResults.querySelector("button")?.click(); }
        if (event.key === "ArrowDown") { event.preventDefault(); this.searchResults.querySelector("button")?.focus(); }
      });
      this.listen(this.searchResults, "keydown", event => {
        const buttons = [...this.searchResults.querySelectorAll("button")], index = buttons.indexOf(event.target);
        if (index < 0 || !["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length-1 : index+(event.key === "ArrowDown" ? 1 : -1);
        if (next < 0) this.search.focus({preventScroll:true});
        else buttons[Math.min(next,buttons.length-1)]?.focus();
      });
      const themeGroup = globalThis.JayrunRunPanels.themeControl(display.theme, value => this.setAttribute("theme", value));
      this.themeRadios = [...themeGroup.querySelectorAll('input')];
      const appearance = element("div", null, {class: "visualization-appearance"});
      appearance.append(themeGroup);
      top.append(appearance);
      this.search.dataset.help = "graph.search";
      this.mode = this._legacyData?.mode || "validation";
      if (this._legacyData) {
        const label = element("label", "View");
        this.modeSelect = element("select", null, {"aria-label": "Presentation"});
        for (const value of ["validation", "dashboard"]) this.modeSelect.append(element("option", value === "validation" ? "Validation" : "Progress", {value}));
        this.modeSelect.value = this.mode;
        label.append(this.modeSelect); this.toolbar.append(label);
        this.listen(this.modeSelect, "change", () => this.setMode(this.modeSelect.value));
      }
      const check = (labelText, name) => {
        const label = element("label", null, {class: "check"});
        const input = element("input", null, {type: "checkbox", "aria-label": name});
        const text = element("span", labelText);
        label.append(input, text);
        this.toolbar.append(label);
        return [input, text, label];
      };
      [this.reiteration, this.reiterationText, this.reiterationLabel] = check("Re-iteration", "Re-iteration");
      this.reiteration.dataset.help = "graph.reiteration";
      this.listen(this.reiteration, "change", () => {
        this.shell.classList.toggle("show-reiteration", this.reiteration.checked);
        this.highlight();
        this.announce(this.reiteration.checked ? "Showing structural next-iteration mappings. No execution requested." : "Re-iteration hidden. Ordinary dependencies unchanged.");
      });
      [this.motion, this.motionText] = check("Motion", "Motion");
      this.motion.dataset.help = "view.motion";
      this.motion.checked = display.motion;
      this.reduced = matchMedia("(prefers-reduced-motion: reduce)");
      const updateMotion = () => {
        this.motion.disabled = this.reduced.matches;
        this.motionText.textContent = this.reduced.matches ? "Reduced motion" : "Motion";
        this.shell.classList.toggle("motion", this.motion.checked && !this.reduced.matches && !document.hidden);
        this._updateDisabledReasons();
      };
      this.listen(this.motion, "change", updateMotion);
      this.listen(this.reduced, "change", updateMotion);
      this.listen(document, "visibilitychange", updateMotion);
      updateMotion();
      this.progressSummary = element("section", null, {class: "progress-summary", "aria-label": "Execution progress", hidden: ""});
      chrome.append(this.progressSummary);
      const work = this.work = element("main", null, {class: "work"});
      // Results overlay the work area. Header overflow must never clip them.
      work.append(this.searchResults);
      const canvas = this.canvas = element("section", null, {class: "canvas-panel", "aria-label": "Graph"});
      const heading = element("div", null, {class: "graph-heading"});
      const headingText = element("div");
      this.graphTitle = element("h2");
      this.counts = element("div", null, {class: "count"});
      headingText.append(this.graphTitle);
      const tools = element("div", null, {class: "tools"});
      const button = (label, action, title = label) => {
        const item = element("button", label, {type: "button", "aria-label": title, "data-help": "graph.navigation"});
        this.listen(item, "click", action);
        tools.append(item);
        return item;
      };
      button("−", () => this.zoom(this.scale / 1.2), "Zoom out");
      button("+", () => this.zoom(this.scale * 1.2), "Zoom in");
      button("Fit", () => this.fit(), "Fit graph");
      this.focusButton = button("Focus", () => this.focusSelected(), "Focus selection");
      this.focusButton.disabled = true;
      this.focusButton.title = "Select a component to center it";
      this._updateDisabledReasons();
      this.detailsButton = button("Details", () => this.openInspector(this.inspector.hidden || this.inspector.inert, true), "Toggle component details");
      this.detailsButton.setAttribute("aria-expanded", "false");
      this.detailsButton.setAttribute("aria-controls", "component-details");
      this.detailsButton.disabled = true;
      this.issueNext = button("Issues", () => {
        const open = this.graphInfoView !== "issues" || this.graphInfo.hidden || this.graphInfo.inert;
        this.graphInfoView = "issues";
        if (open) this.inspectGraph(true);
        this._openGraphInfo(open, true);
      }, "Graph issues");
      this.issueNext.setAttribute("aria-controls", "graph-info");
      this.detailsButton.dataset.help = this.focusButton.dataset.help = "graph.selection";
      this.issueCount = element("span", "0 issues", {class: "count"});
      tools.append(this.issueCount);
      heading.append(headingText, tools);
      this.viewport = element("div", null, {class: "viewport", tabindex: "0", role: "region", "aria-label": "Graph viewport. Scroll to pan; use Fit and zoom controls."});
      this.viewHint = element("div", null, {class: "view-hint muted", hidden: ""});
      canvas.append(this.viewHint, this.viewport);
      this.graphInfo = element("aside", null, {id: "graph-info", class: "graph-info detail-panel", "aria-label": "Graph information", hidden: ""});
      this.inspector = element("aside", null, {id: "component-details", class: "inspector detail-panel", "aria-label": "Component details", hidden: ""});
      this.panelLayout = element("div", null, {class: "panel-layout"});
      this.panelLayout.append(this.graphInfo, canvas, this.inspector);
      this.listen(this.panelLayout, "click", event => {
        // The visible graph gutter remains a dismiss target while a narrow
        // drawer makes the covered graph inert to keyboard and pointer input.
        if (this.canvas.inert && event.target === this.panelLayout) this._resetSelection();
      });
      work.append(heading, this.panelLayout);
      this.shell.append(work);
      const footer = element("footer", null, {class: "footer"});
      const legend = element("div", null, {class: "legend", "aria-label": "Connection legend"});
      for (const label of ["✓ Match", "! Mismatch", "? Unknown", "· Unchecked", "▣ Resource binding"]) legend.append(element("span", label));
      const dataExport = element("button", "Export graph data", {type: "button", "data-help": "action.export-graph"});
      this.listen(dataExport, "click", () => this.exportData());
      this.artifactLegend = element("div", null, {class: "artifact-legend", role: "region", tabindex: "0", "aria-label": "Artifacts"});
      const legendRow = element("div", null, {class: "legend-row", tabindex: "0", role: "region", "aria-label": "Connection key and data export"});
      legendRow.append(legend, dataExport);
      this._disabledReasons = element("div", "Select a component for Focus / Details.", {class:"disabled-reasons"});
      footer.append(this.artifactLegend, legendRow, this._disabledReasons);
      this.shell.append(footer);
      this.status = element("div", null, {class: "live-status", role: "status", "aria-live": "polite"});
      this.shell.append(this.status);
      const transient = target => {
        const view = target?.closest?.("[data-id]");
        return view?.getRootNode() === this.root ? view.getAttribute("data-id") : null;
      };
      this.listen(this.root, "pointerover", event => { this.hoverId = this.drag?.moved ? null : transient(event.target); this.highlight(); });
      this.listen(this.root, "pointerout", event => { this.hoverId = this.drag?.moved ? null : transient(event.relatedTarget); this.highlight(); });
      this.listen(this.root, "focusin", event => {
        // Keyboard focus takes over even if the pointer has not moved away.
        this.hoverId = null; this.focusId = transient(event.target); this.highlight();
      });
      this.listen(this.root, "focusout", event => { this.focusId = transient(event.relatedTarget); this.highlight(); });
      // Preserve the original viewer's drag-pan and cursor-anchored wheel zoom.
      // Geometry remains fixed; only the scrollable presentation changes.
      this.listen(this.panelLayout, "pointerdown", event => {
        if (event.button !== 0 || event.target.closest(".detail-panel")) return;
        this.suppressClick = false;
        this.drag = {id:event.pointerId, x:event.clientX, y:event.clientY,
          left:this.viewport.scrollLeft, top:this.viewport.scrollTop, moved:false,
          capture:this.canvas.inert ? this.panelLayout : this.viewport};
      });
      this.listen(this.root, "pointermove", event => {
        if (!this.drag || this.drag.id !== event.pointerId) return;
        const dx=event.clientX-this.drag.x, dy=event.clientY-this.drag.y;
        if (!this.drag.moved && Math.hypot(dx,dy)<4) return;
        this.drag.moved=true;
        this.drag.capture.setPointerCapture(event.pointerId);
        this.viewport.classList.add("dragging");
        this.autoFit=false;
        this.viewport.scrollTo(this.drag.left-dx,this.drag.top-dy);
        this.hoverId=null; this.highlight();
      });
      const finishDrag = event => {
        if (!this.drag || this.drag.id !== event.pointerId) return;
        this.suppressClick=this.drag.moved && event.type !== "pointercancel";
        this.drag=null;
        this.viewport.classList.remove("dragging");
      };
      for (const event of ["pointerup","pointercancel","lostpointercapture"]) this.listen(this.panelLayout,event,finishDrag);
      // Capture the pan gesture's click before nested selectable targets handle
      // it. A new pointer gesture or keyboard activation is never swallowed.
      this.panelLayout.addEventListener("click", event => {
        if (this.suppressClick && event.detail !== 0) {
          this.suppressClick=false; event.preventDefault(); event.stopPropagation(); return;
        }
        if (this.viewport.contains(event.target) && !transient(event.target)) this._resetSelection();
      }, {signal:this.events.signal, capture:true});
      this.panelLayout.addEventListener("wheel",event=>{
        if (!this.svg || event.target.closest(".detail-panel")) return;
        event.preventDefault();
        const box=this.viewport.getBoundingClientRect(), x=event.clientX-box.left, y=event.clientY-box.top;
        const wx=(this.viewport.scrollLeft+x)/this.scale;
        const wy=(this.viewport.scrollTop+y-(parseFloat(this.svg.style.marginTop)||0))/this.scale;
        this.zoom(this.scale*Math.exp(-event.deltaY*.0015));
        this.viewport.scrollTo(wx*this.scale-x,wy*this.scale+(parseFloat(this.svg.style.marginTop)||0)-y);
      },{signal:this.events.signal,passive:false});
      this.listen(this.root, "keydown", event => {
        if (event.key === "Escape") {
          event.preventDefault(); event.stopPropagation();
          if ((event.target === this.search || this.searchResults.contains(event.target)) && this.search.value) {
            this.search.value = ""; this.searchEntities(); this.search.focus({preventScroll:true});
          }
          else if (this.graphInfo.contains(event.target) || (!this.selected && !this.graphInfo.hidden)) this._openGraphInfo(false, true);
          else this._resetSelection();
        }
      });
      this.listen(this.viewport, "keydown", event => {
        if (event.target !== this.viewport) return;
        if (event.key === "+" || event.key === "=") { this.zoom(this.scale * 1.2); event.preventDefault(); }
        if (event.key === "-") { this.zoom(this.scale / 1.2); event.preventDefault(); }
        if (event.key.toLowerCase() === "f") { this.fit(); event.preventDefault(); }
      });
      this.switchGraph(this.payload.kind === "registry" ? this.payload.selected_graph : this.payload.id);
      if (this._legacyData?.progress) this.updateProgress(this._legacyData.progress);
      this.refreshProgress();
      if (display.reiteration && !this.reiteration.disabled) {
        this.reiteration.checked = true;
        this.shell.classList.add("show-reiteration");
      }
      if (display.selection) {
        if (this.entities.has(display.selection)) this.select(display.selection);
        else this.announce("The requested selection is not present in this graph.");
      }
      this.resize = new ResizeObserver(() => {
        // A hidden workspace is retained, not a zero-size camera resize.
        if (!this.work.clientWidth || !this.viewport.clientHeight) return;
        this._updateDrawers();
        if (this.autoFit && this._graph) this.fit();
      });
      this.resize.observe(this.work);
      this.resize.observe(this.viewport);
    }
    disconnectedCallback() {
      if (this._legacyData) {
        const source = this.querySelector('script[type="application/json"]');
        if (source) source.textContent = JSON.stringify({payload: this._legacyData, display: {
          theme: this.getAttribute("theme") || "light", motion: this.motion?.checked ?? true,
          selection: this.selected, reiteration: this.reiteration?.checked || false
        }});
      }
      this._help?.dispose(); this._help = null;
      this.payloadObserver?.disconnect();
      this.payloadObserver = null;
      this.resize?.disconnect();
      this.events?.abort();
      this.graphEvents?.abort();
      this.inspectorEvents?.abort();
      this.graphInfoEvents?.abort();
      this.searchEvents?.abort();
      this.entities?.clear();
      this.views?.clear();
      this.progressNodes?.clear();
      this._progress = null;
      this._liveOrder = null;
      this._legacyData = null;
      this.hoverId = this.focusId = this.drag = null;
      this.suppressClick = false;
      this.graphs = null;
      this._graph = null;
      this.payload = null;
    }
    announce(message) { this.status.textContent = message; }
    switchGraph(id) {
      this._help?.dismiss();
      this.graphEvents?.abort();
      this.graphEvents = new AbortController();
      this.inspectorEvents?.abort();
      this.searchEvents?.abort();
      this.entities = new Map();
      this.views = new Map();
      this.selected = null;
      this.hoverId = this.focusId = null;
      this._progress = null;
      if (!this._legacyData) this.mode = "validation";
      this.progressNodes = new Map();
      this.artifactLegend.replaceChildren();
      this.issueIndex = -1;
      this.search.value = "";
      this.searchResults.replaceChildren();
      this.reiteration.checked = false;
      this.shell.classList.remove("show-reiteration");
      this.viewport.replaceChildren();
      this.inspector.replaceChildren();
      this.openInspector(false);
      this.detailsButton.disabled = true;
      this.focusButton.disabled = true;
      this.focusButton.title = "Select a component to center it";
      this._updateDisabledReasons();
      this.viewport.scrollTo(0, 0);
      this.viewHint.hidden = true;
      this._graph = this.graphs.find(graph => graph.id === id) || null;
      this.svg = null;
      this.scale = 1;
      this.autoFit = true;
      if (!this._graph) {
        this.graphTitle.textContent = this.graphs.length ? "Invalid graph selection" : "Empty registry";
        this.counts.textContent = "0 operator occurrences";
        this.viewport.append(element("div", this.graphs.length ? "That graph is not included in this snapshot." : "No graphs were registered when this snapshot was captured.", {class: "empty"}));
        this.reiteration.disabled = true;
        this.reiterationText.textContent = "Re-iteration (0)";
        this.issueNext.disabled = true;
        this.issueCount.textContent = "0 issues";
        this.inspectGraph();
        this.refreshProgress();
        return;
      }
      const graph = this._graph;
      if (this.registrySelect) this.registrySelect.value = graph.id;
      this.graphTitle.textContent = graph.label;
      this.counts.textContent = `${graph.nodes.filter(n => n.kind === "operator").length} operator occurrences · ${graph.edges.length} connections · ${graph.nodes.reduce((sum, n) => sum + (n.resources || []).length, 0)} resource markers`;
      this.reiteration.disabled = !graph.reiterations.length;
      this.reiterationText.textContent = `Re-iteration (${graph.reiterations.length})`;
      this.reiterationLabel.title = graph.reiterations.length ? "Show eligible next-iteration mappings; presentation only" : graph.reiteration.reason || "No eligible mappings supplied";
      this.issueNext.disabled = !graph.findings.length;
      this.issueCount.textContent = `${graph.findings.length} ${graph.findings.length === 1 ? "issue" : "issues"}`;
      this.palette = new Map(graph.artifacts.map(a => [a.id, a]));
      this.svg = svgElement("svg", {viewBox: `0 0 ${graph.bounds.width} ${graph.bounds.height}`, width: graph.bounds.width, height: graph.bounds.height, role: "graphics-document", "aria-label": graph.label});
      this.viewport.append(this.svg);
      for (const edge of graph.edges) this.drawEdge(edge, false);
      for (const edge of graph.reiterations) this.drawEdge(edge, true);
      for (const node of graph.nodes) this.drawNode(node);
      if (!graph.nodes.length) this.viewport.append(element("div", "This graph has no operators.", {class: "empty"}));
      this.drawArtifactLegend();
      this.inspectGraph();
      this.refreshProgress();
      this.fit();
      // Initial views keep card text readable. A user can still explicitly Fit
      // to an overview at any scale; the scrollable detail view changes neither
      // topology nor layout. Do not keep re-fitting it during ordinary resize.
      if (this.scale < .6 || (this.viewport.clientWidth < 600 && this.scale < .8)) {
        this.zoom(1);
        const first = graph.nodes.find(node => node.kind === "operator") || graph.nodes[0];
        if (first) this.viewport.scrollTo(Math.max(0, first.x - 24), Math.max(0, first.y - 32));
        this.viewHint.textContent = "Scrollable detail view · Fit shows the whole graph; search or Focus reveals a selection.";
        this.viewHint.hidden = false;
      }
      this.announce("Selected " + graph.label + ". Selection and overlays cleared.");
    }
    selectable(view, data, kind) {
      const id = data.id;
      this.entities.set(id, {data, kind});
      this.views.set(id, view);
      view.setAttribute("data-id", id);
      view.setAttribute("tabindex", "0");
      view.setAttribute("role", "button");
      view.setAttribute("aria-label", `${data.label || id} · ${kind}${data.status ? " · " + data.status : ""}`);
      const select = event => { event.stopPropagation(); this.select(id); };
      view.addEventListener("click", select, {signal: this.graphEvents.signal});
      view.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(event); }
      }, {signal: this.graphEvents.signal});
    }
    drawEdge(edge, iteration) {
      const artifact = this.palette.get(edge.artifact_id);
      const group = svgElement("g", {class: "edge" + (iteration ? " reiteration" : ""), "data-status": edge.status});
      const d = roundedPath(edge.points);
      group.append(svgElement("title", {}, `${edge.label || artifact.label} · ${iteration ? "structural re-iteration" : edge.status}`));
      group.append(svgElement("path", {class: "hit", d}));
      group.append(svgElement("path", {class: "artifact-stroke", d, stroke: artifact.color}));
      const p = edge.points[edge.points.length - 1];
      group.append(svgElement("path", {class: "artifact-arrow", d: `M${p[0]},${p[1]} L${p[0]-10},${p[1]-5} L${p[0]-10},${p[1]+5} Z`, fill: artifact.color, stroke: artifact.color}));
      const [x, y] = edge.label_position;
      const destination = this._graph.nodes.find(node => node.id === edge.target.node)?.inputs.find(port => port.id === edge.target.port)?.label || edge.target.port;
      const segment = edge.segment?.count > 1 ? ` · ${edge.segment.index}/${edge.segment.count}` : "";
      const label = iteration ? `${short(artifact.label, 18)} → ${short(destination, 18)} · n → n+1` : `${symbols[edge.status]} ${short(artifact.label, segment ? 9 : 13)}${segment}`;
      const width = Math.max(28, label.length * 6.8 + 14);
      group.append(svgElement("rect", {class: "edge-label-bg", x: x-width/2, y: y-14, width, height: 21, rx: 5}));
      group.append(svgElement("text", {class: "edge-label" + (edge.status === "mismatch" ? " mismatch-cue" : ""), x, y, "text-anchor": "middle"}, label));
      this.selectable(group, edge, iteration ? "Re-iteration mapping" : "Artifact connection");
      this.svg.append(group);
    }
    drawNode(node) {
      const group = svgElement("g", {class: "node", "data-kind": node.kind, transform: `translate(${node.x},${node.y})`});
      if (node.kind !== "operator") {
        const artifact = this.palette.get([...node.inputs,...node.outputs][0]?.artifact_id);
        if (artifact) group.style.setProperty("--boundary", artifact.color);
      }
      const boundaryArtifact = node.kind === "operator" ? null :
        (node.artifact_id ?? [...node.inputs,...node.outputs].find(port => port.artifact_id != null)?.artifact_id);
      const identityHint = boundaryArtifact == null ? "" : ` · Artifact identity: ${boundaryArtifact} · Node identity: ${node.id}`;
      group.append(svgElement("title", {}, node.label + identityHint + (node.description ? " — " + node.description : "")));
      group.append(svgElement("rect", {class: "card", width: node.width, height: node.height, rx: node.kind === "operator" ? 12 : 22}));
      group.append(svgElement("text", {class: "type", x: node.kind === "operator" ? 17 : 12, y: node.kind === "operator" ? 24 : 16}, node.kind === "operator" ? "OPERATOR" : node.kind.toUpperCase()));
      node.label_lines.forEach((line, i) => group.append(svgElement("text", {class: "name", x: node.kind === "operator" ? 17 : 12, y: (node.kind === "operator" ? 48 : 34) + i*18}, line)));
      node.description_lines.forEach((line, i) => group.append(svgElement("text", {class: "description", x: 17, y: 52 + node.label_lines.length*20 + i*16}, line)));
      if (node.kind === "operator") group.append(svgElement("line", {class: "divider", x1: 16, x2: node.width-16, y1: node.port_top-19, y2: node.port_top-19}));
      this.selectable(group, node, node.kind === "operator" ? "Operator occurrence" : node.kind + " boundary");
      if (identityHint) group.setAttribute("aria-label", `${node.label} · ${node.kind} boundary${identityHint}`);
      for (const side of ["inputs", "outputs"]) {
        for (const port of node[side]) {
          const input = side === "inputs";
          const x = port.x-node.x, y = port.y-node.y;
          const pg = svgElement("g", {class: "port"});
          const portHint = `${port.label} · ${this.palette.get(port.artifact_id)?.label || "unbound"} · Artifact identity: ${port.artifact_id ?? "unbound"} · Port identity: ${port.id}`;
          pg.append(svgElement("title", {}, portHint));
          pg.append(svgElement("circle", {cx: x, cy: y, r: 5, fill: this.palette.get(port.artifact_id)?.color || "var(--muted)"}));
          if (node.kind === "operator") pg.append(svgElement("text", {x: input ? 13 : node.width-13, y: y+4, "text-anchor": input ? "start" : "end"}, short(port.label, node.kind === "operator" ? 16 : 13)));
          this.selectable(pg, port, input ? "Input port" : "Output port");
          pg.setAttribute("aria-label", portHint);
          this.entities.get(port.id).owner = node.id;
          group.append(pg);
        }
      }
      for (const marker of node.resources || []) {
        const rg = svgElement("g", {class: "resource", "data-state": marker.state, transform: `translate(12,${marker.y})`});
        rg.append(svgElement("title", {}, marker.label + " · " + marker.state));
        rg.append(svgElement("rect", {width: node.width-24, height: marker.height, rx: 6}));
        marker.label_lines.forEach((line, i) => rg.append(svgElement("text", {x: 10, y: 19 + i*16}, (i === 0 ? "▣ " : "") + line)));
        this.selectable(rg, marker, "Resource binding");
        this.entities.get(marker.id).owner = node.id;
        group.append(rg);
      }
      if (node.kind === "operator") {
        const meter = svgElement("g", {class: "progress", transform: `translate(14,${node.progress_y ?? node.height-24})`, role: "progressbar", "aria-label": `${node.label} step-session progress`, "aria-valuemin": 0, "aria-valuemax": 100});
        meter.append(svgElement("text", {class: "progress-state", x: 0, y: 0}), svgElement("rect", {class: "progress-track", x: 0, y: 8, width: node.width-70, height: 4, rx: 2}), svgElement("rect", {class: "progress-fill", x: 0, y: 8, width: 0, height: 4, rx: 2}), svgElement("text", {class: "progress-value", x: node.width-28, y: 13, "text-anchor": "end"}));
        group.append(meter);
      }
      this.svg.append(group);
    }
    _updateDrawers() {
      if (!this.panelLayout) return;
      const narrow = this.work.clientWidth < 1050;
      this.work.classList.toggle("narrow", narrow);
      const panels = [this.graphInfo, this.inspector];
      const open = panels.filter(panel => !panel.hidden);
      const active = open.includes(this.activePanel) ? this.activePanel : open.at(-1);
      this.activePanel = active;
      this.canvas.inert = narrow && open.length > 0;
      for (const panel of panels) {
        // Narrow drawers are non-modal. The other open panel keeps its state,
        // but never leaves covered controls in the keyboard/accessibility tree.
        const covered = narrow && !panel.hidden && panel !== active;
        panel.classList.toggle("covered", covered);
        panel.inert = panel.hidden || covered;
        panel.setAttribute("aria-hidden", String(panel.inert));
      }
      this.graphInfoButton.setAttribute("aria-expanded", String(this.graphInfoView === "definition" && !this.graphInfo.hidden && !this.graphInfo.inert));
      this.issueNext.setAttribute("aria-expanded", String(this.graphInfoView === "issues" && !this.graphInfo.hidden && !this.graphInfo.inert));
      this.requirementsButton?.setAttribute("aria-expanded", String(this.graphInfoView === "requirements" && !this.graphInfo.hidden && !this.graphInfo.inert));
      this.detailsButton.setAttribute("aria-expanded", String(!this.inspector.hidden && !this.inspector.inert));
      const focused = this.root.activeElement;
      if (panels.some(panel => panel.inert && panel.contains(focused))) active?.querySelector("button")?.focus({preventScroll: true});
    }
    _setPanel(panel, open, focus = false) {
      // Visibility/focus only: canvas dimensions, fit ownership and camera state
      // are untouched. Absolute positioning handles both wide and narrow panels.
      panel.hidden = !open;
      if (open) this.activePanel = panel;
      this._updateDrawers();
      if (focus && open) panel.querySelector("button")?.focus({preventScroll: true});
    }
    _openGraphInfo(open, focus = false) {
      if (open && this.graphInfo.hidden) this.inspectGraph(true);
      this._setPanel(this.graphInfo, open, focus);
      if (!open) {
        this.graphInfoEvents?.abort();
        if (focus) (this.graphInfoView === "requirements" ? this.requirementsButton : this.graphInfoView === "issues" ? this.issueNext : this.graphInfoButton)?.focus({preventScroll: true});
      }
    }
    openInspector(open, focus = false) {
      if (!this.inspector) return;
      this._setPanel(this.inspector, Boolean(open && this.selected), focus);
    }
    _panelHeader(panel, label, action, signal) {
      const header = element("div", null, {class: "panel-header"});
      const close = element("button", "Close", {type: "button", "aria-label": `Close ${label.toLowerCase()}`});
      close.addEventListener("click", action, {signal});
      header.append(element("span", label), close);
      const content = element("div", null, {class: "panel-content", tabindex: "0", "aria-label": `${label} content`});
      panel.replaceChildren(header, content);
      return content;
    }
    drawArtifactLegend() {
      for (const artifact of this._graph.artifacts) {
        let key = `@artifact/${artifact.id}`;
        while (this.entities.has(key)) key = "@" + key;
        const count = artifact.segments?.length || 0;
        const button = element("button", null, {type: "button", "data-artifact": artifact.id, "aria-pressed": "false"});
        const dot = element("span", null, {class: "artifact-dot"});
        dot.style.backgroundColor = artifact.color;
        button.append(dot, element("span", artifact.label + (count > 1 ? ` · ${count} segments` : "")));
        this.selectable(button, {...artifact, id: key, artifact_id: artifact.id, identity: {...artifact.identity, "Artifact identity": artifact.id}}, "Artifact");
        this.artifactLegend.append(button);
      }
    }
    highlight() {
      if (!this._graph || !this.views) return;
      const selected = this.hoverId || this.focusId || this.selected;
      const item = this.entities.get(selected);
      const nodes = new Set(), edges = new Set(), emphasized = new Set();
      const connections = [...this._graph.edges, ...(this.reiteration.checked ? this._graph.reiterations : [])];
      const addArtifact = id => { for (const edge of connections) if (edge.artifact_id === id) edges.add(edge.id); };
      if (item) {
        const data = item.data;
        if (data.artifact_id != null) addArtifact(data.artifact_id);
        else if (data.kind && data.kind !== "operator") {
          for (const port of [...data.inputs,...data.outputs]) addArtifact(port.artifact_id);
        } else if (data.kind === "operator") { nodes.add(data.id); emphasized.add(data.id); }
        else if (item.owner) { nodes.add(item.owner); emphasized.add(item.owner); }
      }
      const query = !this.hoverId && !this.focusId ? this.search.value.trim().toLocaleLowerCase() : "";
      if (query) {
        for (const node of this._graph.nodes) if (`${node.id} ${node.label} ${this.entityLabel(node,"Operator occurrence")} ${JSON.stringify(node.identity || {})}`.toLocaleLowerCase().includes(query)) nodes.add(node.id);
        for (const edge of connections) if (`${edge.id} ${edge.label}`.toLocaleLowerCase().includes(query)) edges.add(edge.id);
      }
      // Exactly one adjacency hop for an operator. Artifact focus follows all
      // paths of that identity, including separate, unconnected segments.
      for (const edge of connections) if (nodes.has(edge.source.node) || nodes.has(edge.target.node)) edges.add(edge.id);
      for (const edge of connections) if (edges.has(edge.id)) { nodes.add(edge.source.node); nodes.add(edge.target.node); }
      // Retain the target even without a connected path. Add a port's owner
      // after path expansion so its unrelated artifacts do not become visible.
      if (item?.data.inputs) nodes.add(item.data.id);
      else if (item?.owner) nodes.add(item.owner);
      const enabled = Boolean(item || query);
      for (const node of this._graph.nodes) {
        const view = this.views.get(node.id);
        view?.classList.toggle("dim", enabled && !nodes.has(node.id));
        view?.classList.toggle("emphasized", emphasized.has(node.id));
      }
      for (const edge of [...this._graph.edges,...this._graph.reiterations]) {
        const view = this.views.get(edge.id);
        view?.classList.toggle("dim", enabled && !edges.has(edge.id));
        view?.classList.toggle("highlight", enabled && edges.has(edge.id));
      }
      for (const button of this.artifactLegend.querySelectorAll("button")) button.setAttribute("aria-pressed", String(this.selected === button.dataset.id));
    }
    setMode(mode) {
      if (!["validation", "dashboard"].includes(mode)) throw new TypeError("mode must be validation or dashboard");
      if (!this._graph) return;
      this.mode = mode;
      if (this._legacyData) this._legacyData.mode = mode;
      if (this.modeSelect) this.modeSelect.value = mode;
      this.refreshProgress();
      this.refreshInspector();
    }
    // Transport-free host API. Legacy updateProgress retains its strict revision
    // convention; live samples use a separate checked ownership/order envelope.
    updateLive(value) {
      if (!value || !Number.isSafeInteger(value.generation) || value.generation < 0 || !Number.isSafeInteger(value.revision) || value.revision < 0 || typeof value.sample !== "string" || !Number.isFinite(Date.parse(value.sample)) || !value.progress || value.graph_id !== value.progress.graph_id || value.context_id !== value.progress.context_id) throw new TypeError("Invalid live observation");
      const sampleTime = Date.parse(value.sample);
      const old = this._liveOrder;
      if (old && (value.context_id !== old.context_id || value.graph_id !== old.graph_id)) throw new TypeError("Reset live binding before switching runs");
      if (old && (value.generation < old.generation || value.generation === old.generation && (value.revision < old.revision || value.revision === old.revision && value.progress.revision < old.progressRevision || value.revision === old.revision && value.progress.revision === old.progressRevision && sampleTime <= old.sample))) return false;
      const previous = this._progress;
      // Validate the complete update through the existing checked path. Only
      // after validation succeeds does an equal-revision elapsed sample replace it.
      this._progress = null;
      this._updatingLive = true;
      try { this.updateProgress(value.progress); }
      catch (error) { this._progress = previous; throw error; }
      finally { this._updatingLive = false; }
      this.mode = "dashboard";
      this._liveOrder = {context_id:value.context_id, graph_id:value.graph_id, generation:value.generation, revision:value.revision, sample:sampleTime, progressRevision:value.progress.revision};
      this.refreshProgress();
      return true;
    }
    dispose() {
      this._pausedProgress = null;
      this.disconnectedCallback();
      this.replaceChildren();
      this.shadowRoot?.replaceChildren();
    }
    updateProgress(value) {
      if (!this._graph || !value || value.graph_id !== (this._graph.graph_id || this._graph.id)) throw new TypeError("Progress graph identity does not match this viewer");
      if (typeof value.context_id !== "string" || !Number.isSafeInteger(value.revision) || value.revision < 0 || typeof value.state !== "string" || !finite(value.elapsed_seconds) || !fraction(value.estimated_fraction) || !(value.estimated_remaining_seconds == null || finite(value.estimated_remaining_seconds)) || !Number.isSafeInteger(value.iteration) || value.iteration < 0 || !Array.isArray(value.nodes)) throw new TypeError("Invalid progress snapshot");
      if (this._progress && value.context_id !== this._progress.context_id) throw new TypeError("Reset progress before displaying a different context");
      const operators = this._graph.nodes.filter(n => n.kind === "operator");
      const ids = new Map(operators.map(n => [this._legacyData ? String(n.identity["Validation node"]) : n.id,n.id]));
      const updates = new Map();
      for (const node of value.nodes) {
        const id = ids.get(node.id);
        if (!id || updates.has(id) || !progressStates.has(node.state) || !finite(node.elapsed_seconds) || !Array.isArray(node.steps)) throw new TypeError("Invalid node progress");
        for (const step of node.steps) if (!progressStates.has(step.state) || !finite(step.elapsed_seconds) || !(step.estimated_seconds == null || finite(step.estimated_seconds))) throw new TypeError("Invalid step progress");
        updates.set(id,node);
      }
      if (updates.size !== operators.length) throw new TypeError("Progress must include all operator nodes");
      // Keep the existing strict revision convention. Equal-revision elapsed
      // samples are not introduced under this Package 1 compatibility fix.
      if (this._progress && value.revision <= this._progress.revision) return false;
      this._progress = structuredClone(value);
      this.progressNodes = new Map([...updates].map(([id,node])=>[id,structuredClone(node)]));
      if (this._legacyData) this._legacyData.progress = structuredClone(value);
      this.refreshProgress();
      if (this._updatingLive) {
        if (this.selected && this.inspectorContent) this.inspectProgress(this.selected);
        const content = this.graphInfo?.querySelector('.panel-content');
        if (content && !this.graphInfo.hidden) this.inspectProgress(null, content);
      } else this.refreshInspector();
      return true;
    }
    resetProgress() {
      this._pausedProgress = null;
      this._liveOrder = null;
      this._progress = null;
      this.progressNodes.clear();
      if (this._legacyData) this._legacyData.progress = null;
      this.refreshProgress();
      this.refreshInspector();
    }
    refreshInspector() {
      const selected = this.entities.get(this.selected);
      if (selected) this.inspect(selected.data, selected.kind);
      this.inspectGraph();
    }
    _presentationProgress() {
      const raw = this._progress;
      if (!raw || raw.state !== "paused") { this._pausedProgress = null; return raw; }
      const key = JSON.stringify([raw.context_id,raw.graph_id,this._liveOrder?.generation ?? null]);
      if (!this._pausedProgress || this._pausedProgress.key !== key) this._pausedProgress = {key, value:structuredClone(raw)};
      const held = this._pausedProgress.value, nodes = new Map(held.nodes.map(node=>[node.id,node]));
      // Hold presentation work at the first observed PAUSED sample only. Keep
      // the authoritative snapshot, current state/errors and wall elapsed intact.
      return {...raw, estimated_fraction:held.estimated_fraction, estimated_remaining_seconds:held.estimated_remaining_seconds,
        completed_steps:held.completed_steps, iteration:held.iteration,
        nodes:raw.nodes.map(node=>{const old=nodes.get(node.id);if(!old)return node;const steps=new Map(old.steps.map(step=>[step.index,step]));
          return {...node,elapsed_seconds:old.elapsed_seconds,steps:node.steps.map(step=>{const previous=steps.get(step.index);return previous?
            {...step,elapsed_seconds:previous.elapsed_seconds,estimated_seconds:previous.estimated_seconds,execution_count:previous.execution_count,iteration:previous.iteration}:step})}})};
    }
    refreshProgress() {
      if (!this.progressSummary) return;
      const presented = this._presentationProgress();
      const byId = new Map((presented?.nodes || []).map(node=>[node.id,node]));
      this.displayProgressNodes = new Map([...this.progressNodes].map(([id,node])=>[id,byId.get(node.id)||node]));
      const visible = this.mode === "dashboard", paused = presented?.state === "paused";
      this.shell.classList.toggle("dashboard", visible);
      this.shell.classList.toggle("paused", paused);
      this.progressSummary.hidden = !visible;
      const variant = paused ? "paused" : ["finished", "failed", "aborted", "rejected"].includes(presented?.state) || this._graph?.completed ? "final" : "";
      // The subtitle is a full-width layout row. Its visible wording carries the
      // fact; letting it own hover help would make most of the header a hot area.
      this.subtitle.removeAttribute("data-help");
      this.subtitle.removeAttribute("data-help-variant");
      this._updateDisabledReasons();
      this.progressSummary.replaceChildren();
      if (visible) {
        const p = presented;
        this.subtitle.textContent = p ? "Supplied execution snapshot · duration-based estimates, not measured work counters · no polling or execution by this viewer" : "No execution snapshot supplied · declaration data only";
        if (!p) this.progressSummary.append(element("span", "No progress snapshot supplied. No execution state is inferred."));
        else {
          this.progressSummary.append(element("strong", `${paused ? "Paused · work not advancing" : p.state} · iteration ${p.iteration}${p.max_iterations == null ? "" : ` / ${p.max_iterations}`}`), element("span", `Context ${p.context_id}`), element("span", `Elapsed ${seconds(p.elapsed_seconds)} · includes pauses and waits`, {class:"elapsed-fact", "data-help":"progress.elapsed", "data-help-variant":variant}), element("span", `Remaining step work ${seconds(p.estimated_remaining_seconds)}${paused ? " · held while paused" : ""} (not wall-clock ETA)`));
          const meter = element("div", null, {class: "total-progress", role: "progressbar", "aria-label": "Estimated total progress", "aria-valuemin": "0", "aria-valuemax": "100"});
          const ended = ["finished", "failed", "aborted", "rejected"].includes(p.state);
          const progressLabel = ended ? "Execution ended; fraction does not measure successful work" : (paused ? "Paused · work is not advancing · " : "") + (p.estimated_fraction == null ? "Estimate unavailable" : `~${Math.floor(p.estimated_fraction*100)}% estimated`);
          if (p.estimated_fraction != null) meter.setAttribute("aria-valuenow", Math.floor(p.estimated_fraction*100));
          meter.setAttribute("aria-valuetext", progressLabel);
          const fill = element("span"); fill.style.width = `${(p.estimated_fraction ?? 0)*100}%`; meter.append(fill);
          this.progressSummary.append(meter, element("span", progressLabel));
        }
      } else this.subtitle.textContent = this.payload.kind === "registry" ? "Offline registry snapshot · every included graph remains selectable · show or save again to refresh" : "Definition snapshot · declared structure and bindings, not execution evidence";
      for (const node of this._graph?.nodes || []) {
        if (node.kind !== "operator") continue;
        const view = this.views.get(node.id), meter = view?.querySelector(".progress");
        const steps = this.executionIdentities(node);
        if (view && steps.length) {
          if (!this._graph.completed) view.querySelector(".type").textContent = `STEP ${steps.map(step=>step.index).join(", ")} · OPERATOR`;
          view.setAttribute("aria-label", this.entityLabel(node,"Operator occurrence"));
        }
        if (!meter) continue;
        const p = this.displayProgressNodes.get(node.id), value = nodeFraction(p);
        view.dataset.state = visible && p ? p.state : "";
        const operatorStep = p?.steps.find(step => step.kind === "operator");
        const executions = operatorStep?.execution_count;
        meter.querySelector(".progress-state").textContent = p ? `${paused && p.state === "running" ? "Ⅱ Paused" : `${stateSymbols[p.state]} ${stateCaptions[p.state]}`}${Number.isSafeInteger(executions) ? ` · execution ${executions}` : ""}` : "No snapshot";
        meter.querySelector(".progress-value").textContent = value == null ? p?.state === "skipped" ? "skip" : "—" : `${value > 0 && value < 1 ? "~" : ""}${Math.floor(value*100)}%`;
        const fill = meter.querySelector(".progress-fill"), activity = value == null && p?.state === "running";
        fill.setAttribute("width", (node.width-70)*(value ?? (activity ? .24 : 0)));
        fill.classList.toggle("indeterminate", activity && !paused);
        meter.removeAttribute("aria-valuenow");
        if (value != null) meter.setAttribute("aria-valuenow", Math.floor(value*100));
        meter.setAttribute("aria-valuetext", value == null ? p ? `${stateCaptions[p.state]}; duration estimate unavailable` : "No progress snapshot" : `${value === 1 ? "Completed" : "Estimated step-session progress"}: ${Math.floor(value*100)} percent`);
      }
      this.refreshCompleted();
    }
    _updateDisabledReasons() {
      if (!this._disabledReasons) return;
      const reasons = [];
      if (this.detailsButton.disabled) reasons.push("Select a component for Focus / Details.");
      else if (this.focusButton.disabled) reasons.push("Selection has no visible canvas component for Focus.");
      if (this.reiteration.disabled) reasons.push("Re-iteration unavailable: " + (this._graph?.reiteration.reason || "No eligible mappings supplied."));
      if (this.motion.disabled) reasons.push("Motion disabled by reduced-motion preference.");
      this._disabledReasons.textContent = reasons.join(" ");
      this._disabledReasons.hidden = !reasons.length;
    }
    inspectProgress(id, parent = this.inspectorContent) {
      if (this.mode !== "dashboard" || !this._progress) return;
      const p = this._presentationProgress(), node = id == null ? null : this.displayProgressNodes.get(id);
      if (id != null && !node) return;
      if (id != null) {
        const data = this.entities.get(id)?.data;
        if (data) this.executionIdentity(data, parent);
      }
      const evidence = {"Context": p.context_id, "State": node ? stateCaptions[node.state] : p.state, "Iteration": p.iteration, "Measured seconds": node ? node.elapsed_seconds : p.elapsed_seconds, "Observed at (browser local time)": p.observed_at ? new Date(p.observed_at).toLocaleString(undefined, {timeZoneName:"short"}) : "Unavailable", "Revision": p.revision};
      if (node) {
        const ratio = nodeFraction(node);
        evidence["Measured seconds meaning"] = "Accumulated active time across this node’s steps, repeats and retries; excludes waits.";
        evidence["Step-session progress"] = ratio == null ? "Estimate unavailable" : `${ratio > 0 && ratio < 1 ? "Estimated " : ""}${Math.floor(ratio*100)}%`;
        evidence["Timing meaning"] = "Elapsed time includes executions within this step session. Individual repetition duration and progress are not captured by this snapshot.";
        evidence["Steps"] = node.steps.map(step=>({"Name":step.name,"Kind":step.kind,"Index":step.index,"State":stateCaptions[step.state],"Iteration":step.iteration,"Executions":step.execution_count,"Accumulated active seconds (repeats/retries included)":step.elapsed_seconds,"Estimated full step-session seconds":step.estimated_seconds}));
      } else Object.assign(evidence, {"Completed steps":p.completed_steps,"Total steps":p.total_steps,"Estimated fraction":p.estimated_fraction,"Remaining step work seconds (not wall-clock ETA)":p.estimated_remaining_seconds,"Timing sample support (not accuracy)":p.confidence,"Samples":p.sample_count});
      if (p.state === "paused") evidence["Paused presentation"] = "Work values are held while paused, not newly measured work. Raw supplied evidence is preserved; wall elapsed may continue.";
      if (!node) evidence["Measured seconds meaning"] = "Context elapsed includes local pauses and waits. PAUSED work and remaining step-work estimates do not advance; elapsed may continue.";
      evidence["Coverage"] = "Supplied snapshot only; no execution, recording or polling by this viewer. Duration-based estimates are not measured work counters.";
      const next = element("div", null, {class:"execution-progress"});
      this.section("Execution progress", evidence, next);
      const current = parent.querySelector(':scope > .execution-progress');
      if (!current) { parent.append(next); return; }
      // Patch progress text only. Declaration links, expanded details, focus and
      // the inspector's scroll/camera ownership are unaffected by live samples.
      const patch = (target, source) => {
        if (target.nodeType !== source.nodeType || target.nodeName !== source.nodeName) { target.replaceWith(source); return; }
        if (target.nodeType === 3) { if (target.data !== source.data) target.data = source.data; return; }
        const children = [...source.childNodes];
        children.forEach((child,index) => target.childNodes[index] ? patch(target.childNodes[index],child) : target.append(child));
        while (target.childNodes.length > children.length) target.lastChild.remove();
      };
      patch(current,next);
    }

    zoom(scale) {
      if (!this._graph || !this.svg) return;
      this.autoFit = false;
      this.svg.style.marginLeft = "";
      this.svg.style.marginRight = "";
      this.svg.style.marginBottom = "";
      this.scale = Math.max(.12, Math.min(2.5, scale));
      this.svg.setAttribute("width", this._graph.bounds.width*this.scale);
      this.svg.setAttribute("height", this._graph.bounds.height*this.scale);
      this.svg.style.marginTop = `${Math.max(0,(this.viewport.clientHeight-this._graph.bounds.height*this.scale)/2)}px`;
    }
    fit() {
      if (!this._graph || !this.svg || !this.viewport.clientWidth || !this.viewport.clientHeight) return;
      this.zoom(Math.min(1, (this.viewport.clientWidth-20)/this._graph.bounds.width, (this.viewport.clientHeight-20)/this._graph.bounds.height));
      this.autoFit = true;
    }
    focusSelected() {
      if (!this.selected) return;
      const view = this._focusView();
      if (view) {
        this.autoFit = false;
        // Explicit Focus adds scroll space around boundary components. Without
        // it, a selected entry/exit cannot reach the center at the graph edge.
        // Zoom/Fit reset these margins; ordinary updates never change them.
        this.svg.style.marginLeft = this.svg.style.marginRight = `${this.viewport.clientWidth/2}px`;
        this.svg.style.marginTop = this.svg.style.marginBottom = `${this.viewport.clientHeight/2}px`;
        const bounds = view.getBoundingClientRect(), viewport = this.viewport.getBoundingClientRect();
        this.viewport.scrollTo({
          left: this.viewport.scrollLeft + bounds.left + bounds.width/2 - viewport.left - this.viewport.clientWidth/2,
          top: this.viewport.scrollTop + bounds.top + bounds.height/2 - viewport.top - this.viewport.clientHeight/2,
          behavior: "instant"
        });
        view.focus({preventScroll: true});
      }
    }
    _focusView() {
      const view = this.views.get(this.selected);
      if (view && this.svg?.contains(view)) return view;
      const artifact = this.entities.get(this.selected)?.data.artifact_id;
      const edge = this._graph?.edges.find(item => item.artifact_id === artifact);
      return edge ? this.views.get(edge.id) : null;
    }
    _resetSelection() {
      this.views.get(this.selected)?.classList.remove("selected");
      this.selected = null;
      this.hoverId = this.focusId = null;
      this.searchEvents?.abort();
      this.search.value = "";
      this.searchResults.replaceChildren();
      this.inspectorEvents?.abort();
      // Keep one inert content snapshot for the closing slide; the next selection
      // replaces it. This is not selected/accessible evidence while closed.
      this.openInspector(false);
      this.detailsButton.disabled = true;
      this.focusButton.disabled = true;
      this.focusButton.title = "Select a component to center it";
      this._updateDisabledReasons();
      // Graph information is independent. A reset never opens or closes it.
      const focusTarget = this.canvas.inert ? this.graphInfo.querySelector("button") : this.viewport;
      focusTarget?.focus({preventScroll: true});
      this.highlight();
      this.announce("Component details closed. Selection and highlighting cleared.");
    }
    select(id) {
      if (id === this._graph?.id) {
        this._resetSelection();
        this._openGraphInfo(true);
        return;
      }
      const entity = this.entities.get(id);
      if (!entity) return;
      this.views.get(this.selected)?.classList.remove("selected");
      this.selected = id;
      this.dispatchEvent(new CustomEvent("jayrun-selection", {detail:{graph_id:this._graph.id, selection:id}, bubbles:true, composed:true}));
      this.views.get(id)?.classList.add("selected");
      this.inspect(entity.data, entity.kind);
      this.detailsButton.disabled = false;
      this.focusButton.disabled = !this._focusView();
      this.focusButton.title = this.focusButton.disabled ? "Selection has no visible canvas component" : "Center selected component; keep current zoom";
      this._updateDisabledReasons();
      this.openInspector(true);
      if (this.work.classList.contains("narrow")) this.inspector.querySelector("button")?.focus({preventScroll: true});
      this.highlight();
      this.announce("Selected " + (entity.data.label || id));
    }
    executionIdentities(data) {
      const values = [...(data.identity?.["Execution steps"] || []), ...(this._graph?.identity?.["Execution step correspondence"]?.[data.id] || [])];
      const indices = new Set(data.execution_steps || []);
      for (const session of this._graph?.completed?.executions || []) {
        if (indices.has(session.step_index)) values.push({index:session.step_index, kind:session.kind, name:session.name});
      }
      if (data.kind === "operator") {
        for (const step of this.progressNodes?.get(data.id)?.steps || []) if (step.kind === "operator") values.push(step);
      }
      return [...new Map(values.filter(step => Number.isSafeInteger(step.index) && step.index >= 0 &&
        ["operator","resource"].includes(step.kind) && typeof step.name === "string").map(step => [step.index, step])).values()];
    }
    stepLabel(step) { return `Step ${step.index} · ${step.kind} · ${step.name}`; }
    entityLabel(data, kind) {
      const steps = this.executionIdentities(data);
      return steps.length ? steps.map(step => this.stepLabel(step)).join("; ") : `${data.label || data.id} · ${kind}`;
    }
    executionIdentity(data, parent) {
      if (!parent) return;
      let box = parent.querySelector(":scope > .execution-identity");
      if (!box) { box = element("div", null, {class:"execution-identity", "data-help":"step.identity"}); parent.append(box); }
      const steps = this.executionIdentities(data);
      const text = steps.length ? steps.map(step => this.stepLabel(step)).join("; ") +
        ` — execution-step index ↔ graph component ${data.id}. The component ID is not a step index.` :
        data.kind === "operator" || this.entities.get(data.id)?.kind === "Resource binding" ?
        `Graph component ${data.id} · execution-step correspondence not supplied.` : "";
      if (box.textContent !== text) box.textContent = text;
      box.hidden = !text;
    }
    searchEntities() {
      this.searchEvents?.abort();
      this.searchEvents = new AbortController();
      this.searchResults.replaceChildren();
      const query = this.search.value.trim().toLocaleLowerCase();
      this.highlight();
      if (!query) return;
      const matches = [...this.entities.entries()].filter(([id, e]) => `${id} ${e.data.label || ""} ${this.entityLabel(e.data,e.kind)} ${JSON.stringify(e.data.identity || {})}`.toLocaleLowerCase().includes(query));
      this.searchResults.append(element("div", `${matches.length} matches${matches.length > 30 ? "; showing first 30. Refine the search." : ""}`, {class: "muted", role:"status"}));
      for (const [id, entity] of matches.slice(0, 30)) {
        const button = element("button", `${this.entityLabel(entity.data,entity.kind)} · component ${id}`, {type: "button"});
        button.addEventListener("click", () => {
          this.select(id);
          this.searchResults.replaceChildren();
          // Removing the activated result must not strand keyboard focus.
          if (this.inspector.inert || this.inspector.hidden) this.search.focus({preventScroll:true});
          else this.inspector.querySelector("button")?.focus({preventScroll:true});
        }, {once: true, signal: this.searchEvents.signal});
        this.searchResults.append(button);
      }
    }
    nextIssue(direction) {
      if (!this._graph?.findings.length) return;
      const findings = this._graph.findings;
      this.issueIndex = this.issueIndex < 0 ? (direction < 0 ? findings.length - 1 : 0) : (this.issueIndex + direction + findings.length) % findings.length;
      const finding = findings[this.issueIndex];
      this.select(finding.subject);
      this.issueCount.textContent = `${this.issueIndex+1} / ${findings.length} issues`;
      this.announce(finding.message);
    }
    refreshCompleted() {
      const evidence = this._graph?.completed;
      if (!evidence) return;
      const iteration = Number(this.iterationSelect?.value ?? evidence.iteration_count);
      this.subtitle.textContent = `Finalized ${evidence.outcome} · context ${evidence.context_id} · iteration ${iteration} · retained evidence only`;
      this.shell.classList.add("completed-view");
      const iterationSessions = evidence.executions.filter(s => s.iteration === iteration);
      const activeByNode = new Map(this._graph.nodes.filter(node => node.kind === "operator").map(node =>
        [node.id, iterationSessions.filter(session => session.kind === "operator" && node.execution_steps.includes(session.step_index))
          .reduce((total, session) => total + session.active_seconds, 0)]));
      const maximum = Math.max(0, ...activeByNode.values());
      for (const node of this._graph.nodes) {
        if (node.kind !== "operator") continue;
        const sessions = evidence.executions.filter(s => node.execution_steps.includes(s.step_index) && s.iteration === iteration);
        const states = [...new Set(sessions.map(s => s.outcome.toUpperCase()))];
        const caption = states.join(" / ") || "NO EVIDENCE";
        const type = this.views.get(node.id)?.querySelector(".type");
        if (type) { const steps=this.executionIdentities(node); type.textContent=(steps.length?`STEP ${steps.map(step=>step.index).join(", ")} · `:"")+caption; }
        const operatorSessions = sessions.filter(session => session.kind === "operator");
        const active = activeByNode.get(node.id);
        const count = operatorSessions.reduce((total, session) => total + session.execution_count, 0);
        const view = this.views.get(node.id), meter = view?.querySelector(".progress");
        if (meter) {
          const outcome = operatorSessions.map(session => session.outcome).join(" / ") || "No evidence";
          view.dataset.state = operatorSessions.at(-1)?.outcome || "unknown";
          meter.hidden = false;
          meter.setAttribute("role", "meter");
          meter.setAttribute("aria-label", `${node.label} active session duration`);
          meter.setAttribute("aria-valuemax", String(Math.max(maximum, active, 1e-12)));
          meter.setAttribute("aria-valuenow", String(active));
          meter.setAttribute("aria-valuetext", operatorSessions.length ? `${outcome}; ${seconds(active)} active; ${count} executions` : "No retained execution evidence");
          meter.querySelector(".progress-state").textContent = operatorSessions.length ? `${outcome} · ${count} execution${count === 1 ? "" : "s"}` : "No retained evidence";
          meter.querySelector(".progress-value").textContent = operatorSessions.length ? seconds(active) : "—";
          const fill = meter.querySelector(".progress-fill");
          fill.classList.remove("indeterminate");
          fill.setAttribute("width", (node.width-70)*(maximum ? Math.min(1,active/maximum) : 0));
        }
        for (const resource of node.resources || []) {
          const retained = iterationSessions.filter(session => resource.execution_steps?.includes(session.step_index));
          const marker = this.views.get(resource.id);
          if (marker) marker.querySelector("title").textContent = `${resource.label} · ${retained.map(session=>session.outcome+" · "+seconds(session.active_seconds)+" active").join("; ") || "No retained evidence"}`;
        }

      }
    }
    completedDetail(value, depth = 0) {
      if (value === null || typeof value !== "object") return value;
      if (depth >= 6) return "[inspector depth limit; see bounded export]";
      const entries = Array.isArray(value) ? value.map((v,i)=>[String(i+1),v]) : Object.entries(value);
      const result = Object.fromEntries(entries.slice(0,64).map(([k,v])=>[k,this.completedDetail(v,depth+1)]));
      if (entries.length > 64) result["Omitted"] = `${entries.length-64} entries; see bounded export`;
      return result;
    }
    inspectCompleted(data, parent) {
      const evidence = this._graph?.completed;
      if (!evidence) return;
      const iteration = Number(this.iterationSelect?.value ?? evidence.iteration_count);
      const sessions = evidence.executions.filter(s => s.iteration === iteration && (!data || (data.execution_steps || []).includes(s.step_index)));
      if (!data) {
        this.section("Finalized outcome", {Context: evidence.context_id, Outcome: evidence.outcome, "Stop accepted": evidence.stop_requested ?? "unknown (not captured)", "Iterations started": evidence.iteration_count, "Iterations completed": evidence.completed_iterations, "Elapsed wall seconds": evidence.elapsed_wall_seconds, Failure: evidence.failure}, parent);
        this.section("Evidence coverage", evidence.coverage, parent);
      }
      if (!data || data.execution_steps) {
        parent.append(element("h3", `Iteration ${iteration} · ordered sessions`));
        if (!sessions.length) parent.append(element("p", "No retained session evidence; execution is unknown."));
        const maximum = Math.max(0, ...sessions.map(s => s.active_seconds));
        for (const session of sessions.slice(0, 64)) {
          const row = element("details", null, {class: "completed-session"});
          row.append(element("summary", `${session.id} · ${session.kind} · ${session.name} · ${session.outcome}`));
          const bar = element("meter", null, {min: "0", max: String(maximum || 1), value: String(session.active_seconds), "aria-label": "Active session duration, not wall time"});
          row.append(element("p", `Active ${seconds(session.active_seconds)} · duration bar, not a timeline`), bar);
          this.tree(row, {"Step index": session.step_index, "Skip reason": session.skip_reason, "Attempts (recorded order)": this.completedDetail(session.attempts)});
          parent.append(row);
        }
        if (sessions.length > 64) parent.append(element("p", `${sessions.length-64} sessions omitted from inspector; complete bounded evidence remains in export.`));
        const records = evidence.records.filter(r => r.iteration === iteration && (!data || (data.execution_steps || []).includes(r.step_index)));
        this.section("Retained context records", this.completedDetail(records), parent);
        if (records.length > 64) parent.append(element("p", `${records.length-64} records omitted from inspector; see export.`));
      }
      if (data?.artifact_id) {
        const artifact = evidence.artifacts.find(a => a.id === data.artifact_id);
        const connection = evidence.connections?.find(c => c.id === data.completed_connection);
        if (artifact && connection) {
          const history = artifact.history.filter(r => r.iteration === iteration && connection.producer_history_indices.includes(r.retained_index));
          this.section(`Connection history · iteration ${iteration}`, {
            "Coverage": connection.coverage, "Artifact history coverage": artifact.history_coverage,
            "Retained producer entries": this.completedDetail(history),
            "Consumer session evidence (not lifecycle events)": this.completedDetail(evidence.executions.filter(s => s.iteration === iteration && connection.consumer_sessions.includes(s.id))),
            "Other entries": "Select the artifact in the legend for all retained history; unassigned entries are not copied onto each discrete segment."
          }, parent);
        } else if (artifact) this.section("Artifact history (all retained iterations)", this.completedDetail(artifact), parent);
      }
    }
    tree(parent, value) {
      if (value === null || typeof value !== "object") {
        parent.append(element("span", value === null ? (this._graph?.completed ? "None (recorded field)" : "None (declared)") : String(value)));
        return;
      }
      const entries = Array.isArray(value) ? value.map((item, i) => [String(i+1), item]) : Object.entries(value);
      if (!entries.length) { parent.append(element("span", (this._graph?.completed ? "No retained entries" : "None declared"), {class: "muted"})); return; }
      const dl = element("dl");
      for (const [key, item] of entries) {
        if (item !== null && typeof item === "object") {
          const wrapper = element("details");
          wrapper.append(element("summary", key));
          this.tree(wrapper, item);
          const term = element("dt", key);
          const definition = element("dd");
          wrapper.firstChild.textContent = "Details";
          definition.append(wrapper);
          dl.append(term, definition);
        } else {
          dl.append(element("dt", key), element("dd", item === null ? (this._graph?.completed ? "None (recorded field)" : "None (declared)") : String(item)));
        }
      }
      parent.append(dl);
    }
    section(label, value, parent = this.inspectorContent) {
      parent.append(element("h3", label));
      this.tree(parent, value);
    }
    link(label, id, parent = this.inspectorContent, signal = this.inspectorEvents.signal) {
      const button = element("button", label, {type: "button", class: "link"});
      button.addEventListener("click", () => {
        this.select(id);
        this.inspector.querySelector("button")?.focus({preventScroll: true});
      }, {signal});
      parent.append(button);
    }
    technical(data, parent = this.inspectorContent, signal = this.inspectorEvents.signal) {
      const details = element("details", null, {class: "technical"});
      details.append(element("summary", "Technical identities", {"data-help":"graph.identity"}));
      const values = {"Presentation identity": data.id, ...(data.identity || {})};
      this.tree(details, values);
      const row = element("div", null, {class:"copy-row"});
      const copy = element("button", "Copy identities", {type: "button", "data-help":"action.copy"});
      const feedback = element("span", "", {class:"copy-feedback", role:"status", "aria-live":"polite", "aria-atomic":"true"});
      copy.addEventListener("click", event => {
        const text = Object.entries(values).map(([key, value]) => `${key}: ${typeof value === "object" ? JSON.stringify(value) : value}`).join("\n");
        void copyText(event.currentTarget, text, signal);
      }, {signal});
      row.append(copy, feedback);
      details.append(row, element("small", "Manual copy: select the full values above.", {class:"muted"}));
      parent.append(details);
    }
    inspectGraph(force = false) {
      if (this.graphInfo.hidden && !force) return;
      this.graphInfoEvents?.abort();
      this.graphInfoEvents = new AbortController();
      const signal = this.graphInfoEvents.signal;
      const content = this._panelHeader(this.graphInfo, this.graphInfoView === "issues" ? "Graph issues" : "Graph info", () => this._openGraphInfo(false, true), signal);
      if (this.graphInfoView === "issues") {
        const findings = this._graph?.findings || [];
        content.append(element("h2", `${findings.length} ${findings.length === 1 ? "issue" : "issues"}`));
        for (const finding of findings) this.link(finding.message, finding.subject, content, signal);
        return;
      }
      if (this.graphInfoView === "requirements" && this.payload.kind === "registry") {
        this.inspectRequirements(content, signal);
        return;
      }
      const data = this._graph || this.payload;
      content.append(element("div", this._graph ? "Graph definition" : "Registry snapshot", {class: "kind"}), element("h2", data.label));
      if (data.description) content.append(element("p", data.description));
      if (this._graph) content.append(this.counts);
      const intrinsic = data.identity?.["Intrinsic graph ID"];
      content.append(element("p", /^jrg1:[0-9a-f]{64}$/.test(intrinsic || "") ?
        `Graph ID ${intrinsic.slice(0,17)}… · full ID in Technical identities` : "Graph ID unavailable in this snapshot", {class:"graph-identity"}));
      this.section("Details", data.details || {}, content);
      if (this._graph) {
        this.section("Re-iteration", {"Eligibility": data.reiteration.eligibility, "Mappings": data.reiterations.length, "Meaning": data.reiteration.reason || "Explicit structural mappings only; no execution evidence."}, content);
        if (data.findings.length) {
          content.append(element("h3", "Findings"));
          for (const finding of data.findings) this.link(finding.message, finding.subject, content, signal);
        }
      }
      this.inspectCompleted(null, content);
      this.inspectProgress(null, content);
      this.technical(data, content, signal);
    }
    inspectRequirements(content, signal) {
      content.append(element("div", "REGISTRY SNAPSHOT", {class: "kind"}), element("h2", "Requirements"));
      const evidence = this.payload.requirements;
      if (!evidence) {
        content.append(element("p", "Requirement evidence was not included in this snapshot. No compatibility is inferred."));
        return;
      }
      content.append(element("p", evidence.source));
      const labels = new Map(this.graphs.map(graph => [graph.id, graph.label]));
      const selected = evidence.graphs.find(row => row.graph_id === this._graph?.id);
      content.append(element("h3", "Selected graph"));
      if (selected) {
        content.append(element("p", labels.get(selected.graph_id)), element("p", selected.status === "consistent" ? "Individually consistent direct declarations" : selected.status === "invalid" ? "Individually invalid declarations" : "Individual requirements unavailable", {class: "badge"}));
        if (selected.error) content.append(element("p", selected.error));
        if (!selected.declarations.length) content.append(element("p", "No direct requirements captured."));
        for (const declaration of selected.declarations) content.append(element("p", declaration, {class: "requirement-declaration"}));
      } else content.append(element("p", "No graph selected."));
      const combined = evidence.combined;
      content.append(element("h3", "All included graphs in one environment"));
      content.append(element("p", combined.status === "conflict" ? "Combined-environment conflicts" : combined.status === "unavailable" ? "Combined check unavailable: individual declarations are invalid or unavailable" : "No conflict found by the declaration resolver", {class: "badge"}));
      if (combined.status === "conflict") content.append(element("p", "These constraints conflict when combined; the individual graphs remain separately usable where their own requirements are satisfied."));
      for (const conflict of combined.conflicts) {
        const detail = element("details", null, {class: "requirement-conflict"});
        detail.append(element("summary", conflict.name + (conflict.marker ? " · " + conflict.marker : "") + " · conflicting constraints"));
        detail.append(element("p", conflict.message));
        for (const contributor of conflict.contributors) {
          const line = element("p");
          const button = element("button", labels.get(contributor.graph_id), {type: "button", "data-requirement-graph": contributor.graph_id});
          button.addEventListener("click", () => { this.switchGraph(contributor.graph_id); this.graphInfo.querySelector(".panel-content")?.focus({preventScroll: true}); }, {signal});
          line.append(button, element("span", " · " + contributor.requirement)); detail.append(line);
        }
        content.append(detail);
      }
      if (combined.constraints.length) {
        const details = element("details"); details.append(element("summary", "Non-conflicting combined constraints"));
        for (const text of combined.constraints) details.append(element("p", text, {class: "requirement-declaration"}));
        content.append(details);
      }
      content.append(element("h3", "Per-graph checks"));
      for (const row of evidence.graphs) {
        const line = element("p");
        const button = element("button", labels.get(row.graph_id), {type: "button", "data-requirement-graph": row.graph_id});
        button.addEventListener("click", () => { this.switchGraph(row.graph_id); this.graphInfo.querySelector(".panel-content")?.focus({preventScroll: true}); }, {signal});
        line.append(button, element("span", ` · ${row.status} · ${row.declarations.length} declarations`));content.append(line);
      }
      content.append(element("h3", "Scope and limitations"));
      for (const note of evidence.coverage) content.append(element("p", note));
    }
    inspect(data, kind) {
      this.inspectorEvents?.abort();
      this.inspectorEvents = new AbortController();
      this.inspectorContent = this._panelHeader(this.inspector, "Component details", () => this._resetSelection(), this.inspectorEvents.signal);
      const heading = element("div", null, {class: "inspector-heading"});
      heading.append(element("h2", data.label || this.palette.get(data.artifact_id)?.label || data.id), this._help.info("step.identity", "About execution-step identity"));
      this.inspectorContent.append(element("div", kind, {class: "kind"}), heading);
      this.executionIdentity(data, this.inspectorContent);
      if (data.description) this.inspectorContent.append(element("p", data.description));
      const artifactId = data.artifact_id ?? (data.kind !== "operator" ?
        [...(data.inputs || []),...(data.outputs || [])].find(port => port.artifact_id != null)?.artifact_id : null);
      if (artifactId != null) this.section("Identity", {"Artifact identity": artifactId,
        [data.kind ? "Node identity" : data.source ? "Connection identity" : "Port / component identity"]: data.id});
      if (data.state) this.inspectorContent.append(element("div", data.state, {class: "badge"}));
      if (data.status) this.inspectorContent.append(element("div", `${symbols[data.status]} ${data.status.toUpperCase()}`, {class: "badge"}));
      if (data.inputs) {
        for (const [heading, ports] of [["Inputs", data.inputs], ["Outputs", data.outputs]]) {
          const values = {};
          for (const [index, port] of ports.entries()) {
            const label = ports.filter(p => p.label === port.label).length > 1 ? `${port.label} · ${index+1}` : port.label;
            values[label] = {"Artifact": this.palette.get(port.artifact_id)?.label || "Unbound", ...(port.description ? {"Description": port.description} : {}), ...(port.details || {})};
          }
          this.section(heading, values);
        }
        if (data.resources?.length) {
          this.inspectorContent.append(element("h3", "Resource bindings"));
          for (const marker of data.resources) this.link(marker.label + " · " + marker.state, marker.id);
        }
      }
      if (data.source && data.target) this.section("Connection", {"Artifact": this.palette.get(data.artifact_id)?.label, "From": this.entities.get(data.source.node)?.data.label || data.source.node, "Output": this.entities.get(data.source.port)?.data.label || data.source.port, "To": this.entities.get(data.target.node)?.data.label || data.target.node, "Input": this.entities.get(data.target.port)?.data.label || data.target.port});
      if (data.segment?.count > 1) this.section("Artifact lifecycle / path segments", {"Segment": `${data.segment.index} of ${data.segment.count}`, "Meaning": "Disjoint paths share an artifact identity color, not a continuous value across the gap.", ...this.palette.get(data.artifact_id)?.details});
      if (data.provenance) this.section("Eligibility evidence", {"Provenance": data.provenance, "Meaning": "Structural eligibility, not observed execution. Toggle changes presentation only."});
      if (data.details) this.section("Details", data.details);
      const findings = this._graph.findings.filter(finding => finding.subject === data.id);
      if (findings.length) this.section("Findings", findings.map(finding => finding.message));
      this.inspectCompleted(data, this.inspectorContent);
      this.inspectProgress(data.id);
      this.technical(data);
    }
    exportData() {
      if (!this._graph) { this.announce("No graph selected."); return; }
      const url = URL.createObjectURL(new Blob([JSON.stringify(this._graph, null, 2)], {type: "application/json"}));
      const link = element("a", "", {href: url, download: "graph-viewer-data.json"});
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    }
  }
  customElements.define("jayrun-graph", GraphView);
})();
