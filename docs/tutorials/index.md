```{eval-rst}
.. meta::
   :description: Run Jayrun Python workflow tutorials for graph validation, FastAPI image processing, PyTorch inference and training, document ingestion and scientific calibration.
```

# Tutorials

The tutorials combine framework behavior with application-owned models, services and storage. Run them from the framework repository checkout so their source and installed Jayrun implementation match. Their canonical Python sources and notebooks are linked below; these paths are included with the final release.

```bash
git clone https://github.com/jayrun-project/jayrun.git
cd jayrun
python -m pip install -e .
python -m pip install -r tutorials/requirements.txt
```

Use a suitable isolated environment; GPU/backend setup is specific to your platform. Notebook setup also supports a complete source archive. In Jupyter/Colab, follow the notebook's source-setup cell and use top-level await for async work. Synchronous CLI demonstrations can run through `await asyncio.to_thread(...)`.

| Walkthrough | Python source | Notebook | Capability |
| --- | --- | --- | --- |
| [Build and validate](build-and-validate-graph.md) | [build_graph.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/build_graph.py) | [01_build_graph](https://github.com/jayrun-project/jayrun/blob/main/tutorials/01_build_graph.ipynb) | Properties, diagnostics and corrected execution |
| [Image service](denoise-images-with-fastapi.md) | [denoise_images.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/denoise_images.py) | [02_denoise_images](https://github.com/jayrun-project/jayrun/blob/main/tutorials/02_denoise_images.ipynb) | Async service, shared client and routing |
| [Shared model inference](mnist-inference-and-training.md#share-a-read-only-model-for-inference) | [mnist_inference.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/mnist_inference.py) | [03_mnist_inference](https://github.com/jayrun-project/jayrun/blob/main/tutorials/03_mnist_inference.ipynb) | Read-only model reuse and placement |
| [Supervised training](mnist-inference-and-training.md#supervise-replace-and-promote) | [mnist_training.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/mnist_training.py) | [04_mnist_training](https://github.com/jayrun-project/jayrun/blob/main/tutorials/04_mnist_training.ipynb) | Iteration, mutable state and scoped supervision |
| [Document service](document-ingestion.md) | [document_ingestion.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/document_ingestion.py) | [05_document_ingestion](https://github.com/jayrun-project/jayrun/blob/main/tutorials/05_document_ingestion.ipynb) | Long-running jobs and transactional publication |
| [Adapter checkpointing](checkpointed-adapter-finetuning.md) | [adapter_finetuning.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/adapter_finetuning.py) | [06_adapter_finetuning](https://github.com/jayrun-project/jayrun/blob/main/tutorials/06_adapter_finetuning.ipynb) | Model/optimizer/RNG checkpoints |
| [Scientific campaign](adaptive-scientific-calibration.md) | [heat_calibration.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/heat_calibration.py) | [07_heat_calibration](https://github.com/jayrun-project/jayrun/blob/main/tutorials/07_heat_calibration.ipynb) | Adaptive control and reproducibility |

Each has a small offline CPU path. The MNIST CPU fixtures are synthetic lifecycle examples, not downloaded MNIST or a model-quality claim. Real datasets, pretrained models, CUDA and hosted-service behavior are opt-in and have separate dependencies.

See the [tutorial README](https://github.com/jayrun-project/jayrun/blob/main/tutorials/README.md), [requirements](https://github.com/jayrun-project/jayrun/blob/main/tutorials/requirements.txt) and [optional PEFT requirements](https://github.com/jayrun-project/jayrun/blob/main/tutorials/requirements-peft.txt). The manual renders excerpts from the local canonical sources; it does not fetch tutorial files during the documentation build.

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
