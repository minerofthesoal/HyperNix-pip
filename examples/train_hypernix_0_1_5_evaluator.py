"""Train HyperNix 0.1.5 — an evaluator that judges other models' outputs.

This example ties together every top-level pipe the package exposes:

* ``new_oven``            — spin up a fresh HyperNix 0.1.5 from scratch.
* ``mediocre_fridge``     — synthesize a small judge-training corpus of
                            ``<JUDGE_PROMPT>...<JUDGE_RESPONSE>...<JUDGE_LABEL>GOOD/BAD``
                            examples.
* ``old_fridge``          — freeze the token embedding and count how many
                            parameters are left trainable, then chill the
                            allocator cache.
* ``oven.train``          — run a short training loop on the judge corpus.
* ``old_oven.preheat``    — reload the trained snapshot as a ready-to-use
                            ``CodeOven`` so you can actually ask it to
                            judge things.
* ``new_fridge``          — parse the training stdout into (step, loss)
                            pairs and save a PNG of the loss curve.

The model produced here is a toy. The byte tokenizer and tiny hidden
size make it unfit for serious evaluation work — the point is the
end-to-end shape of the pipeline, which is identical when you scale up
to a real model.

Run it from a checkout with::

    python examples/train_hypernix_0_1_5_evaluator.py --out-dir ./hypernix-0.1.5

Add ``--skip-plot`` to avoid the matplotlib install when running on a
machine where you can't reach PyPI.
"""
from __future__ import annotations

import argparse
import contextlib
import io
from pathlib import Path

from hypernix import (
    HyperNixConfig,
    init_from_scratch,
    mediocre_fridge,
    new_fridge,
    old_fridge,
    old_oven,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Train HyperNix 0.1.5, a tiny evaluator model."
    )
    p.add_argument("--out-dir", default="./hypernix-0.1.5",
                   help="Directory to write the trained snapshot into.")
    p.add_argument("--dataset-size", type=int, default=256,
                   help="Number of judge examples to synthesize.")
    p.add_argument("--steps", type=int, default=80)
    p.add_argument("--batch-size", type=int, default=2)
    p.add_argument("--context-length", type=int, default=64)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--skip-plot", action="store_true",
                   help="Don't call new_fridge.plot_loss_curve (avoids "
                        "pulling in matplotlib).")
    return p


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    root = Path(ns.out_dir)
    root.mkdir(parents=True, exist_ok=True)

    # 1) new_oven: stand up HyperNix 0.1.5 from a minimal, deliberately
    #    small shape so this example runs on a laptop CPU.
    snap = root / "scratch"
    cfg = HyperNixConfig(
        vocab_size=256,
        hidden_size=32,
        intermediate_size=64,
        num_hidden_layers=2,
        num_attention_heads=4,
        num_key_value_heads=2,
        max_position_embeddings=128,
        rope_theta=10000.0,
        tie_word_embeddings=True,
        model_type="hypernix",
    )
    init_from_scratch(snap, cfg, tokenizer_source=None, seed=ns.seed)
    print(f"[new_oven] fresh HyperNix 0.1.5 snapshot at {snap}")

    # 2) mediocre_fridge: build the judge-training corpus. Roughly half
    #    the examples keep the reference answer (labelled GOOD); the
    #    rest are mangled (labelled BAD).
    dataset = root / "judge_corpus.txt"
    mediocre_fridge.synthesize_judge_corpus(
        n=ns.dataset_size, out_path=dataset, seed=ns.seed, good_ratio=0.5,
    )
    print(f"[mediocre_fridge] wrote {ns.dataset_size} judge examples -> {dataset}")

    # 3) old_fridge: preheat the oven so we can inspect parameters,
    #    then freeze the token embedding and print the param split.
    oven = old_oven.preheat(local_dir=snap, device="cpu")
    frozen = old_fridge.freeze(oven.model, patterns=("embed_tokens",))
    stats = old_fridge.parameter_stats(oven.model)
    print(f"[old_fridge] froze {frozen:,} params in embed_tokens")
    print(
        f"[old_fridge] total={stats.total:,}  trainable={stats.trainable:,}"
        f"  frozen={stats.frozen:,}  size={stats.megabytes:.2f} MB"
    )
    old_fridge.chill_cache()

    # 4) oven.train: run a short training loop on the judge corpus.
    #    Capture stdout so new_fridge can parse the step/loss line.
    trained = root / "trained"
    log_buf = io.StringIO()
    tee = _Tee(log_buf)
    with contextlib.redirect_stdout(tee):
        oven.train(
            dataset, trained,
            steps=ns.steps, batch_size=ns.batch_size,
            context_length=ns.context_length,
            lr=3e-4, log_every=max(1, ns.steps // 20),
            save_every=0, seed=ns.seed, quiet=False,
        )
    (root / "train.log").write_text(log_buf.getvalue(), encoding="utf-8")
    print(f"[train] snapshot at {trained}")

    # 5) old_oven: reload the trained snapshot as a ready-to-use
    #    CodeOven. This is the same API a downstream caller would use.
    judge = old_oven.preheat(local_dir=trained, device="cpu")
    print(f"[old_oven] reloaded judge from {trained}")

    # Demo: ask the judge to continue a well-formed (prompt, response)
    # header. We don't expect a tiny byte-tokenizer model trained for
    # ~80 steps to actually learn the GOOD/BAD mapping — it's enough
    # to show the shape of the API.
    demo_prompt = (
        f"{mediocre_fridge.JUDGE_PROMPT}Capital of France?"
        f"{mediocre_fridge.JUDGE_RESPONSE}Paris"
        f"{mediocre_fridge.JUDGE_LABEL}"
    )
    continuation = judge.complete(
        demo_prompt, max_new_tokens=4, temperature=0.0, stop=(), seed=ns.seed,
    )
    print(f"[judge] demo continuation for a GOOD example: {continuation!r}")

    # 6) new_fridge: graph the training curve.
    pairs = new_fridge.parse_training_log(log_buf.getvalue())
    if not ns.skip_plot and pairs:
        png = root / "training_loss.png"
        new_fridge.plot_loss_curve(pairs, png, title="HyperNix 0.1.5 judge loss")
        print(f"[new_fridge] loss curve -> {png}")
    elif pairs:
        print(f"[new_fridge] captured {len(pairs)} log points (plot skipped)")
    else:
        print("[new_fridge] no (step, loss) lines parsed from the training log")

    print(f"\nDone. HyperNix 0.1.5 evaluator at {trained}")
    return 0


class _Tee:
    """Write stream that forwards to stdout *and* an in-memory buffer."""

    def __init__(self, buf: io.StringIO) -> None:
        import sys
        self._stdout = sys.stdout
        self._buf = buf

    def write(self, s: str) -> int:
        self._buf.write(s)
        return self._stdout.write(s)

    def flush(self) -> None:
        self._stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
