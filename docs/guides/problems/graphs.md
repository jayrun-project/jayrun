# Graph and component errors

Diagnose declarations before execution. A construction exception can occur before a GraphDefinition is returned; a property mismatch can leave an inspectable graph that cannot be confirmed.

| Message or symptom | Cause / stage | Correction |
| --- | --- | --- |
| Wrong base class or multiple declaration bases | Component class definition | Directly subclass BaseOperator/BaseResource; move shared logic into helpers |
| Missing input argument, including an optional field | Operator binding | Pass its Artifact or explicit None; do not confuse optional with implicit binding |
| No connected inputs despite declared input fields | Operator binding | Connect at least one declared input, or declare a genuinely input-free root |
| Output count does not match declared fields | Constructor binding or execute return | Match tuple length; unbound output slots still count |
| Duplicate artifact bindings | One input/output group repeats an identity | Give each position a distinct artifact or simplify the declaration |
| Multiple flows for one artifact | Graph construction | Consolidate ordered consumers in one ArtifactFlow |
| Fan-in, unavailable artifacts, alignment cannot progress | Competing producers, reuse after consumption or conflicting flow order | Use explicit split/copy and join, regeneration, or aligned dependency order |
| Missing/unavailable origin | Input has no entry or producer | Add the correct entry flow or input-free producer |
| Graph is already confirmed / resources already bound | Repeated or late preparation mutation | Finish resource/timing setup once before confirm; build a new declaration when needed |
| Property mismatch at confirm | Known producer/consumer incompatibility | Correct properties or add an explicit conversion |
| Runtime attribute is missing | Hidden constructor state is absent from proxy | Declare config/artifact/resource state or call an ordinary helper |

See [graph-definition resolutions](../graphs/resolutions.md) for complete corrected shapes and [operator contracts](../graphs/operators.md) for return values. Do not repair a mismatch by deleting useful property declarations or use retries for a deterministic construction error.
