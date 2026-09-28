(tutorial-checkpointed-adapter-finetuning)=
# Checkpointed Adapter Fine-Tuning

Train a low-rank language-model adapter while keeping mutable training state explicit.
The default offline GRU fixture tests lifecycle and checkpoint mechanics. A separate optional
PEFT integration loads an actual pretrained transformer; choose the offline example first to learn the workflow.

## Run the offline example

```bash
python -m tutorials.adapter_finetuning --output adapter_results
```

Open `tutorials/06_adapter_finetuning.ipynb`. The fixture prepares a small base model before
scheduling, freezes it, and trains only a low-rank output head on the bundled support-text
corpus. It is not a pretrained LLM or a demonstration of production response quality.

## Keep all mutable state in one artifact

The artifact owns the model, optimizer, scheduler, sampler generator, update position,
examples-seen count, and model identity. The token dataset is shared read-only by the
application. A graph iteration performs up to three optimizer updates, evaluates, records
bounded progress, and reaches a control boundary. Stop prevents another iteration.

```{literalinclude} ../../tutorials/adapter_finetuning.py
:language: python
:pyobject: TrainingState
```

```{literalinclude} ../../tutorials/adapter_finetuning.py
:language: python
:pyobject: TrainBlock
```

There is no per-tensor graph scheduling. CPU/CUDA placement is explicit; initial movement
rebinds the optimizer while restoring its existing state. Later iterations reuse it. A
reservation is a capacity claim, not VRAM enforcement. The example is single-device and
makes no multi-GPU or multi-host training claim.

## Save a checkpoint, not merely a report

The application checkpoint contains model, optimizer, scheduler, sampler RNG, positions,
model identity, and the token-dataset fingerprint. It is saved via a temporary file and
loaded with `weights_only=True`. A separately constructed matching state receives the
checkpoint and continues in a new context. Dataset/model mismatches are rejected.

```{literalinclude} ../../tutorials/adapter_finetuning.py
:language: python
:pyobject: save_checkpoint
```

The default recipe has no dropout or other model-side random operations; the sampler owns
its RNG. It does not restore process-global RNG into concurrent trials. The optional PEFT
recipe also disables dropout. Arbitrary stochastic models, data-loader workers, distributed
samplers, and CUDA kernel nondeterminism need additional application-specific qualification.

After loading a checkpoint, compare the update position and the next training result with an uninterrupted run. The optimizer, scheduler and sampler must continue together. A partially executed update block must not simply be retried: restore a known application checkpoint first. Runtime histories do not reconstruct training state.

## Optional pretrained transformer

```bash
python -m pip install -r tutorials/requirements-peft.txt
python -m tutorials.peft_finetuning --revision main --device cuda --output peft_results
```

The complete implementation is `tutorials/peft_finetuning.py`; no framework modification is
required. Transformers loads `HuggingFaceTB/SmolLM2-135M` by default and PEFT applies LoRA to
linear layers. Use `--model` to select another compatible causal model. The resolved immutable
revision is recorded; reuse that revision rather than `main` for reproduction. The standalone
adapter is saved using PEFT's own format, while a full application checkpoint retains optimizer
state. This small corpus is not a suitable quality benchmark. The optional path downloads model weights and needs a compatible backend; start with
the offline fixture if these dependencies are unavailable.

The design follows [PyTorch checkpoint guidance](https://docs.pytorch.org/tutorials/beginner/saving_loading_models.html)
and the [PEFT LoRA interface](https://huggingface.co/docs/peft/en/package_reference/lora).

## Canonical source

The complete runnable implementation is [tutorials/adapter_finetuning.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/adapter_finetuning.py).
Use {doc}`the tutorial index <index>` for all notebooks and their execution requirements.
