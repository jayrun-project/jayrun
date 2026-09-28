# From artifacts to a completed run

We will multiply `7` by `3`, inspect the graph, run it, and read `21`. The example is deliberately small: it lets you follow what is declared once and what changes on each submission. [Install Jayrun](installation.md) before starting. The preceding [lifetime guide](data-and-lifetimes.md) distinguishes artifact values, per-run configuration and reusable resources; this first program needs only artifacts and configuration.

## 1. Declare the data positions

```python
from jayrun import Artifact

source = Artifact(name="source")
result = Artifact(name="result")
```

These are identities, not containers holding `7` and `21`. They let the graph say “this is the value that Scale consumes” and “this is the result it produces.” Submission supplies the actual input later. Names label the diagram; creating another Artifact with the same name would create a different identity.

## 2. Declare the operator

An operator describes its inputs, computational parameters and outputs, then implements the calculation:

```{literalinclude} ../_examples/first_graph.py
:language: python
:pyobject: Scale
```

`self.source = ArtifactField()` declares an input position. `self.outputs` declares one output position. When you construct `Scale(source=source, outputs=(result,))`, Jayrun matches the constructor argument `source` to the field named `source`, and binds the output tuple by position. That is why the constructor does not manually assign the `source` argument to the field.

The constructor runs while declaring the graph. Later, Jayrun invokes `execute()` on an execution object containing the bound runtime values. `self.source.value` is then `7`, and `self.factor.value` is `3`. Returning a number publishes it to the bound result artifact.

`self.context` is another handle supplied by Jayrun during execution. Here, `record("scaled", result)` attaches a small application value to this run so we can read it afterward. You do not instantiate or assign `self.context`. The [component-interface chapter](../guides/components/index.md) explains all four handles and their use in operators and resources.

## 3. Connect an artifact flow

```python
from jayrun import ArtifactFlow, GraphDefinition

scale = Scale(source=source, outputs=(result,))
flow = ArtifactFlow(scale, artifact=source)
graph = GraphDefinition(flow, entry_flows=flow)
```

The flow orders consumers of `source`; here there is just one. Marking it as an entry flow says that the application supplies its initial value. `result` has a producer and no later consumer, so it becomes an exit that we can retrieve after execution.

A flow follows an artifact, rather than being a general list of function calls. For a larger graph, an operator consuming two artifacts appears in both relevant flows. See [artifact flow](../model/flow.md) before adding branches.

## 4. Validate, inspect and confirm

```python
validation = graph.validate()
assert validation.valid
graph.plot.save("scale-graph.html")
graph.confirm()
```

Construction has already checked whether the declared flows can fit together. Validation checks declared input/output properties. Our fields declare no type properties, so validation cannot establish their type compatibility; it simply finds no known mismatch. [Validation](../guides/graphs/validation.md) adds an explicit type check and shows a failure.

The diagram below is embedded in this page. Use **Fit** to center it and select the operator to inspect its fields. It describes the declaration; nothing has executed yet.

```{raw} html
<iframe class="graph-viewer" src="../_static/first_graph.html" title="Scale graph before execution" loading="lazy" allowfullscreen></iframe>
```


Confirmation completes preparation and seals the graph. Bind any resources, serializers and timing selections **before** `confirm()`. The graph can then be reused for multiple submissions. See [preparation order](../guides/graphs/construction.md#preparation-order).

## 5. Supply values and submit

```python
from jayrun import ArtifactContext, ConfigContext, Engine
from jayrun.context import ContextState

artifacts = ArtifactContext({source: 7})
configs = ConfigContext({scale.factor: 3})

with Engine() as engine:
    run = engine.submit(graph, artifacts, configs)
    run.wait(timeout=5)
    if run.state is not ContextState.FINISHED:
        raise RuntimeError(str(run.report.data.failure))
    print(run.artifact(result).value)       # 21
    print(run.records("scaled")[-1].value) # 21
```

`ArtifactContext` supplies data to entry artifacts. `ConfigContext` supplies the factor to the operator's declared configuration field. The Engine starts on entering `with`, and shuts down when that block ends.

Configuration answers **what this calculation should do**. Settings answer **how Jayrun should run it**: for example, a ContextSettings value can set an iteration limit, while EngineSettings can set worker capacity. This program uses the defaults. Read [execution settings](../guides/runs/settings.md) when you need to change them; they are not fields read through `self.factor`.

## 6. Understand the returned run

Submission returns a `ContextRun` immediately. It is your handle to this particular execution: its state, control operations, records and eventual result. It is separate from the reusable graph and from the Engine that hosts it.

`wait(timeout=5)` waits up to five seconds for finalization. Once it returns, reports and retained results are available. It does not assert success, which is why we check `run.state`. If waiting times out, the work may still be running; [ContextRun and lifecycle control](../guides/runs/context-run.md) explains what to do next.

After successful finalization, `run.artifact(result).value` reads the retained exit. `run.records("scaled")` reads committed application records. The graph and record express different things: the artifact is the computation's output; the record is a value we chose to keep for inspection.

## 7. See what executed

With a finalized `run`, `run.plot.save("scale-run.html")` creates a run visualization. It opens an execution workspace with outcome, iteration counts and elapsed time above the graph. The operator shows its recorded outcome, execution count and active duration. Open **Summary**, **Records** or **Report** to explore the same run through different views.

```{raw} html
<iframe class="graph-viewer" data-kind="run" src="../_static/first_run.html" title="Completed Scale run with summary, records and report tabs" loading="lazy" allowfullscreen></iframe>
```


The [visualization and reporting chapter](../guides/evidence/plots.md) separates declaration inspection from execution results. Its [completed-run guide](../guides/visualization/runs.md) explains the tabs, timing and skipped routes. Holding `run` keeps its retained results available after the Engine closes; release the handle when you no longer need them.

## Complete runnable program

Save this as `first_graph.py` and run `python first_graph.py`. It prints `21` and checks that the record also contains `21`.

```{literalinclude} ../_examples/first_graph.py
:language: python
```

[Download the program](../_examples/first_graph.py). You have now followed the complete sequence: declare artifacts, bind an operator, construct flows, validate and confirm, submit values, then inspect a ContextRun.

Continue with [operators](../guides/graphs/operators.md), [graph-definition resolutions](../guides/graphs/resolutions.md), or [settings](../guides/runs/settings.md), depending on what your computation needs next.
