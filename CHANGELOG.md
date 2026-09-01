# Changelog

All notable changes to Jayrun are documented in this file.

Jayrun is still pre-1.0, so public APIs may continue to evolve as the design is refined.

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
