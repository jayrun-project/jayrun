# Handle failures, retries and shutdown

First identify where failure occurred. A rejected public call, a failed execution and an Engine fault need different recovery actions.

| Boundary | What to inspect | Usual next action |
| --- | --- | --- |
| Construction/preparation | Raised exception and graph declaration | Correct the declaration; no run exists yet |
| Submission call | Raised validation/type/reference error | Fix builders/settings; do not expect a returned run |
| Returned rejected run | State and report | Correct admission/requirements before resubmission |
| Execution failure | `run.report.data.failure` and step/attempt evidence | Fix computation or apply a deliberate retry policy |
| Engine/runtime failure | `engine.failure`, secondary/cleanup failures | Diagnose ownership/runtime fault and complete drainage |
| Persistence failure | Database status, gaps and flush result | Restore storage/capacity and handle missing evidence explicitly |

## Retry policy

`RetryPolicy(max_attempts=N, retry_on=(ExceptionType,))` counts the initial attempt. The default is one attempt. If `N > 1` and no types are supplied, all `Exception` subclasses are eligible. A context can override the Engine's retry policy.

Retries do not roll back Python object mutation, HTTP calls, messages or database writes performed by the application. Use idempotency keys, transactional effects or domain compensation. Placement waits can also restart invocation before a normal result; place reservation calls before effects.

## FailureMode

`EngineSettings.failure_mode` governs ordinary execution failures and engine-owned persistence failure. `CONTINUE` is the default; it can preserve computation while reporting explicit history gaps. `FAIL_FAST` initiates engine failure handling. A standalone Database remains strict, and explicit flush reports failed persistence even when the Engine policy permits computation to continue. A history-write failure is not retroactive proof that an already completed operator failed.

## Shutdown

Application owners call `shutdown()` or `shutdown_async()`. Graceful shutdown stops future iterations, settles ordinary work and then closes authority contexts. Controller/Supervisor loops should observe `self.runtime.alive` or drain `self.runtime.events` to closure. Forced shutdown requests abortion; it is not process isolation or guaranteed interruption of arbitrary blocking native code.

Timeouts bound how long the caller waits. A shutdown timeout does not prove all work was forcibly killed or all external resources released. Check primary and cleanup failures; preserve the first causal failure when reporting subsequent errors. Application-owned setup must clean partial allocations that never reached a successful resource return.

See [minimal reproduction](../problems/reproduction.md) and [supported limits](../../reference/limits.md).
