```{eval-rst}
.. meta::
   :description: Declare a typed ConfigField, pass per-run values with ConfigContext, and round-trip the graph's configuration as YAML in Jayrun.
```

(supply-configuration)=
# Configure a graph with ConfigField and ConfigContext

Declare computational parameters with `ConfigField` and supply overrides using a graph-independent `ConfigContext`. Use operational settings for retries, iterations and retention instead.

Save [first_graph.py](../../_examples/first_graph.py) beside this program so it can import the `Scale` graph.

```python
from first_graph import build_graph
from jayrun import ArtifactContext, ConfigContext, Engine

graph, source, result, scale = build_graph()
configs = ConfigContext({scale.factor: 3})
with Engine() as engine:
    run = engine.submit(graph, artifacts=ArtifactContext({source: 7}), configs=configs)
    run.wait(timeout=5)
    assert run.artifact(result).value == 21
```

The [first graph](../../start/first-graph.md) supplies all prerequisites. References are normalized against that graph. A declaration or inspected definition from another graph is rejected even if its name or numeric ID matches.

## Types, defaults and omission

`value_type` must be exactly `bool`, `int`, `float`, `str` or `tuple`. Values use exact types; `True` is not an integer configuration. Floats must be finite, and tuples recursively contain portable immutable values. Mutable lists/dictionaries and custom hashable objects are not configuration values. Use artifacts/resources for richer state, or an immutable declaration such as a string library identifier.

A required field must be supplied and cannot declare a default. An optional field may have a matching default. Omission selects that default. Explicit `None` is allowed for an optional field and represents absence; it is rejected for a required field. Non-None values must match the exact declared type. Submitted configurations become immutable runtime views, so later builder edits do not alter accepted work.

## Save and load configuration as YAML

With the `yaml` extra installed, `to_yaml(graph)` returns YAML text. Pass that text and the same graph to `load_yaml` on a mutable builder. The loader resolves graph-local field IDs and preserves existing values for fields absent from the document.

```python
text = configs.to_yaml(graph)
restored = ConfigContext()
restored.load_yaml(text, graph)
assert restored.get(scale.factor).value == 3
```

See {py:class}`~jayrun.ConfigContext` for accepted keys and loading errors. Choose timing-relevant fields before confirmation with `graph.select_timing_configs(...)`. The [resource lifetime example](../../model/lifetime.md#compare-three-submissions) shows how resource configuration affects reuse.
