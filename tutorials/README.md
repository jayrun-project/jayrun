# Jayrun tutorials

These examples belong to the application layer; they do not change Jayrun's core API.
Each notebook imports the adjacent Python implementation. Documentation includes the
same source. Framework verification exercises these applications through their public interfaces.

## Choose a tutorial

| Notebook | Application and concepts |
| --- | --- |
| [Build and validate a graph](01_build_graph.ipynb) | Detect a float64/float32 declaration mismatch without executing work, then execute the corrected graph. |
| [Denoise images with FastAPI](02_denoise_images.ipynb) | A real FastAPI TestClient runs the app lifespan, routes uploaded images, and exercises invalid input. The same app can be served with Uvicorn. |
| [Shared MNIST inference](03_mnist_inference.ipynb) | Share one read-only inference model across request contexts and compare predictions to native PyTorch. The default is a clearly labelled synthetic lifecycle fixture. |
| [Supervised MNIST training](04_mnist_training.ipynb) | Keep model and optimizer together in a per-trial artifact. A graph-scoped supervisor holds, selects, aborts, promotes, and gracefully stops trials. |
| [Controllable document ingestion](05_document_ingestion.ipynb) | Create asynchronous text/HTML jobs, inspect a review pause, resume, and publish a searchable lexical index. SQLite job records and transactions are owned by this application. |
| [Checkpointed adapter fine-tuning](06_adapter_finetuning.ipynb) | Train a low-rank output adapter on an offline language-model fixture. Save and restore model, optimizer, scheduler, sampler RNG, and update position. |
| [Adaptive scientific calibration](07_heat_calibration.ipynb) | Calibrate a heat-equation solver, refine candidate parameters, retain a failed candidate, and save numerical provenance. Restart from an application checkpoint. |

## Run locally

From the extracted repository root:

```bash
python -m pip install -r tutorials/requirements.txt
python -m tutorials.build_graph
python -m tutorials.denoise_images
python -m tutorials.mnist_inference
python -m tutorials.mnist_training
python -m tutorials.document_ingestion
python -m tutorials.adapter_finetuning --output adapter_results
python -m tutorials.heat_calibration --output heat_results
```

The PyTorch examples need an existing suitable PyTorch installation. This requirements
file deliberately does not install or replace PyTorch. The examples import the local
`jayrun/` source when launched from the repository root; installing a different released
Jayrun package is not a substitute for using the source version paired with these lessons.

The MNIST examples default to a synthetic lifecycle fixture so all notebooks have a
small offline path. It is explicitly **not MNIST** and its accuracy is not a model-quality
result. Use real data and CUDA explicitly:

```bash
python -m tutorials.mnist_inference --real-mnist --device cuda
python -m tutorials.mnist_training --real-mnist --device cuda
```

Missing requested CUDA is an error, never an implicit CPU fallback. Downloaded MNIST
is cached in `MNIST_DIR` or `~/.cache/jayrun/mnist`. Launch either ASGI app with one worker:

```bash
uvicorn tutorials.denoise_images:create_app --factory
uvicorn tutorials.document_ingestion:create_app --factory
```

## Run in Google Colab

Upload/open a notebook, then run its source-setup cell. When the repository is absent,
it asks for the complete project ZIP and safely extracts it. The repository can also
be available in the runtime already. For GPU lessons select a GPU runtime and set
`DEVICE = "cuda"`. Colab is an interactive example environment, not the production host
for the web services. The notebooks use real in-process ASGI clients, not public tunnels.

Only missing non-PyTorch optional packages are installed by the Colab setup. Do not
replace the runtime's working PyTorch/CUDA installation. The hosted Colab service itself
was not tested during this rebuild; local fresh-kernel execution is reported separately.

## Optional real pretrained-model integration

`peft_finetuning.py` uses Hugging Face Transformers and PEFT rather than adding a model
framework to Jayrun. Install `tutorials/requirements-peft.txt` explicitly when using it.
For a first exploratory run:

```bash
python -m tutorials.peft_finetuning --revision main --device cuda --output peft_results
```

For reproduction, replace `main` with the resolved immutable revision recorded in
`result.json`. Resume with `--resume peft_results/training_checkpoint.pt --updates 24`.
Model downloads, CUDA execution, and pretrained model quality were not qualified in
this CPU rebuild. The fixture checkpoint test and the optional integration are separate.

## Ownership and limits

A context owns mutable training/solver state. Resources own shared read-only models,
encoders, or inputs. Python payloads do not become immutable simply by entering a
`Data` container. A paused run can retain memory and placement; pause is not eviction.
Graph stop finishes the accepted iteration in `FINISHED` and records `stop_requested`.
Retries do not roll back optimizer updates or external side effects.

The document example owns its SQLite job store and publication transactions. Its
`max_active` and `max_history` limits bound counts, not every possible memory allocation.
Delete terminal jobs to release application handles and their indexed content. Runtime
history is not automatic job/checkpoint recovery, and `graph_id` is not an experiment
fingerprint. The examples do not supply authentication, tenant isolation, distributed
launching, arbitrary-URL safety, or exactly-once side effects.

## Verification

Run the module commands above or execute each notebook from a fresh kernel to check
its example. The notebooks import the adjacent Python implementation, so keep the
complete `tutorials/` directory and sample data together.

Development verification covers actual FastAPI clients and a local HTTP upstream,
numerical baselines, optimizer/checkpoint continuity, retained failure outcomes and
fresh-kernel notebook execution. Those internal test tools are not included in this
public repository. Real MNIST downloads, pretrained-model downloads and hosted Colab
execution require separate opt-in checks; synthetic fixtures establish lifecycle
behavior, not real-data model quality or hardware/endurance qualification.
