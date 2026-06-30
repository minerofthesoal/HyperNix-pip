#!/usr/bin/env python3
"""
examples/resilient_finetune_v0_70_4.py

Demonstrates a resilient fine-tuning run using HyperNix v0.70.4, mixing
the newer safety/averaging modules (cake_pan.BakeOff, whisk.EMA) with the
original core modules (old_oven, old_fridge, freezer) that have been part
of HyperNix since the early releases.

What this does:
  1. Picks the right VRAM strategy for the current GPU (freezer — core).
  2. Loads a base model via the classic CodeOven wrapper (old_oven — core).
  3. Freezes the embedding layer to save memory (old_fridge — core).
  4. Tracks an EMA shadow copy of the weights during training (whisk — new).
  5. Wraps the actual training loop in BakeOff so a NaN, OOM, or wall-time
     limit rolls back to a clean state instead of corrupting the run
     (cake_pan — new).
  6. Applies the EMA shadow weights for the final, smoother checkpoint.

Run:
    python examples/resilient_finetune_v0_70_4.py \
        --dataset corpus.txt \
        --out-dir ./resilient-run \
        --steps 2000 --max-hours 3
"""

import argparse

from hypernix import freezer, old_oven, old_fridge
from hypernix.cake_pan import BakeOff
from hypernix.whisk import EMA


def parse_args():
    p = argparse.ArgumentParser(description="Resilient HyperNix fine-tune (v0.70.4)")
    p.add_argument("--repo-id", default="nix2.5", help="Base model short name or repo ID")
    p.add_argument("--dataset", required=True, help="Path to a plain-text training corpus")
    p.add_argument("--out-dir", default="./resilient-run", help="Output directory for checkpoints")
    p.add_argument("--steps", type=int, default=2000)
    p.add_argument("--max-hours", type=float, default=3.0, help="Wall-time budget for BakeOff")
    p.add_argument("--ema-decay", type=float, default=0.999)
    return p.parse_args()


def main():
    args = parse_args()

    # 1) Auto-pick a VRAM strategy. On a GTX 1080 this returns OldFreezer(fp16);
    #    on a newer card it returns NewFreezer with bf16/fp32 as appropriate.
    fz = freezer.flash_freezer(base=freezer.auto_freezer(), slow=True)

    # 2) Preheat an oven from a short name — downloads on first call, cached after.
    oven = old_oven.preheat(repo_id=args.repo_id, device="cuda", dtype="float16")
    fz.prepare(oven.model)

    # 3) Memory hygiene: freeze embeddings so they don't drift during fine-tuning.
    old_fridge.freeze(oven.model, patterns=("embed_tokens",))
    print("Parameter stats:", old_fridge.parameter_stats(oven.model))

    # 4) Set up EMA tracking — the shadow weights will usually generalise
    #    better than the raw live weights at the end of training.
    ema = EMA(oven.model, decay=args.ema_decay)

    # 5) Train inside BakeOff so a NaN, OOM, or wall-time limit rolls back to
    #    a clean state instead of corrupting the run. The dataset path is
    #    read by the model's own .train() loop.
    with BakeOff(oven.model, args.dataset, max_hours=args.max_hours) as run:
        for step in range(args.steps):
            loss = oven.train_step(args.dataset, step=step)
            ema.update(oven.model)

            if step % 100 == 0:
                print(f"step {step:>5} | loss {loss:.4f}")

    # 6) Swap in the EMA shadow weights for the final checkpoint and save.
    ema.apply_shadow(oven.model)
    oven.save_pt(f"{args.out_dir}/model-ema-final.pt")
    print(f"Done. EMA checkpoint saved to {args.out_dir}/model-ema-final.pt")


if __name__ == "__main__":
    main()
