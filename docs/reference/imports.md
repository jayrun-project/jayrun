# Public import map and glossary

Use public namespaces below. `jayrun.core` and `jayrun.engine` contain implementation modules; source links may lead there, but application imports should use the supported facades.

| Namespace | Purpose | Reference |
| --- | --- | --- |
| `jayrun` | Graphs, components, builders, Engine and authority | [Artifacts](artifacts.md), [components](components.md), [graphs](graphs.md), [Engine](engine.md) |
| `jayrun.context` | Runs, states, records, reports, events and snapshots | [Runs](context-run.md), [evidence values](records.md) |
| `jayrun.settings` | Engine/context policy and runtime devices | [Settings](settings.md) |
| `jayrun.inspection`, `jayrun.registry` | Graph-local definitions and registry inspection | [Inspection](inspection.md), [graphs](graphs.md) |
| `jayrun.validation`, `jayrun.properties` | Declarative compatibility and artifact properties | [Inspection/validation](inspection.md) |
| `jayrun.placement` | Placement values and backend/device enums | [Placement](placement.md) |
| `jayrun.persistence` | Database, readers, queries, limits and errors | [Persistence](persistence.md) |
| `jayrun.serialization` | Portable config/record codecs | [Serialization](serialization.md) |
| `jayrun.visualization`, `jayrun.dashboard` | Rendering and prepared dashboard graphs | [Visualization](visualization.md) |

`ContextHistoryEntry` exists in both `jayrun.context` (lifecycle evidence) and `jayrun.persistence` (stored entry). `Backend` also has different placement and storage meanings. Qualify or alias these imports when combined.

## Vocabulary

| Term | Meaning |
| --- | --- |
| Declaration | Reusable graph/component structure, separate from submission values |
| Context / run | One logical submitted execution and its stable ContextRun handle |
| Iteration | One traversal of the declared graph |
| Execution / repeat | An operator invocation within its step session / another such execution |
| Attempt | One try within retry policy |
| Request | Accepted lifecycle intent, distinct from committed state |
| Finalization | Terminal evidence and retained results are ready |
| Flush | Persistence settlement, distinct from context finalization |
| Entry / exit | Submitted initial artifact / final artifact eligible for retention |
| Unbound slot | Declared output position with no Artifact binding; still counts toward return arity |
| Absent route | Connected artifact value is None; consumers skip |
| Authority | Scoped capability granted at submission, with a lifetime |
| Remote shadow | Local view of a context owned for execution elsewhere |

API signatures below are generated from this checkout. The `[source]` links open implementation files in the [public repository](https://github.com/jayrun-project/jayrun); they are not recommendations to import private modules. Tutorial source/notebook links target the same repository.
