# Error and symptom index

Use the distinctive fragment or observed symptom to reach a correction. Dynamic IDs and object representations vary; they are not stable message contracts. An error at construction cannot be diagnosed through a run that was never created.

| Search term / symptom | Owning guide |
| --- | --- |
| Fan-in, fan-out, unavailable artifacts, cannot make further progress | [Explicit graph resolutions](../guides/graphs/resolutions.md) |
| Multiple flows, missing origin, conflicting consumer order | [Graph/component errors](../guides/problems/graphs.md) |
| Duplicate input/output binding, required outputs argument, output count | [Operator contracts](../guides/graphs/operators.md#return-positions-and-tuple-payloads) |
| Missing runtime attribute, reserved name, direct base class | [Operator declarations](../guides/graphs/operators.md#declaration-rules) |
| Type/shape/device property mismatch, unknown compatibility | [Validation](../guides/graphs/validation.md) |
| Graph must be confirmed, resources already bound, graph is sealed | [Preparation order](../guides/graphs/construction.md#preparation-order) |
| Unknown artifact/config reference, missing required value, exact type | [Submission/configuration](../guides/problems/submission.md) |
| Config nesting, nodes, accounted bytes, unsupported type | [Configuration](../guides/graphs/configuration.md) and [codecs](serialization.md) |
| Serializer coverage, occupied graph identity, requirement conflict | [Registration](../guides/graphs/registration.md) |
| missing_input, SKIPPED, conditional branch never runs | [Conditional routing](../guides/graphs/resolutions.md#conditional-routing-and-convergence) |
| ContextNotTerminatedError, wait returned FAILED, timeout | [ContextRun](../guides/runs/context-run.md) |
| Placement impossible/unavailable, changed request sequence | [Execution/placement problems](../guides/problems/execution.md) |
| ContextHistoryLimitError, OwnershipCapacityError, record limit | [Capacity and retention](../guides/runs/capacity.md) |
| PermissionError, invisible target, expired capability | [Authority problems](../guides/problems/authority.md) |
| ObserverOverflowError, missing terminal summary, cursor gap | [Events](../guides/evidence/progress.md) and [terminal history](../guides/runtime/history.md) |
| Storage capacity/schema/value error, missing details, flush failure | [Persistence](../guides/evidence/persistence.md) |
| shutdown timeout, repeated side effect, async loop stall | [Failure/shutdown](../guides/runs/failures.md) and [async use](../guides/runs/async.md) |

For issues not covered by these categories, prepare a [minimal reproduction](../guides/problems/reproduction.md).
