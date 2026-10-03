```{eval-rst}
.. meta::
   :description: Learn checkpointed adapter training with Jayrun’s offline GRU example, explicit mutable state and an optional pretrained-transformer integration.
```

(tutorial-checkpointed-adapter-finetuning)=
# Checkpointed Adapter Fine-Tuning

Train a small low-rank output adapter, save all continuation state, reconstruct it, and compare resumed training with an uninterrupted run. You should understand a PyTorch optimizer and state_dict. The offline GRU and bundled text are a lifecycle fixture, not a pretrained LLM or a response-quality benchmark.

## Run it

Follow [tutorial setup](index.md#prepare-your-environment), then run from the repository root:

```bash
python -m tutorials.adapter_finetuning --output adapter_results
```

Open `tutorials/06_adapter_finetuning.ipynb` for the guided lesson. The Python snippets below are consecutive notebook cells: run them in Jupyter with top-level `await`. For a terminal run, use the module command above.

## 1. Separate shared input from mutable training state

The token dataset is shared read-only by convention. TrainingState owns model, optimizer, scheduler, sampler RNG, identity, update position, and examples-seen count. One graph iteration performs up to three updates, records progress, and reaches a control boundary. total_updates is an absolute target, not a number to add to the current position.

<!-- notebook: 06_adapter_finetuning.ipynb#inspect-state -->
```python
import asyncio
import inspect
import tempfile
import torch
from pathlib import Path
from tutorials import adapter_finetuning as lesson

print(inspect.getsource(lesson.TrainingState))
print(inspect.getsource(lesson.TrainBlock))
dataset = lesson.load_fixture()
print("Train / validation shapes:", tuple(dataset.train.shape), tuple(dataset.validation.shape))
```

## 2. Train to update six

new_fixture_state prepares the small base and freezes it before scheduling. Only the low-rank head trains. run_training assembles and submits the confirmed graph using those canonical operators. Six updates correspond to 24 sampled examples in this recipe; optimizer and scheduler should both be populated.

<!-- notebook: 06_adapter_finetuning.ipynb#train-partial -->
```python
partial = await asyncio.to_thread(
    lesson.run_training, lesson.new_fixture_state(), dataset, total_updates=6)
print("Updates / examples seen:", partial.step, partial.examples_seen)
assert partial.step == 6 and partial.examples_seen == 24
assert partial.optimizer.state
```

## 3. Save, reconstruct, and continue

Saving model weights alone would lose optimizer momentum, schedule position, and the next sampled batch. The application checkpoint stores those values together and verifies dataset/model identity when loading. A new state is reconstructed, then restored before another context is submitted. Here the temporary directory is removed after restoration; keep a chosen output directory for a real experiment.

<!-- notebook: 06_adapter_finetuning.ipynb#restore -->
```python
with tempfile.TemporaryDirectory() as temporary:
    checkpoint = Path(temporary) / "training_checkpoint.pt"
    lesson.save_checkpoint(partial, dataset, checkpoint)
    restored = lesson.restore_checkpoint(lesson.new_fixture_state(), dataset, checkpoint)
assert restored.step == 6 and restored.examples_seen == 24
torch.testing.assert_close(restored.generator.get_state(), partial.generator.get_state(), rtol=0, atol=0)

resumed = await asyncio.to_thread(lesson.run_training, restored, dataset, total_updates=12)
print("After continuation:", resumed.step, resumed.examples_seen)
assert resumed.step == 12 and resumed.examples_seen == 48
```

## 4. Compare the full parameter state

Build the same initial fixture and train uninterrupted to update twelve. On this CPU recipe, resumed parameters should agree exactly. The canonical complete demo also compares direct PyTorch training and checks that frozen parameters did not change. These checks establish continuation for this fixture, not arbitrary stochastic models or hardware.

<!-- notebook: 06_adapter_finetuning.ipynb#compare -->
```python
uninterrupted = await asyncio.to_thread(
    lesson.run_training, lesson.new_fixture_state(), dataset, total_updates=12)
for name, value in uninterrupted.model.state_dict().items():
    torch.testing.assert_close(value, resumed.model.state_dict()[name], rtol=0, atol=0)
print("Checkpoint continuation matches uninterrupted CPU training.")

summary = await asyncio.to_thread(lesson.run_demo)
assert summary["matches_direct_baseline"] and summary["frozen_parameters_unchanged"]
print({key: summary[key] for key in ("updates", "trainable_parameters", "validation_loss_before", "validation_loss_after")})
```

## Try it yourself

Change the checkpoint boundary to update three and keep the final target twelve. Adapt the expected position/examples-seen checks and compare the result again. Try restoring into a fixture with a different seed: model identity should reject it.

Do not retry a partially executed optimizer block as if its effects were rolled back. Restore a known application checkpoint first. The sampler owns the RNG in this recipe; arbitrary dropout, worker RNG, or CUDA nondeterminism needs additional qualification. History records do not reconstruct training state.

## Optional: a pretrained transformer

The separate peft_finetuning implementation uses Transformers and PEFT. It downloads weights and needs explicit optional-package installation and a suitable memory budget. Enable only after completing the offline lesson. Record and reuse the resolved immutable revision. This tiny corpus does not evaluate production model quality.

<!-- notebook: 06_adapter_finetuning.ipynb#optional-pretrained -->
```python
RUN_PRETRAINED = False
if RUN_PRETRAINED:
    from tutorials.peft_finetuning import run_pretrained
    pretrained_result = await asyncio.to_thread(
        run_pretrained, model_id="HuggingFaceTB/SmolLM2-135M", revision="main",
        output=Path("peft_results"), device="cpu", total_updates=12)
    print(pretrained_result)
```

## Optional pretrained-model setup

The optional notebook cell is disabled by default. To run the separate integration explicitly:

```bash
python -m pip install -r tutorials/requirements-peft.txt
python -m tutorials.peft_finetuning --revision main --device cuda --output peft_results
```

The resolved immutable revision is recorded; use it for later reproduction. The PEFT adapter export and full optimizer checkpoint serve different purposes. CPU/CUDA placement is explicit and single-device. A reservation accounts for capacity; it does not enforce actual VRAM allocation. The fixture has no model-side dropout; concurrent trials do not restore process-global RNG.

## Read the canonical implementation

The complete [adapter_finetuning.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/adapter_finetuning.py) supplies the operators and application helpers used above. This excerpt shows checkpoint storage:

```{literalinclude} ../../tutorials/adapter_finetuning.py
:language: python
:pyobject: save_checkpoint
```

Continue with [the tutorial collection](index.md) or [supported behavior and limitations](../reference/limits.md).
