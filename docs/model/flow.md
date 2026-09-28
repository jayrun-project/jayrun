# Artifact flow and graph structure

An `ArtifactFlow` orders consumers of one artifact. Consumption makes that active value unavailable to later consumers unless a step regenerates it. Jayrun does not infer a broadcast from multiple uses of the same identity.

An operator may consume an artifact and output the same artifact to regenerate it for a later consumer or the next iteration. It may instead output a different identity, leaving the consumed flow ended. Independent branches use distinct artifacts. A join declares separate inputs and is aligned across their consumer flows.

## Follow one artifact through two steps

Suppose `text` starts as `"hello"`. AddMark consumes that value and produces `"hello!"` back to the same artifact. Uppercase then consumes the new value and produces `"HELLO!"`. The flow is ordered, so Uppercase reads the regenerated value rather than the original one.

| Moment | Current text value | What makes the next step possible? |
| --- | --- | --- |
| Submission | `"hello"` | The entry flow receives an input |
| After AddMark | `"hello!"` | AddMark outputs to the same artifact it consumed |
| After Uppercase | `"HELLO!"` | The final available value is an exit |

```{literalinclude} ../_examples/flow.py
:language: python
```

If AddMark consumed `text` but produced only a different artifact, the old text value would no longer be available for Uppercase. To continue the chain, regenerate text as above; to create independent branches, use separate output artifacts through a [splitter](../guides/graphs/resolutions.md#fan-out-split-into-distinct-artifacts).

## Entry, intermediate and exit roles

| Role | Source or destination |
| --- | --- |
| Entry artifact | Submission supplies its initial value through an entry flow |
| Intermediate artifact | A producer supplies a value consumed later |
| Unflowed output | Produced without a consumer flow; can be an exit |
| Exit artifact | Final available value eligible for terminal retention |

An input-free operator can start a graph. A one-operator artifact-free flow can express a service or side effect. An artifact-free flow is not an entry flow because it has no submitted artifact. Declaring input fields but disconnecting all of them is a different, rejected declaration.

## Absence is data-flow control

A connected input value of `None` causes its operator to be skipped. This also skips resource setup for that step and can propagate to later consumers. A value of `0`, `False`, an empty string or an empty collection remains a present value. A field declared `required=False` allows explicit disconnection; a connected optional field whose value is `None` still causes skipping.

See [graph-definition resolutions](../guides/graphs/resolutions.md) for complete split/join and conditional-route examples. See [retention](../guides/runs/capacity.md) for what survives after a flow ends.
