(tutorial-adaptive-scientific-calibration)=
# Adaptive Scientific Calibration

Calibrate a one-dimensional heat-diffusion model against analytic observations. The numerical
method remains ordinary NumPy code. Jayrun owns iterative execution, reusable problem data,
per-trial state, failure isolation, and control boundaries.

## Run it

```bash
python -m tutorials.heat_calibration --output heat_results
```

Open `tutorials/07_heat_calibration.ipynb`. No dataset download or GPU is required.

## State and numerical boundaries

A shared problem resource provides a grid and read-only observations. Each trial owns its
field values, diffusivity, simulated time, step count, and misfit. `advance()` applies explicit
Euler steps with zero Dirichlet boundary values and a stability-limited time step. Each graph
iteration performs a block, records bounded solver progress, and requests Stop at the horizon.

```{literalinclude} ../../tutorials/heat_calibration.py
:language: python
:pyobject: AdvanceSimulation
```

This tutorial uses an application-owned campaign loop, not a new scheduling policy inside the
engine. It runs an initial candidate set, keeps all outcomes, and refines around the best
successful value for two more rounds. An invalid negative diffusivity deliberately fails one
candidate without discarding the rest of the campaign.

## Verify computation independently

Every successful graph result is checked against the native numerical loop. You can also
compare the solver to the analytic sine-mode solution within a chosen numerical tolerance.
The campaign refinement improves the objective relative to the initial set. These checks
measure numerical correctness, not a new scientific calibration algorithm or a throughput gain.

A partial solver checkpoint is saved as NPZ without pickle objects, loaded into a new state,
and continued in a new context. Its final field matches the uninterrupted run. This is explicit
application checkpoint continuation, not restoration of a live context from engine history.

## Produce a reproducibility artifact

`experiment_manifest.json` includes resolved numerical configuration, observation/result hashes,
checkpoint lineage by hash, Python/NumPy/Jayrun versions, tutorial and framework source hashes,
graph identity, all ten outcomes including the deliberate failure, and the selected parameter.
Source hashes bind the actual working files rather than assuming Git HEAD describes an uncommitted
tree. The supplied fixture is analytic and uses no random seed.

```{literalinclude} ../../tutorials/heat_calibration.py
:language: python
:pyobject: source_manifest
```

`graph_id` is declaration identity, not an experiment fingerprint. A real research release should
also supply its full environment lock, external datasets, hardware/software details relevant to
its solver, numerical tolerances, and source repository revision/patch when available. No claim
of bitwise reproducibility across hardware or BLAS implementations is made here.

## Canonical source

The complete runnable implementation is [tutorials/heat_calibration.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/heat_calibration.py).
Use {doc}`the tutorial index <index>` for all notebooks and their execution requirements.
