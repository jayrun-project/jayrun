# Changelog

All notable changes to Jayrun are documented in this file.

Release notes describe new capabilities, compatibility changes and fixes.

## [0.3.4] - 2026-11-25

### Added

- The dashboard's **Contexts** tab shows up to eight recently finished runs. A run keeps its searchable display ID when it finishes, including when it finishes between active-list refreshes. Open its summary or continue to scoped History.
- **Activity → Execution logs** shows retained `self.execution.log(message)` entries after finalization, labeled by step, iteration, execution and attempt. **Report** links to the logs. Application values recorded with `self.context.record(...)` remain available under **Records**.
- `HistoryQuery` supports `by_finish=True` for completion-time ordering and `identity_digest` for exact display-ID lookup. Custom storage backends serving dashboard History should support both fields. Publication order remains the default.

### Fixed

- The active table, its quick-detail panel and the recently finished list keep their positions as jobs come and go. The active pager appears only when more than 25 matches need it. Keyboard focus and pointer selection follow short-lived runs through completion.
- History orders matching contexts before pagination and can resolve a displayed run ID from recorded SQLite history after a dashboard restart. Run summaries copy the execution engine ID, preserve captured graph names and explain when a graph definition is unavailable.
- Graph fit, zoom and pan preserve the intended point of focus. Camera position, selection and open issues survive run finalization. Narrow layouts keep the active workspace tab in view and make more room for the graph.
- The documentation corrects the first-graph walkthrough, input ownership and recording-mode examples. Eight retired chapter URLs now lead to their replacements within the same manual version.

## [0.3.3] - 2026-11-23

### Added

- Operators and resource setup hooks can read the current graph iteration from
  `self.context.iteration`. It starts at 1 and stays the same when an operator
  repeats or an invocation retries within that iteration.

## [0.3.2] - 2026-11-22

### Fixed

- On Windows, context admission and `Engine.pressure` now read available
  physical memory and the process's current working set through Win32. This
  fixes an `AttributeError` during pressure sampling and allows the scheduler
  to enforce a configured CPU memory limit and resume queued work after recovery.
- On Windows, `Database()` now uses `LOCALAPPDATA` when set, including in
  processes without a home directory. It consults the user profile only
  when it needs the fallback path.

## [0.3.1] - 2026-11-17

### Added

- `EngineSettings.controller_policy` with `ControllerPolicy.HOST_ONLY` (default)
  and `ControllerPolicy.DELEGATED`, available from `jayrun.settings`.
- With `DELEGATED`, live Controllers can submit child Controller and Supervisor
  workflows. Child Controllers may submit further workflows with authority.
- Controllers can submit newly constructed, confirmed `GraphDefinition` objects
  directly without a graph registry, as well as registered graph identities.

- Optional graph `name` and `description`, preserved without changing structural
  graph identity.
- Structured declaration reports through `graph.report.to_dict()` and
  `graph.report.to_json()`, using schema `jayrun.declaration/1`. Reports preserve
  authored intent, component references, bindings and construction limitations.
- A separate **Export declaration report** action in confirmed graph viewers,
  including registry and captured dashboard views. The download preserves the
  report JSON exactly, including integers outside JavaScript's safe range.

### Changed

- `self.runtime.submit(graph, artifacts, configs, settings=..., authority=...)`
  now matches `Engine.submit()` arguments and validation rules. A configured
  registry still requires submitted graph objects to be registered.
- Controller guides and API references explain delegated submission, child
  lifetimes, explicit history grants, routing and capacity requirements.
- Engine history settings include the selected `controller_policy`.

### Fixed

- Owned Engine startup now bounds loop initialization and cross-thread readiness
  acknowledgement to five seconds, with bounded failure cleanup. External event
  loop ownership is unchanged; this is not a deadline for the entire start call.
- Graph viewers display authored graph names/descriptions and support long
  descriptions within their aggregate export bounds.
- Legacy viewer detail strings now use safe inspection metadata, avoiding raw
  representations that could bypass sensitive-default redaction.

### Compatibility

- Replace keyword `runtime.submit(graph_key=...)` with `runtime.submit(graph=...)`.
  Existing positional registered-identity calls continue to work.
- Under `HOST_ONLY`, any non-None runtime `authority` raises `PermissionError`;
  previously the unsupported keyword raised `TypeError`. Host authority grants
  remain available under either policy.
- Ordinary contexts and Supervisors still cannot submit workflows. Supervisor
  graph scope is unchanged. Children belong to the Engine and can outlive their
  parent; parent-issued handles and borrowed history readers keep their existing
  authority lifetimes.
- Waiting parents retain execution slots. Configure sufficient `max_tasks` and
  `max_workers` for nested workflows. Delegation does not add automatic child
  cancellation, deadlock prevention or a process sandbox.

- Text reports and existing viewer/execution exports remain available. Declaration
  JSON requires a confirmed graph and does not include operator implementations,
  submitted values or execution evidence. Missing construction information and
  redacted defaults are explicit; no automatic reconstruction or importer is added.
- Existing aggregate viewer and dashboard capture limits still apply. Regenerate
  old HTML exports to include declaration reports; history-only snapshots without
  a captured report cannot supply one.

## [0.3.0] - 2026-09-28

### Added

- SQLite-backed execution/session history, bounded retention, explicit flush and
  scoped historical readers through `jayrun.persistence`.
- Portable configuration and ContextRecord codecs through `jayrun.serialization`.
- Public inspection, report and lifecycle types organized into documented facades.
- Interactive definition, registry and completed-run viewers, plus a dashboard
  with consistent themes and an offline documentation preview.
- A rebuilt manual, runnable examples and seven application tutorials with
  matching Python sources and notebooks.

### Changed

- Graphs require explicit `graph.confirm()` after binding resources and serializers.
  Confirmation validates and freezes preparation; invalid graphs remain inspectable.
- Submit with `engine.submit(graph, artifacts, configs, settings=...)`. ArtifactContext
  and ConfigContext are value builders rather than graph-bound submission wrappers.
- One `EngineSettings.failure_mode` governs execution and owned persistence.
  Standalone Database operations remain strict; use explicit flush to check settlement.
- Configuration accepts bounded immutable built-in values; use a string such as
  `"float32"` instead of a Python/library object such as `torch.float32`.
- Settings are keyword-only. RecordingMode, engine_id, unfinished_contexts and
  database methods with an `_async` suffix use consistent terminology.
- `ArtifactPolicy(retained_artifacts=None)` retains eligible exits, `()` retains
  none, and a tuple selects declared exits. Retention does not cap total process RSS.
- Strengthened operator-output handling, failure-reference cleanup and lifecycle
  qualification. Simplified public imports and updated all published examples.

### Compatibility

0.3.0 includes breaking changes from 0.2.0. For example:

```python
# 0.2: graph-bound builders, inferred graph at submission
artifacts = ArtifactContext(graph=graph)
configs = ConfigContext(graph=graph)
run = engine.submit(artifacts, configs)

# 0.3: prepare explicitly, then submit the graph and value builders
# Bind required resources/serializers before confirming.
graph.confirm()
artifacts = ArtifactContext({source: value})
configs = ConfigContext({operator.factor: 3})
run = engine.submit(graph, artifacts, configs)
```

Replace `ArtifactContext.clear_entries()` with `clear()`. Builder validation occurs
at submission; retired no-argument builder `validate()` methods and public compiled
plan/layout access are removed. BaseOperator construction is unchanged. Component
identity versions remain independent of the package version.

History is bounded diagnostic evidence, not automatic application checkpointing or
an exactly-once event archive. Concurrency, placement and cooperative shutdown retain
their documented limits. See the [current manual](https://jayrun.readthedocs.io/en/latest/)
for supported imports, complete examples and operational limits.

## [0.2.0] - 2026-09-01

### Added

- Added `ContextRun`, a stable object for observing and controlling one submitted context throughout its lifecycle.
- Added synchronous and asynchronous waiting through `ContextRun.wait()`, `ContextRun.wait_async()`, `Engine.wait()`, and `Engine.wait_async()`; a run can also be awaited directly.
- Added terminal artifact access through `ContextRun.artifact()` and terminal reporting through `ContextRun.report`.
- Added context-scoped stored-value access through `ContextRun.get_value()`, `get_values()`, `get_value_record()`, and `get_value_records()`.
- Added graph-scoped supervision with `Engine.submit(..., supervises=...)`. Supervisors see only runs belonging to the exact graph objects they are authorized to supervise.
- Added authorized runtime identities and a serialized messaging path for lifecycle control and context storage across thread boundaries.
- Added continuous-integration checks and stricter automated documentation builds.

### Changed

- `Engine.submit()` now returns a `ContextRun` and accepts graph-bound `ArtifactContext` and `ConfigContext` objects as the submission boundary.
- Unified external and in-graph supervision around the same `ContextRun` observation, waiting, and control API.
- Unified pause, resume, stop-iteration, abort, and store requests through the runtime messaging system.
- Completed runs are released from the engine registry while existing `ContextRun` objects remain usable for reports, retained artifacts, and stored values.
- Clarified lifecycle terminology: `stop()` prevents another graph iteration, while `abort()` prevents further dispatch and drains accepted work.
- Strengthened context finalization, executor cleanup, placement reconciliation, and graceful and forced shutdown behavior.
- Expanded public docstrings and generated the API Reference from the documented public API.
- Revised the explanatory documentation and tutorials to use the stabilized context lifecycle and supervision APIs.

### Removed

- Removed the public `ContextSnapshot` workflow in favor of the single live-to-terminal `ContextRun` abstraction.
- Removed legacy split context result and status pathways superseded by `ContextRun`.

## [0.1.0] - 2026-08-28

### Added

- Initial public release.
- Artifact-centric computational graphs with explicit configuration and artifact contexts.
- Iterative graph execution and repeated operator execution.
- Synchronous and asynchronous operators.
- Shared resource lifecycle management.
- CPU, GPU, and multi-device placement reservations.
- Graph validation, inspection, and interactive plotting.
- Context supervision, failure handling, and coordinated shutdown.

[0.2.0]: https://github.com/jayrun-project/jayrun/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/jayrun-project/jayrun/releases/tag/v0.1.0

[0.3.0]: https://github.com/jayrun-project/jayrun/compare/v0.2.0...v0.3.0

[0.3.1]: https://github.com/jayrun-project/jayrun/compare/v0.3.0...v0.3.1

[0.3.2]: https://github.com/jayrun-project/jayrun/compare/v0.3.1...v0.3.2

[0.3.3]: https://github.com/jayrun-project/jayrun/compare/v0.3.2...v0.3.3
