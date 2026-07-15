# Pressure Cooker V5 / V5+ / V5S

## Overview

Pressure Cooker V5 is HyperNix's flagship optimizer, abandoning traditional AdamW mechanics entirely in favor of an **Oscillation Resistant Cosine Power (ORCP)** architecture, combining 6-bit quantized momentum, Quantization-Aware Training (QAT), and Multi-Token Prediction (MTP) support. V5+ extends V5 with automatic model transformation and quantization sensitivity analysis. V5S adds a third dimension of cosine similarity tracking (oscillation resistant cosin 3d), pressure diffusion, and lower memory usage.

## Features

### 6-Bit Quantized Momentum

Momentum buffers are quantized to 6-bit signed integers using stochastic rounding, reducing memory usage by ~75% compared to fp32 momentum while maintaining training stability.

```python
from hypernix.pressure_cooker_v5 import PressureCookerV5

cooker = PressureCookerV5(
    model.parameters(),
    peak_lr=2e-4,
    quantize_momentum=True,  # Enable 6-bit quantized momentum
)
```

### Quantization-Aware Training (QAT)

QAT simulates low-precision quantization during training so models learn to be robust to quantization error. Supports Q4, Q5, Q6, and Q8 bit widths.

```python
from hypernix.pressure_cooker_v5 import PressureCookerV5, QATConfig

# Basic QAT
qat_cfg = QATConfig(bits=6, per_layer=True)
cooker = PressureCookerV5(
    model.parameters(),
    qat_config=qat_cfg,
)
cooker.attach_qat(model)  # Attach fake quantization hooks

# Advanced QAT with learnable scales
qat_cfg = QATConfig(
    bits=4,
    per_layer=True,
    learnable_scales=True,
    dynamic_range=True,
    mixed_precision=True,  # Keep sensitive layers in fp16
)
```

### Multi-Token Prediction (MTP)

MTP trains models to predict multiple future tokens simultaneously, improving training efficiency by 1.5-3x.

```python
from hypernix.pressure_cooker_v5 import PressureCookerV5, MTPConfig

mtp_cfg = MTPConfig(num_tokens=4, lambda_weight=0.3, sequential=True)
cooker = PressureCookerV5(
    model.parameters(),
    enable_mtp=True,
    mtp_config=mtp_cfg,
)

# Get MTP head for your model
mtp_head = cooker.get_mtp_head(hidden_dim=768, vocab_size=32000)
```

### EMA Weight Shadowing

Track exponential moving averages of weights for evaluation:

```python
cooker = PressureCookerV5(model.parameters(), ema_decay=0.999)

# During training: EMA updates automatically

# For evaluation: swap to EMA weights
cooker.swap_ema_weights(model)
evaluate(model)
cooker.swap_ema_weights(model)  # Swap back
```

## GPU Tiers

| Tier | Class | Use Case | QAT | MTP |
|------|-------|----------|-----|-----|
| CPU T1 | StovetopCooker | Low-memory | Yes | No |
| CPU T2 | ElectricCooker | Multi-core | Yes | Yes |
| GPU T1 | InductionCooker | CUDA + AMP | Yes | Yes |
| GPU T2 | ProCooker | CUDA graphs | Yes | Yes |

## QAT Bit Width Comparison

| Bits | Levels | VRAM Overhead | Use Case |
|------|--------|--------------|----------|
| Q4 | 16 | 1.15x | Extreme compression |
| Q5 | 32 | 1.20x | Mobile/edge |
| Q6 | 64 | 1.25x | Balanced (default) |
| Q8 | 256 | 1.35x | Near-lossless |

## V5 vs V5+

| Feature | V5 | V5+ |
|---------|-----|-----|
| QAT | Manual hook attach | Auto `prepare_model()` |
| Mixed precision | Basic | Per-layer sensitivity |
| Gradient tracking | No | Norm monitoring |
| Sensitivity analysis | No | Built-in |
| Default EMA | 0 (off) | 0.999 |

## CLI

```bash
# Configure V5 with QAT and MTP
hnx pressure-cooker-v5 --tier V5 --qat 6 --mtp --epochs 10

# V5+ with full pipeline
hnx pressure-cooker-v5 --tier V5+ --qat 4 --mtp --mtp-tokens 4 --ema 0.999
```

## Integration with Freezer

```python
from hypernix import freezer
from hypernix.pressure_cooker_v5 import PressureCookerV5, QATConfig

fz = freezer.auto_freezer()
fz = freezer.flash_freezer(base=fz)

# QAT-aware batch sizing
bs = fz.suggest_qat_batch_size(bits=6, hint=8)

# Prepare model for QAT in freezer context
fz.prepare_for_qat(model, bits=6)
```
