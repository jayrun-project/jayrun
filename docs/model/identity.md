# Artifacts and runtime data

An Artifact identifies a value's place in a computation. It does not hold the current value. This lets you submit the same graph with different inputs without rebuilding its structure.

```python
from jayrun import Artifact, ArtifactContext

image = Artifact(name="image")
first_request = ArtifactContext({image: b"first image bytes"})
second_request = ArtifactContext({image: b"second image bytes"})
```

Both builders refer to the same declared input, but supply different values. When submitted against a graph that uses `image` as an entry, each run receives its own submission view. Payload objects are not automatically deep-copied; the application still decides whether sharing a mutable object is safe.

## From declaration to result

| Object | What it represents | Where you use it |
| --- | --- | --- |
| `Artifact` | A data identity in the graph | Graph construction and submission keys |
| `ArtifactField` | An operator's input/output position | Component constructor |
| `Data` | A runtime value and its placement | Operator/resource hooks |
| `ArtifactContext` | Input values for a submission | Application code before submit |
| `ArtifactResult` | A finalized artifact's data and history | `run.artifact(artifact)` |

Inside `execute()`, a connected input field is replaced by a Data wrapper. Read its payload through `self.image.value`. Return a raw value for an ordinary CPU output, or return `Data(value=payload, placement=placement)` when carrying explicit placement information. [Operator bindings](../guides/graphs/operators.md) explains how the declared field becomes that runtime value.

## Consumption and retained results

The artifact identity remains part of the graph while its runtime value can change or become unavailable. A consumer takes the active value; returning an output publishes a new value to its bound artifact. Returning to the same identity regenerates that flow. A later consumer cannot assume the earlier value still exists after consumption.

At finalization, `ArtifactPolicy` determines which exit values remain available through `run.artifact(...)`. It does not save every intermediate. Payload objects are not deep-copied or destroyed on behalf of other Python owners. The [lifetime introduction](../start/data-and-lifetimes.md) compares this behavior with fixed configuration and cached resources.

## Identity is not the display name

Two `Artifact(name="image")` objects are distinct. Reuse the same declaration object wherever you mean the same artifact. Graph inspection also supplies graph-local definitions and numeric IDs; those references belong to the graph that produced them.

Prefer declaration objects in ordinary application code. Use [inspection](../guides/visualization/inspection.md) when a generic tool needs to discover fields. Portable graph identities are introduced later in [registration](../guides/graphs/registration.md).
