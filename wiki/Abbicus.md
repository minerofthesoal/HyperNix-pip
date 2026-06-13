# Abbicus — `hypernix.abbicus`

Automatic token regulation and curriculum tuning during training. Dynamically
adjusts max sequence length and padding based on model size, dataset type,
and global step.

## Configuration

```python
from hypernix import Abbicus, AbbicusConfig

cfg = AbbicusConfig(
    model_size="7B",           # 0.5B … 72B — sets size multiplier
    base_context_length=4096,
    dataset_type="text",       # text | math | code
    curriculum_steps=10000,
    dynamic_padding=True,
)
abb = Abbicus(cfg)
```

## Training loop

```python
for step in range(steps):
    abb.step(step)
    batch = {"input_ids": ids, "labels": labels}
    batch = abb.regulate(batch)
    loss = model(batch["input_ids"], labels=batch["labels"])["loss"]
    ...
```

## Behaviour

- **Curriculum length** — starts at 25% of `base_context_length`, grows to
  `100% × size_multiplier` over `curriculum_steps`.
- **Math / code padding** — pads sequences to multiples of 8 for tensor-core
  efficiency when `dynamic_padding=True`.
- **Size multipliers** — smaller models (≤1B) use 0.5×; 70B+ uses 2.0×.

## Pairing

Use with `PressureCookerV3` / `instant_pot.brew()` and
[Compute Framework](Frameworks.md) for multi-GPU runs. For multi-round
datasets see [Tupperware](Tupperware.md).

See also: [Training.md](Training.md).
