# Build and confirm a graph

Create artifacts and component declarations, order consumers with `ArtifactFlow`, then prepare a `GraphDefinition`. Use [graph-definition resolutions](resolutions.md) when the intended shape is rejected.

```{literalinclude} ../../_examples/first_graph.py
:language: python
:pyobject: build_graph
```

`entry_flows` identifies flows initialized by submission values. Other consumed artifacts need a producer origin. A produced exit need not have a consumer flow. Each artifact has one flow definition; place its ordered consumers in that flow rather than duplicating the flow for another consumer.

## Input-free and artifact-free work

An input-free producer may head a flow for the artifact it produces. A single operator with no artifact inputs can also stand alone as `ArtifactFlow(operator)`. This is useful for a Controller or a terminal side effect. Do not put an artifact-free flow in `entry_flows`.

The [Controller example](../runtime/controller.md) contains an artifact-free service graph and an input-free producer graph. They do not need a dummy input.

## Preparation order

1. Construct the graph. Structural contradictions can fail here, before a graph object is returned.
2. Bind resources with `graph.bind_resources(mapping)` when needed.
3. Bind any artifact boundary serializers with `graph.bind_serializers(mapping)` and select timing configuration with `graph.select_timing_configs(...)`.
4. Inspect or validate declared properties. `graph.validate()` returns a report without executing code.
5. Call `graph.confirm()` explicitly. Confirmation checks the prepared declaration and seals the graph, including serializer bindings.
6. Register the confirmed graph if the receiving Engine uses a graph registry. Submit native builders directly, or create a `Submission` and call `arguments()` for each run. [Prepare and inspect submission inputs](../runs/engine.md#inspect-inputs-before-starting-an-engine)

For an ordinary local graph without resources or serializers, construction → validation → confirmation is sufficient. A serializer cannot be added after confirmation; prepare the complete boundary first.

Confirmed declarations are reusable. Avoid changing component metadata or configuration defaults after construction. Per-run values belong in builders and settings. Repeated graph occurrences, execution repeats and graph iterations are different tools; see [repeat and iterate](../runs/iteration.md).

Reference: [GraphDefinition and GraphRegistry](../../reference/graphs.md).

## Retrieve or attach an authored flow

An `Artifact` identifies a slot. An `ArtifactDefinition` is the immutable
metadata for that slot in a particular graph. Resolve the latter with
`graph.inspect.artifacts.by_id(0)`. `graph.flow(slot)`, `graph.flow(definition)`
and `graph.flow(0)` retrieve the same authored root row. An output without a
row returns `None`. An explicitly authored row beginning with a zero-input
producer is returned intact. A descriptive name never identifies a slot.

This complete example inserts the same independently authored adjustment on
both sides of a sensor reading. Each insertion has its own configuration.

```python
from jayrun import (
    Artifact, ArtifactContext, ArtifactField, ArtifactFlow, BaseOperator,
    ConfigContext, ConfigField, Engine, GraphDefinition,
)

class Adjust(BaseOperator):
    def __init__(self, *, reading, outputs):
        super().__init__()
        self.reading = ArtifactField()
        self.delta = ConfigField(value_type=int, required=False, default=1)
        self.outputs = (ArtifactField(),)

    def execute(self):
        return self.reading.value + self.delta.value

sensor = Artifact()
center = ArtifactFlow(Adjust(reading=sensor, outputs=(sensor,)), artifact=sensor)
original = GraphDefinition(center, entry_flows=center)
original.confirm()

sample = Artifact()
adjust = ArtifactFlow(Adjust(reading=sample, outputs=(sample,)), artifact=sample)
extended = original.attach(adjust, sensor, position="start").attach(adjust, sensor)
first, middle, last = extended.flow(sensor).operators
extended.confirm()
with Engine() as engine:
    run = engine.submit(extended, ArtifactContext({sensor: 10}),
                        ConfigContext({first.delta: 2, last.delta: 3}))
    run.wait(timeout=5)
    assert run.artifact(sensor).value == 16
```

The example works because each adjustment consumes and regenerates the same
slot. An operator that consumes the final value without regenerating it ends
that chain. An operator producing a different slot needs an explicit row for
consumers of that slot.

Each attachment returns an unconfirmed graph, including when the receiver is
confirmed. Graph construction, validation, compilation and execution follow
their ordinary paths. Each call creates local ports for the imported native
operator contract. The returned row exposes each imported use as a native
`BaseOperator` with its own fields. Its inspection and declaration report
identify the authored implementation. Repeating a declaration in a row runs
it several times with the same fields. Separate calls create independent fields. Artifact bindings outside the explicit
translation keep the original Python identities, including internal artifacts.
When reusing a procedure, explicitly translate any private slots that should
be independent.

Use `attach_many((flow, destination, position), ...)` when one operator occurs
in multiple input rows. The triples are one operation. A partial join is rejected
before publication. All prefixes, then the receiving row, then all suffixes
appear in argument order within their group. A destination of `None` keeps the
source identity and can introduce an additional row or artifact-free root.
Use `translations` for secondary ports, especially outputs that supply graph
entries. Use `entry_artifacts` for the entire new set of caller-supplied slots.
Definitions and IDs refer to the receiver. New slots are addressed by their
actual Artifact objects.

Receiving resource bindings and explicit timing selections carry over. Select
resources for imported fields in the new graph. A flow has no resource or
serializer selection of its own. If existing boundary serializers cover the
new boundary, surviving selections carry over. Otherwise pass all outer codecs
in `serializers`, or pass `serializers={}` to explicitly drop codec coverage.
A former exit consumed by the attachment can become intermediate. Feedback,
retention, timing and failures belong to the resulting context.

The [complete sensor example](../../_examples/attach_flows.py) attaches
preparation to two previously external entries, measures two former exits and
runs with a bound calibration resource.
