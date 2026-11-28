# Engine

The application owns this lifecycle surface. Components use the separate [self.runtime reference](../interfaces/runtime.md). See [correspondence](../guides/runtime/correspondence.md) for equivalent operations and differences, and [ContextRun](context-run.md) for returned handles.

```{eval-rst}
.. autoclass:: jayrun.Engine
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.EngineState
   :members:
   :undoc-members:
```

```{eval-rst}
.. autoclass:: jayrun.RuntimeActivity
   :members:
   :undoc-members:
```

```{eval-rst}
.. autoclass:: jayrun.Supervisor
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.Controller
   :members:
```

## Reusable submission inputs

```{eval-rst}
.. autoclass:: jayrun.Submission
   :members:
```

Construction requires a confirmed graph and accepts the same artifact and config builders as direct submission. Native graph-relative errors are raised immediately. The object retains winning bindings and shares the underlying artifact payloads by reference. The graph, requested settings and authority are preserved in each argument dictionary. The config builder contains explicit overrides, including explicit null and overrides equal to a default. Each admission checks its inputs and the live authority again.

`inspect()` returns a detached dictionary. Entry rows give graph-local IDs and flag a supplied missing value. Construction rejects absent required bindings. Config rows are indexed by config ID and mark values as explicit, default or omitted. Integers and floats use tagged hexadecimal strings. Tuples use a tagged array. Policy counters larger than 53 bits use the same exact integer tag. Resource rows refer to those same config IDs. Selection IDs group fields bound to the same resource or serializer instance within this graph. The diagnostics retain native edge status and separate graph-iteration and operator-repeat mismatches.

`requested_settings` preserves omission. `graph_settings` resolves exit retention and graph-independent defaults. Inherited retry settings remain open. Pass `engine_settings=` to project the combined context policy in `engine_scenario`. The admitting Engine determines its actual policy, registration, capacity, placement and authority.

Sensitive configuration names are redacted automatically. For additional redaction, pass a tuple of paths made of dictionary keys and sequence indices. For example, `redact=(("configs", 2, "value"),)` hides config 2. Append `"tuple", 0` to that path to hide its first tuple member. A path of `()` hides the whole report. Exact config values follow native bounds. Display labels are bounded and inspection raises `ValueError` if its compact JSON exceeds 32 MiB.
