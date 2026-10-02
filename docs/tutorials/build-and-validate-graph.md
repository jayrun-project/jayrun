```{eval-rst}
.. meta::
   :description: Validate a NumPy and PyTorch computation graph with Jayrun. Diagnose a producer and consumer dtype mismatch, then execute the corrected graph.
```

(tutorial-build-and-validate-graph)=
# Build and Validate a Graph

This introduction catches a producer/consumer dtype mismatch before execution, then runs
the corrected NumPy/PyTorch graph. It does not remove metadata to hide the mismatch.

## Run it

```bash
python -m tutorials.build_graph
```

Open `tutorials/01_build_graph.ipynb` for the local/Colab path. NumPy and PyTorch are
optional tutorial dependencies. Run from the source repository paired with the tutorial.

## Declare, connect, and validate

`PrepareDataset` declares the same dtype it actually produces. `TrainModel` requires
float32; passing float64 to the builder creates an intentional static mismatch. The
model flow trains and then wraps the model in `TemperatureScaledModel`.

```{literalinclude} ../../tutorials/build_graph.py
:language: python
:pyobject: build_graph
```

## Execute the corrected graph

The example validates without executing the invalid graph, then supplies an initial
dataset/model to the corrected declaration. Failure diagnostics use `run.report.data.failure`.

```{literalinclude} ../../tutorials/build_graph.py
:language: python
:pyobject: run_demo
```

Call `graph.plot.save("training-graph.html")` to inspect the declaration. The returned
demo summary reports one detected mismatch and the corrected result type. Follow
[graph visualization](../guides/visualization/graphs.md) to interpret compatibility markers.

## Canonical source

The complete runnable implementation is [tutorials/build_graph.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/build_graph.py).
Use {doc}`the tutorial index <index>` for all notebooks and their execution requirements.
