# Authority, observation and persistence problems

| Error or symptom | Cause | Correction |
| --- | --- | --- |
| Empty runtime run lists | No supervising scope, excluded caller, or no live targets | Check the submission grant and graph identity; do not infer engine idleness |
| PermissionError on submit/shutdown/terminal history | Not a Controller | Have the owner grant Controller where justified; Supervisor() is not equivalent |
| PermissionError on pressure apply | Scope is restricted | Use an authorized unrestricted supervisor/controller or application owner |
| `runtime.history is None` | Controller has no reader grant | Pass an explicit DatabaseReader via Controller(history=...) |
| Expired reader/handle | Controller/source lifecycle ended | Obtain a new authorized capability; IDs cannot recreate a grant |
| ObserverOverflowError | Consumer fell behind bounded event queue | Report the observation gap and reconcile authorized snapshots/terminal summaries |
| Missing terminal entries | Retention, byte bounds, disabled window or old cursor | Check page.gap and sequence bounds; do not claim full event coverage |
| History header exists but detail is missing | Detail pressure/retention/capture gap | Inspect availability/status; a header is not proof of full-report storage |
| Flush raises despite completed computation | Persistence settlement failed | Diagnose storage/capacity and preserve explicit gaps |
| Schema/value/capacity storage error | Incompatible schema, malformed value or bounded admission | Use the relevant maintenance/codec/capacity remedy rather than blind retry |

The application must grant and protect history scope. Do not pass an all-session reader merely to make an authorization error disappear. See [runtime capabilities](../runtime/capabilities.md), [history](../runtime/history.md) and [persistence](../evidence/persistence.md).
