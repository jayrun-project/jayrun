# Observe progress and events

`run.progress` describes the current committed progress view. Factual state, counters and measured timing should be distinguished from optional learned estimates. Waiting, placement contention, pause time and changing workload evidence can change an estimate; it is not a calibrated completion deadline.

Choose timing-relevant configuration fields before graph confirmation. Persisted timing profiles can warm estimates in later sessions, but bounded samples, late capture and different configurations/hardware limit what those estimates establish.

## Application observers

An Engine owner can create an independent `engine.observer(capacity=256)`. Consume and close it according to the [observer reference](../../reference/records.md). A supervising component instead uses its one `self.runtime.events` queue. Both have bounded observation semantics; a queue overflow is explicit and must not be silently treated as a complete history.

Reconcile an event-driven display with current snapshots/live lists and, if authorized, bounded terminal summaries. Very fast work, downtime and overflow can precede observation. A Database cannot invent an event or graph layout never captured.

## Read a progress sample

With a ContextRun returned by submission:

```python
progress = run.progress
print(progress.context_state.value, progress.completed_steps)
if progress.estimated_remaining_seconds is not None:
    print("Estimated remaining step work:", progress.estimated_remaining_seconds)
```

The sample's state and completed-step count describe observed work. Remaining seconds is an estimate of step work, not a wall-clock deadline for concurrent execution. A finalized failed run can have a completion fraction of 1: the work has ended, but did not succeed.

## Consume and close an application observer

The [diagnostics example](reports.md#walk-from-a-report-to-an-execution-record) creates its observer before submitting work, then closes and drains it after waiting. Closing preserves already queued events and allows iteration to finish. While the Engine is running, an async application can instead use `async for event in observer` and react as events arrive, closing the observer in its owning scope's `finally` block.

Each event carries `context_id` and an atomic `snapshot`. For example, inspect `event.snapshot.state` to update a display. Progress changes alone do not emit events; sample `run.progress` when the display needs fresh estimates. If consumption raises ObserverOverflowError, report the gap and refresh from current run state rather than assuming the last event is current.

## Presentation boundaries

Paused contexts can retain authoritative elapsed time that includes pause/wait periods. A display estimate or animation is not a new runtime measurement. Show unavailable information and gaps as such. For remote shadows, sample age and owner information matter; received pressure is not automatic liveness detection.

Use [terminal/durable history](../runtime/history.md) for coverage beyond live lists and [visualization and reporting](plots.md) for presentation. See [supported limits](../../reference/limits.md) before claiming deterministic progress or complete observation.
