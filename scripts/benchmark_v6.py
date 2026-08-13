"""Benchmark for Pressure Cooker V6 vs AdamW vs PressureCooker V5.

Each optimizer gets its own freshly-initialized, identically-seeded copy of
the model so results are a fair apples-to-apples comparison rather than
optimizers training sequentially on top of each other's already-updated
weights. Runs on CUDA when available and falls back to CPU otherwise, so
the script is runnable on any machine -- results are of course only
representative of the device actually used (the printed device is always
reported alongside the numbers, and CPU numbers should NOT be read as a
prediction of GPU speedup: V6's whole design bet -- fewer host<->device
syncs, fused multi-tensor kernels -- only pays off on a device where
kernel-launch/sync overhead is actually the bottleneck, which is far more
true on GPU than CPU). Also includes PressureCookerV6V when a CUDA device
is available, since it requires one.
"""
from __future__ import annotations

import time

import torch
import torch.nn as nn
from torch.optim import AdamW

from hypernix.pressure_cooker_v5 import PressureCookerV5
from hypernix.pressure_cooker_v6 import PressureCookerV6

N_STEPS = 100
BATCH_SIZE = 128
HIDDEN = 2048
SEED = 0


def _make_model(device: torch.device) -> nn.Module:
    torch.manual_seed(SEED)
    return nn.Sequential(
        nn.Linear(HIDDEN, HIDDEN),
        nn.ReLU(),
        nn.Linear(HIDDEN, HIDDEN),
        nn.ReLU(),
        nn.Linear(HIDDEN, HIDDEN),
    ).to(device)


def _bench_one(name: str, make_opt, device: torch.device) -> dict:
    model = _make_model(device)
    opt = make_opt(model)

    torch.manual_seed(SEED + 1)
    inputs = [
        torch.randn(BATCH_SIZE, HIDDEN, device=device) for _ in range(N_STEPS)
    ]

    # A few untimed warmup steps so lazy state init / kernel autotuning
    # doesn't get charged to the timed loop.
    for x in inputs[: min(5, N_STEPS)]:
        opt.zero_grad(set_to_none=True)
        loss = model(x).pow(2).mean()
        loss.backward()
        opt.step()
    if device.type == "cuda":
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats(device)

    start = time.perf_counter()
    for x in inputs:
        opt.zero_grad(set_to_none=True)
        out = model(x)
        loss = out.pow(2).mean()
        loss.backward()
        opt.step()
    if device.type == "cuda":
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - start

    peak_mem_mb = (
        torch.cuda.max_memory_allocated(device) / (1024 ** 2)
        if device.type == "cuda"
        else float("nan")
    )
    return {
        "name": name,
        "elapsed_s": elapsed,
        "ms_per_step": (elapsed / N_STEPS) * 1000,
        "peak_mem_mb": peak_mem_mb,
        "final_loss": float(loss.detach()),
    }


def run_benchmark() -> list[dict]:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[benchmark_v6] device={device}, steps={N_STEPS}, "
          f"batch={BATCH_SIZE}, hidden={HIDDEN}")
    if device.type != "cuda":
        print("[benchmark_v6] NOTE: no CUDA device available -- these are "
              "CPU numbers. V6's fused/foreach design targets GPU "
              "kernel-launch overhead specifically; do not extrapolate "
              "these ratios to GPU performance. Re-run on CUDA hardware "
              "for numbers that actually mean something for training.")

    configs = {
        "AdamW": lambda m: AdamW(m.parameters(), lr=1e-3),
        "PressureCookerV5": lambda m: PressureCookerV5(m.parameters(), lr=1e-3),
        "PressureCookerV6": lambda m: PressureCookerV6(m.parameters(), lr=1e-3),
    }
    if device.type == "cuda":
        from hypernix.pressure_cooker_v6v import PressureCookerV6V
        configs["PressureCookerV6V"] = lambda m: PressureCookerV6V(m.parameters(), lr=1e-3)

    results = [_bench_one(name, make_opt, device) for name, make_opt in configs.items()]
    baseline_ms = next(r["ms_per_step"] for r in results if r["name"] == "AdamW")
    for r in results:
        mem = f"{r['peak_mem_mb']:.1f} MB" if device.type == "cuda" else "n/a (CPU)"
        speedup = baseline_ms / r["ms_per_step"]
        print(
            f"{r['name']:20s} total={r['elapsed_s']:.3f}s  "
            f"per_step={r['ms_per_step']:.3f}ms  vs_adamw={speedup:.2f}x  "
            f"peak_mem={mem}  final_loss={r['final_loss']:.4f}"
        )
    return results


if __name__ == "__main__":
    run_benchmark()
