# Execution, placement and shutdown problems

| Symptom | Likely boundary | How to resolve |
| --- | --- | --- |
| Operator is `SKIPPED` with `missing_input` | A connected input value is None | Inspect the producer/conditional route; optional binding does not change this rule |
| Wrong output count | Execute return normalization | Return one position per declared output; wrap a tuple payload in Data |
| Run wait returns but computation failed | Wait completed finalization | Check state and `run.report.data.failure`; waits do not assert success |
| Wait for PAUSED returns another state | Run terminated before reaching requested state | Inspect current state rather than assuming the wait target was reached |
| Placement cannot fit | Impossible request/device description | Correct backend/device/group capacity; waiting longer cannot enlarge it |
| Placement waits indefinitely | Contention, retained leases or non-returning work | Inspect pressure/resource owners and reduce contention; keep request order stable |
| Effects occur twice | Retry, repeat, iteration or placement restart | Put effects after admission and make external actions idempotent |
| Record capacity error | Per-key or accounted-byte admission | Choose a smaller payload/history or justified bounds; do not store model blobs in records |
| Shutdown timeout | Accepted work or application cleanup has not returned | Inspect live/draining contexts, resource teardown and primary/secondary failures |
| Async application stalls | Blocking call on its event loop | Use async waits/shutdown and offload persistence-enabled sync entry points |

A cleared/non-retained result is not automatically a failed computation. Compare artifact history and `ArtifactPolicy`. A shutdown timeout is not confirmation that worker code was killed. See [failure handling](../runs/failures.md), [capacity](../runs/capacity.md) and [async use](../runs/async.md).
