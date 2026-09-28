# Write an operator

Define an operator by directly subclassing `BaseOperator`, declaring fields in `__init__`, and implementing synchronous `execute()` or `async def execute()`. The constructor receives bindings; Jayrun replaces declared fields with runtime `Data` values on the invocation proxy.

```{literalinclude} ../../_examples/first_graph.py
:language: python
:pyobject: Scale
```

This class is used by the [complete first graph](../../start/first-graph.md). Its factor is a declared configuration field, not hidden constructor state.

## Bind declarations, read runtime values

Construct the class with artifact identities:

```python
scale = Scale(source=source, outputs=(result,))
```

Jayrun matches the `source` constructor argument to the ArtifactField declared as `self.source`. It binds the `outputs` argument to the fields in `self.outputs` by position. The constructor's role is to declare the fields; the framework performs their artifact binding. Configuration fields are different: `scale.factor` is a configuration key that you use later in `ConfigContext({scale.factor: 3})`.

When Jayrun invokes execute, `self.source` and `self.factor` hold runtime Data wrappers. Read `.value` for the payload. The returned value is assigned to `result`; execute does not need the Artifact object itself. See [component interfaces](../components/index.md) for the execution object's other members and the resource setup/teardown distinction.

## Declaration rules

Declare input `ArtifactField`s as attributes and output fields as the `self.outputs` tuple. Bind each input explicitly, including `optional_input=None`. The `outputs=` binding is a tuple with the same length as the declaration. A declared input group must have at least one connected artifact; a genuinely input-free operator declares no artifact inputs. Duplicate artifact bindings within one input or output group are rejected.

Direct inheritance is required; use ordinary helpers for shared business logic. Runtime interface names such as `execution`, `context`, `runtime` and `placement` are reserved. Constructor-assigned arbitrary attributes and methods on the declaration are not an implicit mutable runtime object. Keep computation in `execute()` or ordinary helpers, and carry state through declared artifacts/resources/configuration.

## Return positions and tuple payloads

| Declaration/binding | Return contract |
| --- | --- |
| One declared output | Return one value or a one-element output tuple |
| Two declared outputs | Return `(left_value, right_value)` |
| `outputs=(artifact, None)` | Still return two positions; the unbound position is discarded |
| All declared outputs unbound | Return all declared positions; no artifact is published |
| `self.outputs = ()` | Return `None` or `()` |

A bare tuple represents output positions. To produce one tuple-valued artifact, return `Data(value=(a, b))` or `((a, b),)`. Returned `Data` retains its value/placement semantics.

A connected output whose **value** is `None` makes that route absent. This differs from a slot bound to no artifact. A consumer with any connected input value of `None` is skipped even if that field has `required=False`. See [conditional routing](resolutions.md#conditional-routing-and-convergence).

A terminal operator may have no outputs and perform a side effect. Define its retry/idempotency behavior explicitly; failure cannot undo an external write. See [failure handling](../runs/failures.md).
