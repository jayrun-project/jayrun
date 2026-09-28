# Runtime interface: capabilities and lifetime

Components use the injected `self.runtime` handle. They do not construct an Engine or import a RuntimeInterface implementation to obtain authority. Authority is granted by the application on submission.

| Surface | Ordinary context | Scoped Supervisor | Supervisor() | Controller |
| --- | --- | --- | --- | --- |
| `name`, `engine_id`, `alive` | Available | Available | Available | Available |
| Visible run lists | Empty | Declared graph scope | All other visible live work | All other visible live work |
| Run control through returned handles | No cross-context targets | Scoped targets | Visible targets | Visible targets |
| `wait`, `wait_async` | Shared helpers for supplied authorized handles | Same | Same | Same |
| `events` | PermissionError | Scoped queue | Authority queue | Authority queue |
| `pressure`, `pressures` | Scoped counts/shared runtime facts | Scoped | Broad | Broad |
| Apply a context snapshot | Target authority required | Scoped targets | Authorized targets | Authorized targets |
| Apply a pressure snapshot | Denied | Denied | Available | Available |
| `submit`, `shutdown` | Denied | Denied | Denied | Available |
| `terminal_history` | Denied | Denied | Denied | Available |
| `history` | Denied | Denied | Denied | Granted reader, or None without a grant |

The caller itself is excluded from run lists. An empty list may reflect scope or no unfinished work; it is not proof that an engine is idle. `pressure` exposes scope-filtered context/placement counts together with shared execution/memory facts, so it is not a per-user memory accounting boundary.

`alive` is a cooperative service condition. During graceful shutdown, authority contexts remain alive while ordinary work drains; their final shutdown stage then makes it false and closes their events queue. Ordinary contexts lose it when stopping/aborting/failing/finishing begins; forced shutdown makes it false immediately.

## Lifetime and denial

Runtime-issued handles and borrowed readers recheck authority. After the authority context/source expires, new operations can raise `PermissionError`. Already admitted commands are not necessarily undone by later revocation. Do not retain injected capabilities as global application state.

Use [observe/control](control.md), [Controller submission](controller.md) and [history](history.md) for tasks. The [complete runtime reference](../../interfaces/runtime.md) lists every member and links to source. [Engine/runtime correspondence](correspondence.md) explains shared operations without combining their APIs.
