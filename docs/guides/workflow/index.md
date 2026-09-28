# From declaration to execution

A declaration describes reusable computation. A submission supplies values and creates one execution, represented by a ContextRun. This chapter follows that transition without treating a run as another graph definition.

The [lifetime introduction](../../start/data-and-lifetimes.md) explains what changes with each run and what the runtime can reuse. If you have not run Jayrun yet, start with the [complete guided example](../../start/first-graph.md). Then use the two parts below to understand and extend it.

## Follow the lifecycle

| Stage | What you create or do | Read next |
| --- | --- | --- |
| Declare data and computation | Artifact identities, operator fields and resource bindings | [Artifacts](../../model/identity.md), [operators](../graphs/operators.md), [resources](../graphs/resources.md) |
| Connect the declaration | ArtifactFlow and GraphDefinition | [Artifact flow](../../model/flow.md), [construction](../graphs/construction.md) |
| Validate and prepare | Resolve structural/property errors, bind resources and serializers, then confirm | [Validation](../graphs/validation.md), [graph resolutions](../graphs/resolutions.md) |
| Supply values and policy | ArtifactContext, ConfigContext and execution settings | [Configuration](../graphs/configuration.md), [settings](../runs/settings.md) |
| Submit and manage work | Engine returns a ContextRun; wait or request lifecycle changes | [Engine](../runs/engine.md), [ContextRun](../runs/context-run.md) |
| Read the execution result | Check outcome, retained artifacts and reports after finalization | [Results](../runs/context-run.md#results-and-retention), [visualization and reporting](../evidence/plots.md) |

Configuration supplies parameters read by the computation. Settings govern how Jayrun runs it. Their separate guides show where each is passed; neither requires changing the graph's data flow.

```{toctree}
:maxdepth: 1

../graphs/index
../runs/index
```

Once you understand this lifecycle, [component interfaces](../components/index.md) explain what an operator or resource can do while executing. [Visualization and reporting](../evidence/plots.md) then shows how to inspect the declaration and interpret the resulting execution separately.
