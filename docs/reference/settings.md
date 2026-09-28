# Settings, policies, defaults and limits

Settings are keyword-only validated values. Context retry policy inherits the Engine policy when None; context artifact/record/iteration policy belongs to the context. See [capacity and retention](../guides/runs/capacity.md) and [failure mode](../guides/runs/failures.md).

## Limit semantics

| Setting | Owner / unit | Default | None / zero | Behavior |
| --- | --- | --- | --- | --- |
| max_workers | Engine worker threads | None (runtime default) | None allowed; zero rejected | Bounds concurrent worker capacity |
| max_tasks | Engine dispatched tasks | None (runtime default) | None allowed; zero rejected | Bounds task dispatch |
| max_iterations | Context graph iterations | 1 | None unbounded; zero rejected | Stop prevents another iteration |
| max_repeats | Additional executions per step session | None | None uncapped; zero disables repeats | Caps repeat requests |
| RetryPolicy.max_attempts | Attempts including initial invocation | 1 | None/zero rejected | Eligible failures retry up to this count |
| record_history_limit | Retained records per key | 64 | None full history; zero rejected | Prunes older records for that key |
| record_max_keys | Retained/pending distinct record keys | 256 | Positive integer required | Rejects excess before queueing |
| record_max_value_bytes | Accounted bytes for one value | 65,536 | Positive integer; at most 64 MiB | Rejects excess before queueing |
| record_max_total_bytes | Retained plus pending accounted bytes | 8,388,608 | Positive integer required | Rejects excess before queueing |
| context_history_admission_limit | History-producing entries/admissions per context | None | None unlimited; zero rejected | Further admission fails; accepted evidence and drainage remain |
| remote_context_id_limit | Cumulative distinct remote context IDs per incarnation | None | None unlimited; zero rejected | Rejects additional identities at capacity |
| terminal_history_limit | Retained terminal summaries | 1,024 | Zero disables; None rejected | Eviction/loss is exposed as cursor gaps |
| terminal_history_max_bytes | Retained terminal summary bytes | 1,048,576 | Positive integer required | Bounds the summary window |
| retained_artifacts | Context exit selection | None (all exits) | Empty tuple retains none | Releases unselected final values |
| release_entry_artifacts | Context entry ownership policy | False | Boolean | Releases framework entry references, not external ones |

Record byte accounting uses 16 bytes per node plus UTF-8 strings and integer magnitude bytes. Configuration admission separately bounds each value to 1 MiB accounted bytes, depth 64 and 16,384 nodes. These are not estimates of the application's total heap or device memory.

Settings and retry/recording/routing enums are validated at construction. The signatures and member descriptions below give the exact current fields. Database limits/retention have separate ownership and defaults in the [persistence reference](persistence.md).

```{eval-rst}
.. autoclass:: jayrun.settings.ArtifactPolicy
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.settings.ContextSettings
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.settings.EngineSettings
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.settings.FailureMode
   :members:
   :undoc-members:
```

```{eval-rst}
.. autoclass:: jayrun.settings.RetryPolicy
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.settings.RoutingMode
   :members:
   :undoc-members:
```

```{eval-rst}
.. autoclass:: jayrun.settings.RuntimeDevice
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.settings.RecordingMode
   :members:
   :undoc-members:
```
