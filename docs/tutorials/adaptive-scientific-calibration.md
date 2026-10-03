```{eval-rst}
.. meta::
   :description: Run iterative NumPy heat-diffusion calibration with Jayrun. Reuse problem data, manage per-trial state and isolate failed trials.
```

(tutorial-adaptive-scientific-calibration)=
# Adaptive Scientific Calibration

Estimate a positive diffusivity by matching a one-dimensional heat simulation to known observations. You should know NumPy arrays; the notebook explains the numerical objective. Learn how shared problem data, per-trial state, contained failures, and application checkpoints fit an adaptive campaign.

## Run it

Follow [tutorial setup](index.md#prepare-your-environment), then run from the repository root:

```bash
python -m tutorials.heat_calibration --output heat_results
```

Open `tutorials/07_heat_calibration.ipynb` for the guided lesson. The Python snippets below are consecutive notebook cells: run them in Jupyter with top-level `await`. For a terminal run, use the module command above.

## 1. Understand the objective

The initial temperature is sin(pi*x) on x in [0, 1], with zero boundary values. Analytic observations at time 0.1 use diffusivity 0.17. For each candidate, the solver advances to that horizon; misfit is mean squared error against those observations. Smaller misfit is better. Numerical discretization means the best fitted value need not equal 0.17 exactly.

The explicit Euler step uses dt <= 0.4*dx^2/diffusivity. Smaller cells or larger diffusivity require shorter time steps. ProblemResource holds read-only grid/observations, while each trial has its own changing SimulationState.

<!-- notebook: 07_heat_calibration.ipynb#inspect-problem -->
```python
import asyncio
import inspect
import tempfile
import numpy as np
from pathlib import Path
from jayrun import ArtifactContext, Engine
from jayrun.context import ContextState
from jayrun.settings import ContextSettings
from tutorials import heat_calibration as lesson

problem = lesson.make_problem()
print("Cells / horizon:", len(problem.x), problem.horizon)
print(inspect.getsource(lesson.AdvanceSimulation))
```

## 2. Advance one trial through graph iterations

Each invocation runs a block of numerical steps and outputs its state again. max_iterations=None allows repetition until the operator requests Stop at the horizon. Compare that graph result with the direct numerical loop. A matching result checks integration; the analytic observations provide a separate numerical reference.

<!-- notebook: 07_heat_calibration.ipynb#one-trial -->
```python
def run_one_trial(diffusivity):
    graph, state = lesson.build_graph()
    with Engine() as engine:
        run = engine.submit(graph, ArtifactContext({state: lesson.initial_state(problem, diffusivity)}),
                            settings=ContextSettings(max_iterations=None, record_history_limit=4))
        run.wait(timeout=30)
        if run.state is not ContextState.FINISHED:
            raise RuntimeError(str(run.report.data.failure))
        return run.artifact(state).value

trial = await asyncio.to_thread(run_one_trial, 0.17)
reference = lesson.initial_state(problem, 0.17)
while reference.time < problem.horizon - 1e-14:
    lesson.advance(reference, problem)
np.testing.assert_allclose(trial.values, reference.values, atol=1e-12, rtol=0)
print("Time / steps / misfit:", trial.time, trial.steps, trial.misfit)
```

## 3. Refine a campaign and inspect every outcome

The application starts candidates 0.1, 0.2, 0.3, and -0.1. The negative value deliberately fails. It keeps the best successful value and tries two smaller neighborhoods. Four initial candidates and two later sets of three produce ten outcomes. All failures remain in the manifest; they are not silently dropped.

<!-- notebook: 07_heat_calibration.ipynb#campaign -->
```python
manifest = await asyncio.to_thread(lesson.run_demo)
print("round  diffusivity  outcome   misfit")
for row in manifest["runs"]:
    print(row["round"], f'{row["diffusivity"]:.4f}', row["outcome"], row.get("misfit", "unavailable"))
assert len(manifest["runs"]) == 10
assert sum(row["outcome"] == "failed" for row in manifest["runs"]) == 1
initial_best = min(row["misfit"] for row in manifest["runs"]
                   if row["round"] == 0 and row["outcome"] == "finished")
assert manifest["best_misfit"] < initial_best
print("Selected diffusivity:", manifest["best_diffusivity"])
```

## 4. Continue a partial application checkpoint

Save a state after seven solver steps, load it with pickle disabled, and submit it to a new run. Compare its final field with uninterrupted work. The checkpoint is solver state, while experiment_manifest.json records configuration, outcomes, versions, and source/data hashes. graph_id identifies a declaration, not a complete experiment.

<!-- notebook: 07_heat_calibration.ipynb#checkpoint -->
```python
partial = lesson.initial_state(problem, 0.17)
lesson.advance(partial, problem, block_steps=7)
with tempfile.TemporaryDirectory() as temporary:
    checkpoint = Path(temporary) / "partial_solver.npz"
    lesson.save_checkpoint(partial, checkpoint)
    restored = lesson.load_checkpoint(checkpoint)

def continue_solver():
    graph, state = lesson.build_graph()
    with Engine() as engine:
        run = engine.submit(graph, ArtifactContext({state: restored}),
                            settings=ContextSettings(max_iterations=None))
        run.wait(timeout=30)
        if run.state is not ContextState.FINISHED:
            raise RuntimeError(str(run.report.data.failure))
        return run.artifact(state).value

continued = await asyncio.to_thread(continue_solver)
np.testing.assert_allclose(continued.values, trial.values, atol=1e-12, rtol=0)
print("Checkpoint matches uninterrupted:", manifest["checkpoint_matches_uninterrupted"])
print("Provenance fields:", sorted(key for key in manifest if "sha256" in key))
```

## Try it yourself

Change the first single-trial candidate to 0.1, then compare its misfit with 0.17. Keep checkpoint/uninterrupted comparisons on the same candidate. For a numerical convergence experiment, use 81 cells in both make_problem and build_graph and compare error against analytic observations.

The CLI --output heat_results retains partial_solver.npz and experiment_manifest.json; this notebook uses temporary files. A research release additionally needs an environment lock, external datasets, solver tolerances, and relevant hardware/backend information. The checks do not establish throughput gains or bitwise reproducibility across platforms.

## Read the canonical implementation

The complete [heat_calibration.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/heat_calibration.py) supplies the operators and application helpers used above. This excerpt shows source provenance:

```{literalinclude} ../../tutorials/heat_calibration.py
:language: python
:pyobject: source_manifest
```

Continue with [the tutorial collection](index.md) or [supported behavior and limitations](../reference/limits.md).
