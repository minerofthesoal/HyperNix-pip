"""Train HyperNix 1.5 (~92.1 M params) on a GTX 1080 / Pascal (sm_61).

HyperNix 1.5 is a Llama-shaped, grouped-query, tied-embedding model sized
to fit AdamW training on an 8 GB Pascal card:

    hidden_size:          768
    intermediate_size:    1760   # SwiGLU MLP
    num_hidden_layers:    12
    num_attention_heads:  12
    num_key_value_heads:  4      # GQA 3:1
    max_position:         2048
    vocab_size:           32000
    tie_word_embeddings:  True
    rope_theta:           500_000

At fp16 this is ~184 MB of weights + ~184 MB of grads + ~370 MB of
AdamW state + activations.  With batch_size=1, context=1024 it trains
in under 7 GB on a GTX 1080.

-------------------------------------------------------------------------
CUDA 6.1 / Pascal install note
-------------------------------------------------------------------------
The stock PyPI wheels (CUDA 12.x) still compile for sm_60-sm_90 today,
but Pascal performance is best with the CUDA 11.8 toolchain.  On a
GTX 1080 / 1080 Ti / Titan Xp / Titan X (Pascal) install torch like
this BEFORE installing hypernix::

    pip install --index-url https://download.pytorch.org/whl/cu118 torch
    pip install hypernix

This example auto-detects compute capability 6.x at startup, forces
fp16 (not bf16 — Pascal has no native bf16), disables torch.compile,
disables TF32, and uses the FlashFreezer OOM-safety wrapper so a run
that starts too big will throttle itself rather than die.

-------------------------------------------------------------------------
Usage
-------------------------------------------------------------------------

    python examples/train_hypernix_1_5_gtx1080.py \
        --dataset /path/to/raw_text.txt \
        --tokenizer-source /path/to/snapshot_with_tokenizer \
        --out-dir ./hypernix-1.5 \
        --steps 2000 --batch-size 1 --context-length 1024

Add ``--synth`` to skip --dataset and use the mediocre_fridge synthetic
judge corpus instead (for a smoke test).
"""
from __future__ import annotations

import argparse
import contextlib
import io
from pathlib import Path

import torch

from hypernix import (
    HyperNixConfig,
    freezer,
    init_from_scratch,
    mediocre_fridge,
    new_fridge,
    old_fridge,
    old_oven,
)

HYPERNIX_1_5 = HyperNixConfig(
    vocab_size=32000,
    hidden_size=768,
    intermediate_size=1760,
    num_hidden_layers=12,
    num_attention_heads=12,
    num_key_value_heads=4,
    max_position_embeddings=2048,
    rope_theta=500_000.0,
    tie_word_embeddings=True,
    model_type="hypernix",
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Train HyperNix 1.5 (~92.1M) on an 8 GB Pascal GPU."
    )
    p.add_argument("--out-dir", default="./hypernix-1.5")
    p.add_argument("--dataset", default=None,
                   help="Path to a raw-text training file.")
    p.add_argument("--synth", action="store_true",
                   help="Use mediocre_fridge.synthesize_judge_corpus "
                        "instead of a real dataset (smoke test).")
    p.add_argument("--synth-size", type=int, default=2048)
    p.add_argument("--tokenizer-source", default=None,
                   help="Snapshot directory to copy tokenizer.json from. "
                        "If omitted, the byte tokenizer is used and "
                        "vocab_size is clamped to 256.")
    p.add_argument("--steps", type=int, default=2000)
    p.add_argument("--batch-size", type=int, default=1)
    p.add_argument("--context-length", type=int, default=1024)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--log-every", type=int, default=10)
    p.add_argument("--save-every", type=int, default=500)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--freeze-embed", action="store_true",
                   help="Freeze token embeddings (cheap fine-tune mode).")
    p.add_argument("--device", default=None)
    p.add_argument("--no-plot", action="store_true")
    return p


def _configure_for_pascal() -> dict[str, object]:
    """Print detected compute capability; return pascal_mode_hints() dict."""
    cc = freezer.compute_capability()
    if cc is None:
        print("[pascal] no CUDA device detected; running on CPU")
        return freezer.pascal_mode_hints()

    major, minor = cc
    if freezer.is_pascal():
        print(f"[pascal] detected sm_{major}{minor} (Pascal). "
              f"Forcing fp16, disabling SDPA/compile/TF32.")
        # Disable TF32 globally (no-op on Pascal, but defensive).
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
    else:
        print(f"[pascal] detected sm_{major}{minor}; no Pascal-specific tweaks needed.")
    return freezer.pascal_mode_hints()


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    root = Path(ns.out_dir)
    root.mkdir(parents=True, exist_ok=True)

    _configure_for_pascal()

    # 1) Pick the freezer pair: OldFreezer (8-10 GB) wrapped in a
    #    FlashFreezer so an unlucky batch won't bring the whole run
    #    down. On cards with >= 11 GB free VRAM auto_freezer() upgrades
    #    to NewFreezer and the hint cap goes away.
    base_fz = freezer.auto_freezer()
    fz = freezer.flash_freezer(base=base_fz, max_retries=5, backoff_s=2.0, slow=True)
    print(f"[freezer] base={base_fz.name} dtype={base_fz.preferred_dtype}")
    print("[freezer] wrapped with FlashFreezer (slow=True, max_retries=5)")
    print(f"[vram]    {freezer.probe_vram()}")

    # 2) Build the 92.1M-param snapshot from scratch. If the caller
    #    didn't give us a tokenizer source, fall back to the byte
    #    tokenizer and clamp vocab_size=256 so the embedding matrix
    #    matches the byte range 0..255.
    cfg = HyperNixConfig(**{**HYPERNIX_1_5.__dict__})
    if ns.tokenizer_source is None:
        cfg.vocab_size = 256
        print("[init] no tokenizer source; falling back to byte tokenizer "
              "(vocab_size=256).")
    snap = root / "scratch"
    init_from_scratch(
        snap, cfg, tokenizer_source=ns.tokenizer_source, seed=ns.seed,
    )
    print(f"[init] fresh HyperNix 1.5 snapshot at {snap}")

    dev = ns.device or ("cuda" if torch.cuda.is_available() else "cpu")
    dtype_name = _dtype_to_name(base_fz.preferred_dtype)
    oven = old_oven.preheat(local_dir=snap, device=dev, dtype=dtype_name)
    stats = old_fridge.parameter_stats(oven.model)
    print(f"[params]  total={stats.total:,}  "
          f"trainable={stats.trainable:,}  "
          f"size(fp32 equiv)={stats.megabytes:.1f} MB")
    if cfg.vocab_size == HYPERNIX_1_5.vocab_size:
        # With the production 32k-BPE vocab we hit the nominal 92.1M. The
        # byte-fallback path (vocab=256) shaves ~24M off the embedding and
        # lands around 68M, which is still a useful smoke test but not
        # "HyperNix 1.5".
        assert 90_000_000 < stats.total < 95_000_000, (
            f"expected ~92.1M params, got {stats.total:,}"
        )

    if ns.freeze_embed:
        old_fridge.freeze(oven.model, patterns=("embed_tokens",))
        new_stats = old_fridge.parameter_stats(oven.model)
        print(f"[old_fridge] froze embed_tokens; trainable now {new_stats.trainable:,}")

    # 3) Dataset: real file or synthesized judge corpus.
    if ns.synth:
        dataset = root / "synth_corpus.txt"
        mediocre_fridge.synthesize_judge_corpus(
            n=ns.synth_size, out_path=dataset, seed=ns.seed,
        )
        print(f"[mediocre_fridge] wrote {ns.synth_size} synthetic examples -> {dataset}")
    else:
        if ns.dataset is None:
            raise SystemExit("either --dataset PATH or --synth is required")
        dataset = Path(ns.dataset)
        if not dataset.exists():
            raise SystemExit(f"--dataset {dataset} does not exist")

    # 4) Train. The training loop lives in CodeOven.train; we wrap the
    #    whole call in fz.guard so an OOM during step N pauses, frees
    #    cache, halves the batch size (if slow=True), and retries.
    trained = root / "trained"
    bs = fz.suggest_batch_size(hint=ns.batch_size)
    ctx = fz.suggest_context_length(hint=ns.context_length)
    if bs != ns.batch_size or ctx != ns.context_length:
        print(f"[freezer] clamped batch_size {ns.batch_size}->{bs}, "
              f"ctx {ns.context_length}->{ctx}")

    log_buf = io.StringIO()

    def _run_training():
        return oven.train(
            dataset, trained,
            steps=ns.steps, batch_size=bs, context_length=ctx,
            lr=ns.lr, log_every=ns.log_every, save_every=ns.save_every,
            seed=ns.seed, quiet=False,
        )

    with contextlib.redirect_stdout(_Tee(log_buf)):
        fz.guard(_run_training)
    (root / "train.log").write_text(log_buf.getvalue(), encoding="utf-8")
    print(f"[train] snapshot at {trained}")

    # 5) Reload from disk with the other oven to prove the round trip
    #    works, then free cache before plotting.
    reloaded = old_oven.preheat(local_dir=trained, device=dev, dtype=dtype_name)
    print(f"[old_oven] reloaded HyperNix 1.5 from {trained}; "
          f"config.hidden_size={reloaded.model.config.hidden_size}")
    old_fridge.chill_cache()

    # 6) Graph.
    pairs = new_fridge.parse_training_log(log_buf.getvalue())
    if not ns.no_plot and pairs:
        png = root / "training_loss.png"
        new_fridge.plot_loss_curve(
            pairs, png, title=f"HyperNix 1.5 — {stats.total/1e6:.1f}M params",
        )
        print(f"[new_fridge] loss curve -> {png}")
    elif pairs:
        print(f"[new_fridge] captured {len(pairs)} log points (plot skipped)")

    print(f"\nDone. HyperNix 1.5 at {trained}  ({stats.total:,} params)")
    return 0


_DTYPE_NAMES = {
    torch.float16: "float16",
    torch.bfloat16: "bfloat16",
    torch.float32: "float32",
}


def _dtype_to_name(dt) -> str:
    return _DTYPE_NAMES.get(dt, "float16")


class _Tee:
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
