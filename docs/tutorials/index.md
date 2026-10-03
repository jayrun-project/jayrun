```{eval-rst}
.. meta::
   :description: Run Jayrun Python workflow tutorials for graph validation, FastAPI image processing, PyTorch inference and training, document ingestion and scientific calibration.
```

# Tutorials

Use these lessons to build a workflow you can inspect and adapt. Each has a guided notebook, a walkthrough with the same runnable steps, and a complete Python application. Start with graph validation, then choose a service, model, or scientific example. Read [your first graph](../start/first-graph.md) and [data and lifetimes](../start/data-and-lifetimes.md) first if Jayrun is new to you.

## Prepare your environment

Use Python 3.11 or later in an isolated environment and keep the complete repository, notebooks, and bundled data together. From a repository checkout:

```bash
git clone https://github.com/jayrun-project/jayrun.git
cd jayrun
python -m pip install -e .
python -m pip install -r tutorials/requirements.txt
```

The requirements file installs NumPy, Pillow, and the web-service dependencies. It deliberately **does not install PyTorch**. Graph validation, inference, training, and adapter lessons require an existing PyTorch build suitable for your CPU/GPU. Document ingestion does not require PyTorch; scientific calibration needs NumPy. GPU/backend setup is specific to your platform. See [PyTorch's installation selector](https://pytorch.org/get-started/locally/) when you need a suitable build.

For notebooks, use Jupyter with a kernel from that same environment. If Jupyter is absent, install `jupyterlab` there and launch `python -m jupyterlab` from the repository root. Run cells in order in a fresh kernel. Notebook setup also supports a complete source ZIP in Colab; opening an individual notebook alone does not supply its implementation or sample data.

The walkthrough's Python snippets are consecutive notebook cells and use top-level `await`. Synchronous Engine blocks and TestClient demonstrations run through `asyncio.to_thread` because Jupyter already owns an event loop. For a terminal demonstration, use each lesson's `python -m tutorials...` command. CLI commands use the checkout's local Jayrun source; a separately installed wheel does not override it.

## Choose a lesson

| Walkthrough | Python source | Notebook | Capability |
| --- | --- | --- | --- |
| [Build and validate](build-and-validate-graph.md) | [build_graph.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/build_graph.py) | [01_build_graph](https://github.com/jayrun-project/jayrun/blob/main/tutorials/01_build_graph.ipynb) | Properties, diagnostics and corrected execution |
| [Image service](denoise-images-with-fastapi.md) | [denoise_images.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/denoise_images.py) | [02_denoise_images](https://github.com/jayrun-project/jayrun/blob/main/tutorials/02_denoise_images.ipynb) | Async service, shared client and routing |
| [Shared model inference](mnist-inference-and-training.md#share-a-read-only-model-for-inference) | [mnist_inference.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/mnist_inference.py) | [03_mnist_inference](https://github.com/jayrun-project/jayrun/blob/main/tutorials/03_mnist_inference.ipynb) | Read-only model reuse and placement |
| [Supervised training](mnist-inference-and-training.md#supervise-replace-and-promote) | [mnist_training.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/mnist_training.py) | [04_mnist_training](https://github.com/jayrun-project/jayrun/blob/main/tutorials/04_mnist_training.ipynb) | Iteration, mutable state and scoped supervision |
| [Document service](document-ingestion.md) | [document_ingestion.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/document_ingestion.py) | [05_document_ingestion](https://github.com/jayrun-project/jayrun/blob/main/tutorials/05_document_ingestion.ipynb) | Long-running jobs and transactional publication |
| [Adapter checkpointing](checkpointed-adapter-finetuning.md) | [adapter_finetuning.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/adapter_finetuning.py) | [06_adapter_finetuning](https://github.com/jayrun-project/jayrun/blob/main/tutorials/06_adapter_finetuning.ipynb) | Model/optimizer/RNG checkpoints |
| [Scientific campaign](adaptive-scientific-calibration.md) | [heat_calibration.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/heat_calibration.py) | [07_heat_calibration](https://github.com/jayrun-project/jayrun/blob/main/tutorials/07_heat_calibration.ipynb) | Adaptive control and reproducibility |

Each has a small offline CPU path. The MNIST CPU fixtures are synthetic lifecycle examples, not downloaded MNIST or a model-quality claim. Real datasets, pretrained models, CUDA and hosted-service behavior are opt-in and have separate dependencies. The pretrained transformer cell remains disabled by default.

The notebooks let you inspect a declaration, supply inputs, check an outcome, and change one decision. Predict the result of each “Try it yourself” exercise before running it. Expected states and counts are explained alongside the steps; generated IDs, model accuracy, and timings can vary. A passing numerical or lifecycle check does not establish production capacity or model quality.

See the [tutorial README](https://github.com/jayrun-project/jayrun/blob/main/tutorials/README.md), [requirements](https://github.com/jayrun-project/jayrun/blob/main/tutorials/requirements.txt) and [optional PEFT requirements](https://github.com/jayrun-project/jayrun/blob/main/tutorials/requirements-peft.txt).

## Walkthroughs

```{toctree}
:maxdepth: 1

build-and-validate-graph
denoise-images-with-fastapi
mnist-inference-and-training
document-ingestion
checkpointed-adapter-finetuning
adaptive-scientific-calibration
```
