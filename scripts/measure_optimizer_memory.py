"""Measure exact optimizer-state memory footprint for AdamW vs PressureCooker
V5 vs V5S vs V6, per parameter tensor.

This does not estimate or guess -- it instantiates each real optimizer,
runs one backward + step so every state tensor actually gets allocated
(lazy per-parameter state in PyTorch optimizers only materializes on first
``step()``), then sums the exact byte size (``nelement() * element_size()``)
of every tensor stored in ``optimizer.state[param]``.

Runs entirely on CPU -- optimizer *state* memory does not depend on the
device (a quantized int8 buffer is the same number of bytes on CPU or
CUDA), so this is a faithful, device-independent measurement of the thing
the PressureCooker V5/V5S docstrings make claims about.
"""
from __future__ import annotations

import torch
import torch.nn as nn
from torch.optim import AdamW

from hypernix.pressure_cooker_v5 import PressureCookerV5
from hypernix.pressure_cooker_v5s import PressureCookerV5S
from hypernix.pressure_cooker_v6 import PressureCookerV6

SEED = 0


def _state_bytes(opt: torch.optim.Optimizer) -> int:
    total = 0
    for state in opt.state.values():
        for v in state.values():
            if torch.is_tensor(v):
                total += v.nelement() * v.element_size()
    return total


def _param_bytes(model: nn.Module) -> int:
    return sum(p.nelement() * p.element_size() for p in model.parameters())


def _run_one_step(model: nn.Module, opt: torch.optim.Optimizer, batch: int, in_dim: int) -> None:
    torch.manual_seed(SEED + 1)
    x = torch.randn(batch, in_dim)
    opt.zero_grad(set_to_none=True)
    loss = model(x).pow(2).mean()
    loss.backward()
    opt.step()


def measure(hidden: int, batch: int = 32) -> list[dict]:
    configs = {
        "AdamW": lambda m: AdamW(m.parameters(), lr=1e-3),
        "PressureCookerV5": lambda m: PressureCookerV5(m.parameters(), lr=1e-3),
        "PressureCookerV5S": lambda m: PressureCookerV5S(m.parameters(), lr=1e-3),
        "PressureCookerV6": lambda m: PressureCookerV6(m.parameters(), lr=1e-3),
    }
    rows = []
    for name, make_opt in configs.items():
        torch.manual_seed(SEED)
        model = nn.Sequential(nn.Linear(hidden, hidden), nn.ReLU(), nn.Linear(hidden, hidden))
        opt = make_opt(model)
        _run_one_step(model, opt, batch, hidden)
        pbytes = _param_bytes(model)
        sbytes = _state_bytes(opt)
        rows.append({
            "name": name,
            "hidden": hidden,
            "param_bytes": pbytes,
            "state_bytes": sbytes,
            "state_over_param": sbytes / pbytes,
        })
    return rows


def main() -> None:
    print(f"{'optimizer':18s} {'hidden':>8s} {'param MB':>10s} {'state MB':>10s} {'state/param':>12s}")
    baseline = None
    for hidden in (1024, 2048, 4096):
        rows = measure(hidden)
        for r in rows:
            if r["name"] == "AdamW":
                baseline = r["state_bytes"]
            rel = r["state_bytes"] / baseline if baseline else float("nan")
            print(
                f"{r['name']:18s} {r['hidden']:8d} "
                f"{r['param_bytes'] / 1024**2:10.2f} "
                f"{r['state_bytes'] / 1024**2:10.2f} "
                f"{r['state_over_param']:11.3f}x  "
                f"(AdamW-state x{rel:.3f})"
            )
        print()


if __name__ == "__main__":
    main()
