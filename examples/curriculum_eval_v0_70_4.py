#!/usr/bin/env python3
"""
examples/curriculum_eval_v0_70_4.py

Demonstrates curriculum-mixed training data combined with dual-judge
evaluation in HyperNix v0.70.4, alongside the original `pans` preprocessing
pipeline and `table` inspection tool that have been part of HyperNix since
the earliest releases.

What this does:
  1. Cleans two raw datasets with the classic FryingPan + Skillet tiers
     (pans — core).
  2. Blends them with a staged curriculum schedule: mostly "easy" data
     early on, shifting toward "hard" data later in training
     (blender.HighPowerBlender — new).
  3. Runs a throwaway inference check with `microwave.zap` to eyeball the
     base model before training (microwave — core).
  4. After training, evaluates the result with DoubleShot, which
     cross-checks a scoring rubric against an independent judge model
     (espresso_maker.DoubleShot — new).
  5. Inspects the training log as a filterable table to find any steps
     where loss spiked (table — core).

Run:
    python examples/curriculum_eval_v0_70_4.py \
        --easy-data easy_corpus.txt \
        --hard-data hard_corpus.txt \
        --out-dir ./curriculum-run \
        --steps 3000
"""

import argparse

from hypernix import old_range
from hypernix.blender import HighPowerBlender
from hypernix.espresso_maker import DoubleShot
from hypernix.microwave import defrost, zap
from hypernix.old_oven import preheat
from hypernix.pans import FryingPan, Skillet
from hypernix.table import from_training_log


def parse_args():
    p = argparse.ArgumentParser(description="Curriculum training + dual-judge eval (v0.70.4)")
    p.add_argument("--repo-id", default="nix2.5", help="Base model short name or repo ID")
    p.add_argument("--judge-repo-id", default="nix2.5", help="Judge model for DoubleShot")
    p.add_argument("--easy-data", required=True, help="Path to easier training text")
    p.add_argument("--hard-data", required=True, help="Path to harder training text")
    p.add_argument("--out-dir", default="./curriculum-run")
    p.add_argument("--steps", type=int, default=3000)
    return p.parse_args()


EVAL_PROMPTS = [
    "Explain gradient descent in one sentence.",
    "What does a transformer's attention mechanism do?",
    "Summarize the purpose of a learning rate warmup.",
]


def load_lines(path):
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def main():
    args = parse_args()

    # 1) Clean both datasets through the classic preprocessing tiers.
    easy_raw = load_lines(args.easy_data)
    hard_raw = load_lines(args.hard_data)

    easy_clean = Skillet(FryingPan(easy_raw).process()).process(template="chatml")
    hard_clean = Skillet(FryingPan(hard_raw).process()).process(template="chatml")

    # 2) Build a curriculum: step 0 starts 100% easy, then gradually
    #    shifts toward harder data as training progresses.
    curriculum = [
        {0:    [1.0, 0.0]},
        {500:  [0.7, 0.3]},
        {1500: [0.4, 0.6]},
        {2500: [0.2, 0.8]},
    ]
    training_stream = HighPowerBlender(
        [easy_clean, hard_clean],
        weights=[1.0, 0.0],
        seed=42,
        curriculum=curriculum,
    )

    # 3) Quick sanity check on the base model before training starts.
    base_model = defrost(args.repo_id)
    print("Pre-training sample:", zap(base_model, EVAL_PROMPTS[0], max_tokens=64))

    # 4) Train (the oven's own loop reads from training_stream).
    oven = preheat(repo_id=args.repo_id, device="cuda", dtype="float16")
    oven.train(training_stream, args.out_dir, steps=args.steps, batch_size=1)

    # 5) Evaluate with a dual judge to cross-check the rubric score.
    judge_oven = preheat(repo_id=args.judge_repo_id, device="cuda", dtype="float16")
    results = DoubleShot(
        oven,
        EVAL_PROMPTS,
        rubric=old_range,
        judge=judge_oven,
    )
    print("Agreement rate between rubric and judge:", results.agreement_rate())

    # 6) Inspect the training log for any loss spikes worth investigating.
    with open(f"{args.out_dir}/train.log", encoding="utf-8") as f:
        log_text = f.read()
    t = from_training_log(log_text)
    print("Steps where loss exceeded 3.0:")
    t.filter(lambda r: r["loss"] > 3.0).select("step", "loss").show(n=10)


if __name__ == "__main__":
    main()
