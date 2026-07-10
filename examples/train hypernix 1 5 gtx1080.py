"""Train HyperNix 1.5 (~92.1 M params) on a GTX 1080 / Pascal (sm_61).

HyperNix 1.5 is a Llama-shaped, grouped-query, tied-embedding model sized
to fit AdamW training on an 8 GB Pascal card:

    hidden_size:        768
    intermediate_size: 1760   # SwiGLU MLP
    num_hidden_layers:   12
    num_attention_heads: 12
    num_key_value_heads:  4   # GQA 3:1
    max_position:       2048
    vocab_size:        32000
    tie_word_embeddings: True
    rope_theta:      500_000

At fp16 this is ~184 MB of weights + ~184 MB of grads + ~370 MB of
AdamW state + activations. With batch_size=1, context=1024 it trains
in under 7 GB on a GTX 1080.

-------------------------------------------------------------------------
CUDA 6.1 / Pascal install note
-------------------------------------------------------------------------
The stock PyPI wheels (CUDA 12.x) still compile for sm_60-sm_90 today,
but Pascal performance is best with the CUDA 11.8 toolchain. On a
GTX 1080 / 1080 Ti / Titan Xp / Titan X (Pascal) install torch like
this BEFORE installing hypernix::

    pip install --index-url https://download.pytorch.org/whl/cu118 torch
    pip install "hypernix>=0.70.4"

This example auto-detects compute capability 6.x at startup, forces
fp16 (not bf16 -- Pascal has no native bf16), disables torch.compile,
disables TF32, and uses the FlashFreezer OOM-safety wrapper so a run
that starts too big will throttle itself rather than die.

-------------------------------------------------------------------------
What's new in this revision (hypernix 0.70.4)
-------------------------------------------------------------------------
This version wires in 20 additional hypernix subsystems around the
same core training call, all opt-in via CLI flags unless noted:

  Pre-flight / environment
    apron          -- RNG-state guard; the whole run happens inside
                       ``with apron(seed=...)`` so nothing leaks into
                       the caller's global RNG state.
    doctor         -- environment diagnostic, printed once at start.
    plasma         -- quick on-card GPU benchmark used to calibrate a
                       realistic step-time estimate for *this* GPU.
    smoke_alarm    -- AutoAlarm turns the plasma benchmark into a
                       recommended step count / ETA for a wall-clock
                       budget (``--time-budget-minutes``).
    thermometer    -- samples GPU/CPU temperature before and after
                       the run (Pascal cards run hot under load).

  Data pipeline (on by default; disable with --no-data-pipeline)
    cutting_board  -- deterministic train/val split of the corpus.
    strainer       -- drops too-short/too-long/low-quality lines.
    salt_shaker    -- optional gentle augmentation (--augment).
    sink           -- rotating/deduping file writer used for the
                       augmented corpus and the training log.

  Training loop
    cake_pan       -- pre-flight VRAM margin check (layered under the
                       existing FlashFreezer, not a replacement).
    pressure_cooker-- device-tuned AdamW replacement, opt-in via
                       ``--optimizer pressure_cooker``.
    abbicus        -- curriculum-style context regulation
                       (``--use-abbicus`` / ``--use-turbo-abbicus``).
    stml           -- Short-Term-Memory-Loss context manager/estimator
                       (``--use-stml``), also used pre-flight to print
                       a VRAM-derived context-length suggestion.
    compute_framework -- hardware-agnostic device wrapper (single-GPU
                       no-op by default; ``--use-compute-framework``).
    timer          -- wall-clock elapsed/remaining display.

  Post-training
    whisk / compactor -- with ``--segment-checkpoints``, training runs
                       in ``--save-every``-sized segments that are
                       archived to disk; ``--ema`` averages them with
                       whisk, ``--compact-checkpoints`` zips the rest.
    dishwasher     -- optional cleanup of leftover run artifacts.
    table          -- final run-stats summary table.
    microwave      -- quick post-train smoke-test generation (zap).

-------------------------------------------------------------------------
Usage
-------------------------------------------------------------------------
    python examples/train_hypernix_1_5_gtx1080.py \\
        --dataset /path/to/raw_text.txt \\
        --tokenizer-source /path/to/snapshot_with_tokenizer \\
        --out-dir ./hypernix-1.5 \\
        --steps 2000 --batch-size 1 --context-length 1024

Add ``--synth`` to skip --dataset and use the mediocre_fridge synthetic
judge corpus instead (for a smoke test).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import shutil
import time
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
    # --- new in this revision (hypernix 0.70.4) ---
    abbicus,
    apron,
    cake_pan,
    compactor,
    compute_framework,
    cutting_board,
    dishwasher,
    doctor,
    microwave,
    plasma,
    pressure_cooker,
    salt_shaker,
    sink,
    smoke_alarm,
    stml,
    strainer,
    table,
    thermometer,
    timer,
    whisk,
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

    # --- data pipeline (apron / cutting_board / strainer / salt_shaker / sink) ---
    g = p.add_argument_group("data pipeline")
    g.add_argument("--no-data-pipeline", action="store_true",
                    help="Skip cutting_board/strainer/salt_shaker entirely "
                         "and train directly on --dataset as-is.")
    g.add_argument("--val-ratio", type=float, default=0.05,
                    help="Fraction of the corpus held out via cutting_board "
                         "(saved to disk, not trained on).")
    g.add_argument("--augment", action="store_true",
                    help="Run the cleaned train split through "
                         "salt_shaker.FromTheBag before training.")
    g.add_argument("--augment-rate", type=float, default=0.12)

    # --- pre-flight (doctor / plasma / smoke_alarm / thermometer) ---
    g = p.add_argument_group("pre-flight")
    g.add_argument("--skip-doctor", action="store_true",
                    help="Skip the hypernix.doctor environment diagnostic.")
    g.add_argument("--time-budget-minutes", type=float, default=None,
                    help="If set, benchmark this GPU with plasma and let "
                         "smoke_alarm pick --steps to fit the budget.")

    # --- training loop (pressure_cooker / abbicus / stml / compute_framework) ---
    g = p.add_argument_group("training loop")
    g.add_argument("--optimizer", choices=["adamw", "pressure_cooker"],
                    default="adamw")
    g.add_argument("--use-abbicus", action="store_true")
    g.add_argument("--use-turbo-abbicus", action="store_true")
    g.add_argument("--use-stml", action="store_true")
    g.add_argument("--use-compute-framework", action="store_true")

    # --- post-training (whisk / compactor / dishwasher / table / microwave) ---
    g = p.add_argument_group("post-training")
    g.add_argument("--segment-checkpoints", action="store_true",
                    help="Run training in --save-every-sized segments, "
                         "archiving a snapshot after each one. Required "
                         "for --ema / --compact-checkpoints to have "
                         "anything to work with. Resets optimizer "
                         "momentum at each segment boundary.")
    g.add_argument("--ema", action="store_true",
                    help="Average archived segment checkpoints with "
                         "whisk.ema() into an extra trained-ema/ snapshot.")
    g.add_argument("--ema-decay", type=float, default=0.99)
    g.add_argument("--compact-checkpoints", action="store_true",
                    help="Zip archived segment checkpoints with compactor.")
    g.add_argument("--clean", action="store_true",
                    help="Run dishwasher.wash() on --out-dir when done.")
    g.add_argument("--skip-smoke-test", action="store_true")
    g.add_argument("--smoke-test-prompt", default="def fibonacci(n):")

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


def _run_data_pipeline(dataset: Path, root: Path, ns: argparse.Namespace) -> Path:
    """cutting_board split -> strainer clean -> optional salt_shaker augment."""
    if ns.no_data_pipeline:
        return dataset

    splits_dir = root / "splits"
    board = cutting_board.CuttingBoard(
        train_ratio=max(0.01, 1.0 - ns.val_ratio),
        val_ratio=ns.val_ratio,
        test_ratio=0.0,
        seed=ns.seed,
    )
    split_paths = board.slice_to_files(dataset, splits_dir)
    train_path = split_paths.get("train", dataset)
    val_path = split_paths.get("val")
    val_note = f" val={val_path}" if val_path else ""
    print(f"[cutting_board] train={train_path}{val_note}")

    lines = train_path.read_text(encoding="utf-8").splitlines()
    mesh = strainer.FineMesh(min_length=4, max_length=4000)
    kept = mesh.filter(lines)
    cleaned = root / "train_clean.txt"
    cleaned.write_text("\n".join(kept) + "\n", encoding="utf-8")
    stats = mesh.stats()
    print(f"[strainer] kept={stats.kept} dropped={stats.dropped} "
          f"reasons={dict(stats.reasons)} -> {cleaned}")

    if ns.augment:
        shaker = salt_shaker.FromTheBag(source=cleaned, rate=ns.augment_rate, seed=ns.seed)
        aug_path = root / "train_augmented.txt"
        aug_sink = sink.Sink(aug_path, dedupe=True)
        n_written = 0
        for line in shaker:
            if aug_sink.write(line):
                n_written += 1
        aug_sink.close()
        print(f"[salt_shaker] rate={ns.augment_rate} wrote {n_written} lines -> {aug_path}")
        return aug_path

    return cleaned


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    root = Path(ns.out_dir)
    root.mkdir(parents=True, exist_ok=True)

    # ---- doctor: environment diagnostic, non-fatal ----
    if not ns.skip_doctor:
        code = doctor.run(fix=False)
        print(f"[doctor] environment check exit={code}"
              + (" (looks clean)" if code == 0 else " (see warnings above)"))

    _configure_for_pascal()

    with apron.apron(seed=ns.seed):
        return _run(ns, root)


def _run(ns: argparse.Namespace, root: Path) -> int:
    # 1) Pick the freezer pair: OldFreezer (8-10 GB) wrapped in a
    #    FlashFreezer so an unlucky batch won't bring the whole run
    #    down. On cards with >= 11 GB free VRAM auto_freezer() upgrades
    #    to NewFreezer and the hint cap goes away.
    base_fz = freezer.auto_freezer()
    fz = freezer.flash_freezer(base=base_fz, max_retries=5, backoff_s=2.0, slow=True)
    print(f"[freezer] base={base_fz.name} dtype={base_fz.preferred_dtype}")
    print("[freezer] wrapped with FlashFreezer (slow=True, max_retries=5)")
    print(f"[vram] {freezer.probe_vram()}")

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

    # ---- thermometer: reading before the run (Pascal cards run hot) ----
    therm = thermometer.DigitalThermometer(log_path=root / "thermometer.jsonl")
    with therm:
        reading_before = therm.read()
    print(f"[thermometer] before: gpu={reading_before.gpu_celsius} "
          f"cpu={reading_before.cpu_celsius}")

    oven = old_oven.preheat(local_dir=snap, device=dev, dtype=dtype_name)
    stats = old_fridge.parameter_stats(oven.model)
    print(f"[params] total={stats.total:,} "
          f"trainable={stats.trainable:,} "
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

    # ---- cake_pan: pre-flight VRAM margin check (layered under FlashFreezer) ----
    guard = cake_pan.cake_pan(model=oven.model, gpu_device=dev)
    if dev.startswith("cuda") and not guard.memory_guard():
        print("[cake_pan] WARNING: VRAM margin looks tight for this run; "
              "consider a smaller --batch-size or --context-length.")

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

    dataset = _run_data_pipeline(dataset, root, ns)

    # 4) Train. The training loop lives in CodeOven.train; we wrap the
    #    whole call in fz.guard so an OOM during step N pauses, frees
    #    cache, halves the batch size (if slow=True), and retries.
    trained = root / "trained"
    bs = fz.suggest_batch_size(hint=ns.batch_size)
    ctx = fz.suggest_context_length(hint=ns.context_length)
    if bs != ns.batch_size or ctx != ns.context_length:
        print(f"[freezer] clamped batch_size {ns.batch_size}->{bs}, "
              f"ctx {ns.context_length}->{ctx}")

    # ---- stml: VRAM-derived context suggestion (informational) ----
    vram_budget = freezer.probe_vram()
    vram_gb = vram_budget.free_gb if vram_budget.total else 8.0
    suggested_ctx = stml.calculate_vram_context(
        vram_gb=vram_gb, model_size_params=stats.total, batch_size=bs,
        precision=dtype_name, num_layers=cfg.num_hidden_layers,
        num_heads=cfg.num_attention_heads,
        head_dim=cfg.hidden_size // cfg.num_attention_heads,
    )
    print(f"[stml] VRAM-derived context suggestion: {suggested_ctx} "
          f"(using {ctx} from freezer)")

    # ---- plasma + smoke_alarm: calibrate a real ETA for this exact card ----
    bench = plasma.quick_benchmark(device=dev, seed=ns.seed)
    print(f"[plasma] {bench.tokens_per_sec:.0f} tok/s, {bench.step_ms:.1f} ms/step "
          f"(calibration on {bench.device})")

    time_budget_seconds = (
        ns.time_budget_minutes * 60.0 if ns.time_budget_minutes
        else ns.steps * max(bench.step_ms / 1000.0, 0.01)
    )
    alarm = smoke_alarm.auto_alarm(
        time_budget_seconds=time_budget_seconds,
        model_params=stats.total, context_length=ctx, batch_size=bs,
        gpu_name="GTX 1080",
    )
    plasma.calibrate_alarm(alarm, bench)
    budget = alarm.budget()
    print(f"[smoke_alarm] ~{budget.estimated_step_seconds:.3f}s/step -> "
          f"recommended {budget.recommended_steps} steps in "
          f"{time_budget_seconds:.0f}s budget")
    if ns.time_budget_minutes:
        ns.steps = budget.recommended_steps
        print(f"[smoke_alarm] --time-budget-minutes set; using --steps={ns.steps}")

    optimizer_class = pressure_cooker.PressureCooker if ns.optimizer == "pressure_cooker" else None
    cf = compute_framework.ComputeFramework() if ns.use_compute_framework else None

    log_buf = io.StringIO()
    kt = timer.timer("kitchen", duration=time_budget_seconds)
    kt.start()

    checkpoints_dir = root / "checkpoints"

    def _train_once(steps: int, save_every: int) -> Path:
        return oven.train(
            dataset, trained,
            steps=steps, batch_size=bs, context_length=ctx,
            lr=ns.lr, log_every=ns.log_every, save_every=save_every,
            seed=ns.seed, quiet=False,
            optimizer_class=optimizer_class,
            use_abbicus=ns.use_abbicus, use_turbo_abbicus=ns.use_turbo_abbicus,
            use_stml=ns.use_stml, segment_length=ctx,
            untrained_max_context=max(ctx * 4, ctx),
            compute_framework=cf,
        )

    def _run_training() -> Path:
        if not ns.segment_checkpoints:
            return _train_once(ns.steps, ns.save_every)

        # Segmented mode: run in --save-every-sized chunks, archiving a
        # copy of the snapshot after each one so whisk/compactor have
        # real checkpoint history to work with. Optimizer momentum and
        # the cosine LR schedule both restart at each segment boundary,
        # since CodeOven.train() builds a fresh optimizer per call.
        checkpoints_dir.mkdir(exist_ok=True)
        remaining = ns.steps
        completed = 0
        segment_size = max(1, min(ns.save_every, ns.steps))
        trained_dir = trained
        while remaining > 0:
            this_segment = min(segment_size, remaining)
            trained_dir = _train_once(this_segment, max(this_segment, 1))
            completed += this_segment
            remaining -= this_segment
            # compactor/whisk both identify checkpoints by name via regexes
            # like ``^step-(\d+)$`` -- hyphen, not underscore.
            archive = checkpoints_dir / f"step-{completed:06d}"
            shutil.copytree(trained_dir, archive, dirs_exist_ok=True)
            print(f"[checkpoints] archived step {completed}/{ns.steps} -> {archive}")
        return trained_dir

    with contextlib.redirect_stdout(_Tee(log_buf)):
        fz.guard(_run_training)

    log_sink = sink.Sink(root / "train.log", dedupe=False)
    log_sink.pour(log_buf.getvalue().splitlines())
    log_sink.close()
    print(f"[train] snapshot at {trained}")

    elapsed = kt.elapsed()
    status = alarm.check(elapsed_seconds=elapsed, completed_steps=ns.steps)
    print(f"[smoke_alarm] {status.message} "
          f"(on_pace={status.on_pace}, eta={status.eta_seconds:.1f}s)")

    # ---- whisk / compactor: only meaningful with --segment-checkpoints ----
    if ns.ema or ns.compact_checkpoints:
        if not ns.segment_checkpoints:
            print("[whisk/compactor] --ema/--compact-checkpoints needs "
                  "--segment-checkpoints (no archived checkpoints found); skipping.")
        else:
            archived = compactor.list_checkpoints(checkpoints_dir)
            # whisk wants the weight file itself (.safetensors/.pt), not
            # the HF-style snapshot directory compactor returns.
            weight_files = [d / "model.safetensors" for d in archived
                             if (d / "model.safetensors").exists()]
            if ns.ema:
                if len(weight_files) >= 2:
                    ema_dir = whisk.whisk_to_snapshot(
                        weight_files, root / "trained-ema",
                        tokenizer_source=snap, mode="ema", decay=ns.ema_decay,
                    )
                    print(f"[whisk] EMA(decay={ns.ema_decay}) over {len(weight_files)} "
                          f"checkpoints -> {ema_dir}")
                else:
                    print(f"[whisk] only {len(weight_files)} usable archived "
                          f"checkpoint(s); need >= 2 for EMA smoothing, skipping.")
            if ns.compact_checkpoints:
                archives = compactor.compact(
                    checkpoints_dir, keep_recent=2, fmt="zip", delete_originals=True,
                )
                print(f"[compactor] archived {len(archives)} old checkpoint(s) to zip")

    # 5) Reload from disk with the other oven to prove the round trip
    #    works, then free cache before plotting.
    reloaded = old_oven.preheat(local_dir=trained, device=dev, dtype=dtype_name)
    print(f"[old_oven] reloaded HyperNix 1.5 from {trained}; "
          f"config.hidden_size={reloaded.model.config.hidden_size}")
    old_fridge.chill_cache()

    # ---- thermometer: reading after the run ----
    with therm:
        reading_after = therm.read()
    print(f"[thermometer] after:  gpu={reading_after.gpu_celsius} "
          f"cpu={reading_after.cpu_celsius}")

    # ---- microwave: quick post-train smoke-test generation ----
    if not ns.skip_smoke_test:
        sample = microwave.zap(
            trained, ns.smoke_test_prompt, max_new_tokens=64,
            device=dev, dtype=dtype_name, seed=ns.seed,
        )
        print(f"[microwave] zap({ns.smoke_test_prompt!r}) -> {sample!r}")

    # 6) Graph.
    pairs = new_fridge.parse_training_log(log_buf.getvalue())
    if not ns.no_plot and pairs:
        png = root / "training_loss.png"
        new_fridge.plot_loss_curve(
            pairs, png, title=f"HyperNix 1.5 -- {stats.total/1e6:.1f}M params",
        )
        print(f"[new_fridge] loss curve -> {png}")
    elif pairs:
        print(f"[new_fridge] captured {len(pairs)} log points (plot skipped)")

    # ---- table: final run-stats summary ----
    summary = table.Table.from_rows([
        {"metric": "total_params", "value": f"{stats.total:,}"},
        {"metric": "trainable_params", "value": f"{stats.trainable:,}"},
        {"metric": "steps", "value": ns.steps},
        {"metric": "batch_size", "value": bs},
        {"metric": "context_length", "value": ctx},
        {"metric": "optimizer", "value": ns.optimizer},
        {"metric": "elapsed_seconds", "value": f"{elapsed:.1f}"},
        {"metric": "gpu_temp_before_c", "value": reading_before.gpu_celsius},
        {"metric": "gpu_temp_after_c", "value": reading_after.gpu_celsius},
        {"metric": "trained_dir", "value": str(trained)},
    ])
    print(summary.show())

    # ---- dishwasher: optional cleanup of leftover run artifacts ----
    if ns.clean:
        report = dishwasher.wash(tier="normal", root=str(root), keep_recent=2)
        print(f"[dishwasher] removed {len(report.files_removed)} file(s), "
              f"{len(report.dirs_removed)} dir(s), "
              f"freed {report.bytes_freed / 1e6:.1f} MB")

    print(f"\nDone. HyperNix 1.5 at {trained} ({stats.total:,} params)")
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
