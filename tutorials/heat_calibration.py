"""Adaptive heat-equation calibration with an independent reference and provenance.

The numerical method belongs to the application; Jayrun owns iterative execution.
"""
from __future__ import annotations

import hashlib
import json
import platform
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import jayrun
from jayrun import (Artifact, ArtifactContext, ArtifactField, ArtifactFlow, BaseOperator,
                    BaseResource, ConfigField, Data, Engine, GraphDefinition, ResourceField)
from jayrun.context import ContextState
from jayrun.settings import ArtifactPolicy, ContextSettings, EngineSettings


@dataclass(frozen=True, slots=True)
class Problem:
    x: np.ndarray
    observations: np.ndarray
    horizon: float


@dataclass(slots=True)
class SimulationState:
    diffusivity: float
    values: np.ndarray
    time: float = 0.0
    steps: int = 0
    misfit: float = float("inf")


def make_problem(cells: int = 41, truth: float = .17, horizon: float = .1) -> Problem:
    if cells < 5 or truth <= 0 or horizon <= 0:
        raise ValueError("require cells >= 5 and positive diffusivity and horizon")
    x = np.linspace(0, 1, cells)
    observations = np.sin(np.pi*x)*np.exp(-truth*np.pi**2*horizon)
    x.flags.writeable = observations.flags.writeable = False
    return Problem(x, observations, horizon)


def initial_state(problem: Problem, diffusivity: float) -> SimulationState:
    return SimulationState(diffusivity, np.sin(np.pi*problem.x))


def advance(state: SimulationState, problem: Problem, block_steps: int = 20) -> None:
    """Explicit Euler with zero Dirichlet boundaries and a stability-limited step."""
    if not np.isfinite(state.diffusivity) or state.diffusivity <= 0:
        raise ValueError("diffusivity must be finite and positive")
    if block_steps < 1 or state.values.shape != problem.x.shape:
        raise ValueError("invalid block size or field shape")
    if not 0 <= state.time <= problem.horizon or not np.isfinite(state.values).all():
        raise ValueError("invalid solver checkpoint")
    dx = float(problem.x[1]-problem.x[0])
    stable_dt = .4*dx*dx/state.diffusivity
    for _ in range(block_steps):
        remaining = problem.horizon-state.time
        if remaining <= 1e-14:
            state.time = problem.horizon
            break
        dt = min(stable_dt, remaining)
        values = state.values.copy()
        values[1:-1] += (dt*state.diffusivity/dx**2)*(
            state.values[:-2]-2*state.values[1:-1]+state.values[2:])
        values[0] = values[-1] = 0.0
        state.values = values
        state.time = min(problem.horizon, state.time+dt)
        state.steps += 1
    state.misfit = float(np.mean((state.values-problem.observations)**2))


class ProblemResource(BaseResource):
    def __init__(self, *, cells: int, truth: float, horizon: float) -> None:
        super().__init__()
        self.cells = ConfigField(value_type=int, required=False, default=cells)
        self.truth = ConfigField(value_type=float, required=False, default=truth)
        self.horizon = ConfigField(value_type=float, required=False, default=horizon)

    def setup(self) -> Data:
        return Data(value=make_problem(self.cells.value, self.truth.value, self.horizon.value))

    def teardown(self, data: Data) -> None:
        pass  # The immutable numerical inputs own no external handles.


class AdvanceSimulation(BaseOperator):
    requirements = ("numpy",)

    def __init__(self, *, state: Artifact, outputs: tuple[Artifact, ...]) -> None:
        super().__init__()
        self.state = ArtifactField(required=True)
        self.problem = ResourceField(required=True, parallel_safe=True)
        self.block_steps = ConfigField(value_type=int, required=False, default=20)
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> SimulationState:
        state: SimulationState = self.state.value
        problem: Problem = self.problem.value
        advance(state, problem, self.block_steps.value)
        self.context.record("solver", {"time": state.time, "steps": state.steps,
                                       "misfit": state.misfit})
        if state.time >= problem.horizon-1e-14:
            self.context.stop()
        return state


def build_graph(cells: int = 41, truth: float = .17, horizon: float = .1):
    state = Artifact(name="solver_state")
    step = AdvanceSimulation(state=state, outputs=(state,))
    flow = ArtifactFlow(step, artifact=state)
    graph = GraphDefinition(flow, entry_flows=(flow,))
    graph.bind_resources({step.problem: ProblemResource(cells=cells, truth=truth, horizon=horizon)}); graph.confirm()
    return graph, state


def save_checkpoint(state: SimulationState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            np.savez(stream, diffusivity=state.diffusivity, values=state.values,
                     time=state.time, steps=state.steps)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_checkpoint(path: Path) -> SimulationState:
    with np.load(path, allow_pickle=False) as saved:
        state = SimulationState(float(saved["diffusivity"]), saved["values"].copy(),
                                float(saved["time"]), int(saved["steps"]))
    if state.steps < 0 or state.values.ndim != 1:
        raise ValueError("invalid solver checkpoint")
    return state


def source_manifest() -> dict[str, object]:
    package = Path(jayrun.__file__).parent
    digest = hashlib.sha256()
    for source in sorted(package.rglob("*.py")):
        digest.update(source.relative_to(package).as_posix().encode()+b"\0"+source.read_bytes())
    return {"python": platform.python_version(), "numpy": np.__version__,
            "jayrun_version": jayrun.__version__, "jayrun_python_sha256": digest.hexdigest(),
            "tutorial_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "hardware": platform.machine(), "numerical_method": "explicit Euler, CFL <= 0.4"}


def run_demo(*, output_directory: Path | None = None) -> dict[str, object]:
    problem = make_problem()
    graph, artifact = build_graph()
    settings = ContextSettings(max_iterations=None, record_history_limit=4,
        artifact_policy=ArtifactPolicy(release_entry_artifacts=True))
    evidence: list[dict[str, object]] = []
    best: SimulationState | None = None
    with Engine(EngineSettings(max_workers=3, max_tasks=6)) as engine:
        candidates = [.1, .2, .3, -.1]  # The invalid candidate demonstrates contained failure.
        for round_index in range(3):
            runs = []
            for value in candidates:
                inputs = ArtifactContext(); inputs.set({artifact: initial_state(problem, value)})
                runs.append((value, engine.submit(graph, inputs, settings=settings)))
            successful = []
            for value, run in runs:
                run.wait(timeout=30)
                row: dict[str, object] = {"round": round_index, "diffusivity": value,
                                         "outcome": run.state.value, "context_id": run.context_id}
                if run.state is ContextState.FINISHED:
                    state = run.artifact(artifact).value
                    reference = initial_state(problem, value)
                    while reference.time < problem.horizon-1e-14:
                        advance(reference, problem)
                    np.testing.assert_allclose(state.values, reference.values, atol=1e-12, rtol=0)
                    row.update(misfit=state.misfit, steps=state.steps,
                               stop_requested=run.report.data.stop_requested)
                    successful.append(state)
                else:
                    row["failure"] = str(run.report.data.failure)
                evidence.append(row)
            if not successful:
                raise RuntimeError("every simulation failed")
            best = min(successful, key=lambda state: state.misfit)
            width = .05/(2**round_index)
            candidates = [best.diffusivity-width, best.diffusivity, best.diffusivity+width]

    assert best is not None
    # Restart one partial application checkpoint in a new context, not from engine history.
    with tempfile.TemporaryDirectory(prefix="jayrun-solver-") as temporary:
        folder = output_directory or Path(temporary)
        folder.mkdir(parents=True, exist_ok=True)
        checkpoint = folder/"partial_solver.npz"
        partial = initial_state(problem, best.diffusivity)
        advance(partial, problem, block_steps=7)
        save_checkpoint(partial, checkpoint)
        restored = load_checkpoint(checkpoint)
        with Engine() as engine:
            inputs = ArtifactContext(); inputs.set({artifact: restored})
            run = engine.submit(graph, inputs, settings=settings)
            run.wait(timeout=30)
            if run.state is not ContextState.FINISHED:
                raise RuntimeError(str(run.report.data.failure))
            continued = run.artifact(artifact).value
        np.testing.assert_allclose(continued.values, best.values, rtol=0, atol=1e-12)
        manifest = {**source_manifest(), "graph_id": graph.graph_id,
                    "configuration": {"cells": 41, "truth": .17, "horizon": .1,
                                      "rounds": 3, "seed": "not used; analytic observations"},
                    "observations_sha256": hashlib.sha256(problem.observations.tobytes()).hexdigest(),
                    "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                    "result_sha256": hashlib.sha256(best.values.tobytes()).hexdigest(),
                    "best_diffusivity": best.diffusivity, "best_misfit": best.misfit,
                    "runs": evidence, "checkpoint_matches_uninterrupted": True}
        (folder/"experiment_manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    return manifest


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("heat_results"))
    args = parser.parse_args()
    result = run_demo(output_directory=args.output)
    print(json.dumps(result, indent=2))
