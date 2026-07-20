"""Benchmark for Pressure Cooker v5."""
import time

import torch
import torch.nn as nn
from torch.optim import AdamW

from hypernix.pressure_cooker_v5 import PressureCookerV5


def run_benchmark():
    model = nn.Sequential(
        nn.Linear(2048, 2048),
        nn.ReLU(),
        nn.Linear(2048, 2048)
    ).cuda()
    
    opts = {
        "AdamW": AdamW(model.parameters(), lr=1e-3),
        "V5": PressureCookerV5(model.parameters(), lr=1e-3),
    }
    
    for name, opt in opts.items():
        torch.cuda.synchronize()
        start = time.perf_counter()
        for _ in range(100):
            opt.zero_grad()
            out = model(torch.randn(128, 2048, device='cuda'))
            loss = out.sum()
            loss.backward()
            opt.step()
        torch.cuda.synchronize()
        elapsed = time.perf_counter() - start
        print(f"{name} Time: {elapsed:.3f}s")

if __name__ == "__main__":
    run_benchmark()
