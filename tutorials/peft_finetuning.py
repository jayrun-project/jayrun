"""Optional real pretrained-model integration; requires transformers, peft, and downloads.

Example: python -m tutorials.peft_finetuning --model HuggingFaceTB/SmolLM2-135M \
    --revision main --device cuda --output peft_results
For reproduction, use the resolved immutable model revision recorded in result.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import torch
from tutorials.adapter_finetuning import (DATA, dataset_from_tokens, make_state,
    restore_checkpoint, run_training, save_checkpoint, validation_loss)


def run_pretrained(*, model_id: str, revision: str, output: Path, device: str = "cpu",
                   total_updates: int = 12, reservation_gb: float = 1.0,
                   resume: Path | None = None) -> dict[str, object]:
    # Optional imports do not affect the offline tutorials or core package dependencies.
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig, get_peft_model
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    base = AutoModelForCausalLM.from_pretrained(model_id, revision=revision, trust_remote_code=False)
    resolved = getattr(base.config, "_commit_hash", None)
    if not resolved:
        raise RuntimeError("could not determine the immutable model revision")
    tokenizer = AutoTokenizer.from_pretrained(model_id, revision=resolved, trust_remote_code=False)
    # Zero dropout keeps sampler RNG sufficient for this narrowly defined checkpoint recipe.
    for module in base.modules():
        if isinstance(module, torch.nn.Dropout):
            module.p = 0.0
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(7)
        model = get_peft_model(base, LoraConfig(r=4, lora_alpha=8, lora_dropout=0,
                                               target_modules="all-linear", task_type="CAUSAL_LM"))
    model.config.use_cache = False
    def tokenize(name: str) -> torch.Tensor:
        ids = tokenizer((DATA/name).read_text(), return_tensors="pt")["input_ids"][0]
        usable = (len(ids)//32)*32
        if usable < 32:
            raise ValueError("corpus must contain at least one 32-token sequence")
        return ids[:usable].reshape(-1, 32)
    dataset = dataset_from_tokens(tokenize("support_train.txt"), tokenize("support_validation.txt"))
    state = make_state(model, seed=7, identity={"model": model_id, "revision": resolved, "rank": 4})
    if resume is not None:
        restore_checkpoint(state, dataset, resume)
    before = validation_loss(state, dataset)
    state = run_training(state, dataset, total_updates=total_updates,
                         device=device, reservation_gb=reservation_gb)
    output.mkdir(parents=True, exist_ok=True)
    save_checkpoint(state, dataset, output/"training_checkpoint.pt")
    state.model.save_pretrained(output/"adapter")
    tokenizer.save_pretrained(output/"adapter")
    result = {"model": model_id, "revision": resolved, "dataset_sha256": dataset.fingerprint,
              "device": device, "updates": state.step, "examples_seen": state.examples_seen,
              "validation_loss_before": before, "validation_loss_after": validation_loss(state, dataset),
              "checkpoint_sha256": hashlib.sha256((output/"training_checkpoint.pt").read_bytes()).hexdigest(),
              "qualification": "small tutorial corpus; not a model-quality benchmark"}
    (output/"result.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="HuggingFaceTB/SmolLM2-135M")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--updates", type=int, default=12)
    parser.add_argument("--reservation-gb", type=float, default=1.0)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--output", type=Path, default=Path("peft_results"))
    args = parser.parse_args()
    torch.set_num_threads(1)
    print(json.dumps(run_pretrained(model_id=args.model, revision=args.revision,
        output=args.output, device=args.device, total_updates=args.updates,
        reservation_gb=args.reservation_gb, resume=args.resume), indent=2))
