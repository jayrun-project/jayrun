# Supply configuration

Declare computational parameters with `ConfigField` and supply overrides using a graph-independent `ConfigContext`. Use operational settings for retries, iterations and retention instead.

```python
from jayrun import ConfigContext

# scale and graph come from the complete first-graph example.
configs = ConfigContext({scale.factor: 3})
run = engine.submit(graph, configs=configs, artifacts=artifacts)
```

The [first graph](../../start/first-graph.md) supplies all prerequisites. References are normalized against that graph. A declaration or inspected definition from another graph is rejected even if its name or numeric ID matches.

## Types, defaults and omission

`value_type` must be exactly `bool`, `int`, `float`, `str` or `tuple`. Values use exact types; `True` is not an integer configuration. Floats must be finite, and tuples recursively contain portable immutable values. Mutable lists/dictionaries and custom hashable objects are not configuration values. Use artifacts/resources for richer state, or an immutable declaration such as a string library identifier.

A required field must be supplied and cannot declare a default. An optional field may have a matching default. Omission selects that default. Explicit `None` is allowed for an optional field and represents absence; it is rejected for a required field. Non-None values must match the exact declared type. Submitted configurations become immutable runtime views, so later builder edits do not alter accepted work.

YAML input uses the supported `ConfigContext` loading API and requires the `yaml` extra. External text still undergoes reference and value validation; YAML is not permission to construct arbitrary Python objects. Consult [builder signatures](../../reference/artifacts.md) before choosing keys and load operations.

Configuration also participates in resource reuse and timing-profile selection. Choose timing-relevant fields before confirmation with `graph.select_timing_configs(...)`; this describes which configurations affect learned timings, not a guarantee of runtime prediction accuracy.
