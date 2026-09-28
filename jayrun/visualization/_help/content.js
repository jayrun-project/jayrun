/* Private semantic catalog: no runtime values, HTML, queries or authority. */
[
  ["graph.navigation", {
    brief: "Presentation controls change only this view; they do not execute the graph.",
    detail: "Search selects a component without moving the camera. Drag to pan; use zoom, Fit or Focus to change the camera. Graph info and Details open overlays. Re-iteration shows structural mappings, not executed work. Escape dismisses help first, then the existing graph selection or drawer."
  }],
  ["graph.snapshot", {
    brief: "A definition snapshot describes declared structure and bindings, not execution evidence.",
    detail: "Show or save again to capture later declaration changes. Presentation identities locate components in this layout; they are not execution-step identities or access grants."
  }],
  ["registry.snapshot", {
    brief: "All included graphs belong to this captured registry snapshot; switching does not register or execute them.",
    detail: "Registry key and version identify registrations. An intrinsic graph ID identifies a declaration, while the presentation identity identifies the displayed layout. Show or save again to capture later registrations."
  }],
  ["graph.search", {
    brief: "Search uses visible labels and retained identities. Selecting a result keeps the current camera.",
    detail: "Use the result's step index, operator/resource kind and label to distinguish duplicate names. Definition-only views have no compiled step identity. Arrow keys move through results; Enter selects and Escape clears the search."
  }],
  ["graph.selection", {
    brief: "Focus centers the selected component; Details opens its evidence without changing the camera.",
    detail: "Select a graph component first. Clicking empty graph space clears selection without resetting established zoom or pan. Dragging pans without clearing selection."
  }],
  ["graph.reiteration", {
    brief: "Shows verified structural next-iteration mappings only; it does not execute another iteration.",
    detail: "Ordinary dependencies stay visible. Eligibility and unavailable-mapping reasons come from the supplied declaration evidence, not from this help."
  }],
  ["graph.requirements", {
    brief: "Direct declarations and combined conflicts are not installation, transitive-dependency or platform verification.",
    detail: "Each graph can be individually consistent while the included graphs have a combined conflict. The existing resolver groups by package name and identical marker text. Contributors identify the constraint group, not a minimal unsatisfiable set."
  }],
  ["graph.identity", {
    brief: "Graph, context, registry and layout identities have different meanings; none grants access.",
    detail: "An intrinsic graph ID identifies the declaration. Context identity identifies a run; registry key/version identifies a registration. Presentation identity locates an element in a specific layout. Compact IDs are labels only; exact full values remain in technical details and copy actions."
  }],
  ["step.identity", {
    brief: "A retained execution-step index identifies work; a presentation node ID only locates a graph component.",
    detail: "One graph component may correspond to operator or resource steps. Use the supplied step index and kind to correlate records and reports. Definition-only views never invent compiled indices."
  }],
  ["graph.captured", {
    brief: "This is the definition retained for the selected run, not a replacement from the current registry.",
    detail: "Missing layouts stay unavailable. A stored graph and its identities do not make historical evidence resumable or grant live control."
  }],
  ["progress.fraction", {
    brief: "Progress is a work estimate when available, not proof of success or a guaranteed completion time.",
    detail: "Timing sample support is not prediction accuracy. Unbounded contexts have no whole-context completion percentage. Final outcomes and retained evidence determine what actually happened.",
    variants: {
      paused: {brief: "Paused work and remaining estimates are held, not counted forward.", detail: "Context wall elapsed may still increase because it includes pauses and waits. The display holds the first paused work sample without rewriting the supplied snapshot. Resume releases the hold; final values follow finalized evidence."},
      final: {brief: "Execution has ended; the displayed percentage does not measure successful work.", detail: "Use the visible final outcome, failures and retained evidence. Missing or pruned work cannot be inferred from a progress percentage."}
    }
  }],
  ["progress.elapsed", {
    brief: "Context wall elapsed includes pauses and waits; it is not an active-work timer.",
    detail: "Elapsed and work estimates answer different questions. Help does not calculate a new timing metric or change the authoritative snapshot.",
    variants: {
      paused: {brief: "Elapsed may increase while Paused; work and remaining estimates stay held.", detail: "The authoritative context wall timer includes pauses and waits. The UI holds the first paused work sample rather than inventing a past pause time or active-only elapsed metric."},
      final: {brief: "Final elapsed is the retained context wall duration, including pauses and waits.", detail: "Finalized values no longer advance. Unavailable historical elapsed is not zero and is not reconstructed from unrelated timestamps."}
    }
  }],
  ["evidence.retained", {
    brief: "Retained evidence is a bounded subset; storage does not reconstruct missing observations.",
    detail: "Missing, pruned, unsupported and display-omitted values remain distinct where supplied. No completeness or chronology is inferred from absence. Full retained fields remain available beside their summaries."
  }],
  ["evidence.artifacts", {
    brief: "Only retained artifact lifecycle metadata is shown, never artifact payloads.",
    detail: "PRODUCTION and PERFORMANCE normally retain the latest entry; DEBUG retains the recorded sequence. The public snapshot does not identify recording mode. Missing or omitted entries cannot be reconstructed."
  }],
  ["evidence.records", {
    brief: "Records are context-local retained values; a table filter does not filter charts, summaries or exports.",
    detail: "None is a recorded value, not missing evidence. Sequence and execution-step references remain available. Charts can downsample numeric values; exact retained values stay in the table and export."
  }],
  ["evidence.configuration", {
    brief: "Declared defaults, submitted values and captured effective values are different evidence.",
    detail: "Only retained fields are shown. An omitted effective value is not inferred from a default or submitted value. Redaction and capture gaps remain visible; help never reads configuration values."
  }],
  ["evidence.settings", {
    brief: "Requested overrides and captured effective settings are distinct; omissions remain explicit.",
    detail: "These settings describe the selected execution evidence. Opening this view does not apply new settings or change recording, retention or failure policy."
  }],
  ["evidence.activity", {
    brief: "Retained lifecycle events and observed control requests have separate recorded orders.",
    detail: "No global timeline, missing event or unseen transition is inferred. A submitted request is not an observed completed transition. Raw retained fields remain available."
  }],
  ["evidence.history", {
    brief: "Historical evidence is read-only, not a resumable checkpoint or a live-control grant.",
    detail: "Only already retained evidence is available offline. Missing reports, records, configuration or layouts stay unavailable. Full identities describe provenance, not authority."
  }],
  ["evidence.report", {
    brief: "A finalized report describes retained evidence, not unseen events or guaranteed completeness.",
    detail: "Report export includes the available report, not artifact payloads or a resumable execution. Failure and evidence-gap notices remain part of the visible view."
  }],
  ["evidence.access", {
    brief: "Capability labels describe observed evidence; they do not confer permission.",
    detail: "Unknown means the public snapshot does not expose the grant. Historical visibility is read-only. Actions still pass through their existing authority checks."
  }],
  ["action.export-graph", {
    brief: "Exports the entire currently displayed graph data, not just the selected component.",
    detail: "The export preserves the existing data scope and evidence. Selecting a component only changes the view; it does not narrow this export or create another export API."
  }],
  ["action.copy", {
    brief: "Copies the exact full displayed identities. Copied or Failed appears beside the action.",
    detail: "Clipboard access can be unavailable in an offline file or restricted browser. Full values remain selectable for manual copying; abbreviated labels are never substituted for full IDs."
  }],
  ["view.theme", {
    brief: "Theme changes presentation only. Offline exports start in light unless a caller selects another theme.",
    detail: "Explicit light or dark choices remain supported. The dashboard retains its existing browser preference; portable files do not read or write a shared theme preference."
  }],
  ["view.motion", {
    brief: "Motion highlights presentation states only; reduced-motion preferences take precedence.",
    detail: "Static labels and state cues remain available without animation. Paused work does not animate as advancing work."
  }]
]
