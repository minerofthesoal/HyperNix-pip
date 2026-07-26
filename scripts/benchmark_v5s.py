"""Benchmark for Pressure Cooker V5S vs V5 vs AdamW.

Same methodology as ``benchmark_v5.py``: each optimizer trains its own
freshly-initialized, identically-seeded model copy (never a model already
mutated by a previous optimizer in the loop), runs on CUDA when available
and CPU otherwise, and reports both step latency and peak memory.
"""
from __future__ import annotations

import time

import torch
import torch.nn as nn
from hypernix.pressure_cooker_v5 import PressureCookerV5
from hypernix.pressure_cooker_v5s import PressureCookerV5S
from torch.optim import AdamW

N_STEPS = 100
BATCH_SIZE = 128
HIDDEN = 1024
SEED = 0


def _make_model(device: torch.device) -> nn.Module:
    torch.manual_seed(SEED)
    return nn.Sequential(
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
    print(f"[benchmark_v5s] device={device}, steps={N_STEPS}, "
          f"batch={BATCH_SIZE}, hidden={HIDDEN}")

    configs = {
        "AdamW": lambda m: AdamW(m.parameters(), lr=1e-3),
        "PressureCookerV5": lambda m: PressureCookerV5(m.parameters(), lr=1e-3),
        "PressureCookerV5S": lambda m: PressureCookerV5S(m.parameters(), lr=1e-3),
    }

    results = [_bench_one(name, make_opt, device) for name, make_opt in configs.items()]
    for r in results:
        mem = f"{r['peak_mem_mb']:.1f} MB" if device.type == "cuda" else "n/a (CPU)"
        print(
            f"{r['name']:18s} total={r['elapsed_s']:.3f}s  "
            f"per_step={r['ms_per_step']:.3f}ms  peak_mem={mem}  "
            f"final_loss={r['final_loss']:.4f}"
        )
    return results


if __name__ == "__main__":
    run_benchmark()
