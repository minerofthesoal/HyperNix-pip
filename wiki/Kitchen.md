# Kitchen — pans, microwave, table, sink, instant pot, coffee maker, pressure cooker

Seven modules added in v0.44, all following the same kitchen idiom
that started with the oven. They cover the bits of the lifecycle the
oven / fridge / freezer trio didn't: data preprocessing, one-shot
inference, training-log inspection, file output, end-to-end pipelines,
scheduled repetition, and a custom training optimizer.

| Module | What it does |
|---|---|
| [`pans`](#pans) | 5-tier preprocessing pipeline: FryingPan → SaucePan → Skillet → GrillPan → Wok. |
| [`microwave`](#microwave) | One-shot throwaway inference: `zap(repo_or_dir, prompt)`. |
| [`table`](#table) | Dead-simple tabular viewer over training logs and judge corpora. |
| [`sink`](#sink) | Append-only file output with optional rotation + dedupe. |
| [`instant_pot`](#instant_pot) | One-call end-to-end pipeline: preheat → train → optional GGUF. |
| [`coffee_maker`](#coffee_maker) | Scheduled / repeated brews with exception capture. |
| [`pressure_cooker`](#pressure_cooker) | AdamW + warmup / plateau / cooldown + lookahead. |

## pans

Five tiers of text preprocessing, progressively more opinionated.
Each pan reads from a file, path, or any iterable of strings and
yields processed strings.

```python
from hypernix import pans

# Tier 1 — verbatim, trim trailing whitespace.
for line in pans.FryingPan("corpus.txt"):
    ...

# Tier 2 — collapse internal whitespace, drop empties.
pans.SaucePan("corpus.txt")

# Tier 3 — wrap each line with chat or instruct tags.
pans.Skillet("corpus.txt", mode="chat")
pans.Skillet("corpus.txt", mode="instruct")

# Tier 4 — SaucePan + SHA1 deduplication + min-length filter.
pans.GrillPan("corpus.txt", min_chars=8)

# Tier 5 — buffer + shuffle + optional reverse-order augmentation.
pans.Wok("corpus.txt", seed=0, reverse_ratio=0.1)
```

Pick by name when the tier is a runtime variable:

```python
pans.pick_pan("grill-pan", source="corpus.txt", min_chars=16)
```

Pair with the sink to persist the output:

```python
from hypernix import pans, sink
sink.Sink("clean.txt").pour(pans.GrillPan("raw.txt", min_chars=8))
```

## microwave

One-shot throwaway inference. Preheats an oven, generates, tears it
down. Don't use in a loop — rebuild cost is meaningful; preheat a
`CodeOven` once and call `.complete()` repeatedly instead.

```python
from hypernix import microwave

out = microwave.zap("nix2.5", "def fib(n):", max_new_tokens=64)
print(out)

# Single-turn chat companion:
reply = microwave.chat_zap("nix2.5", "Capital of France?",
                           system="You are terse.")
```

Accepts short names, full HF repo ids, or a local snapshot directory.

## table

Minimal tabular viewer over a list of dicts. Two canned constructors
load the two log types `hypernix` itself produces; the rest is
`.head()` / `.filter()` / `.select()` / `.sort_by()` / `.show()`.

```python
from hypernix.table import Table

# Training log
t = Table.from_training_log("train.log")
print(t.show(10))

# Judge corpus (mediocre_fridge.synthesize_judge_corpus output)
c = Table.from_judge_corpus("judge.txt")
bad = c.filter(lambda r: r["label"] == "BAD")
print(bad.select("prompt", "response").show())
```

No external deps; column widths auto-size from the data.

## sink

Append-only text sink. Optional rotation (one file per N bytes) and
dedupe (SHA1 hash set). The companion to `pans`: whatever the pan
yields, `sink.pour()` writes to disk.

```python
from hypernix.sink import Sink

s = Sink(path="out.txt", rotate_bytes=10_000_000, dedupe=True)
s.write("first line")
s.write("first line")                  # False — skipped
s.write_json({"event": "step", "i": 1})
s.close()

# Pipeline terminal:
Sink("clean.txt").pour(SaucePan("raw.txt"))
```

`Sink` is also a context manager (no buffering though — writes open /
close the file on every call for crash safety).

## instant_pot

One call, one trained snapshot. Recipe is a plain dict so it can live
in JSON:

```python
from hypernix import instant_pot

trained = instant_pot.brew({
    "repo_id": "nix2.5",               # or "local_dir": "./my-snap"
    "dataset": "./corpus.txt",
    "out_dir": "./trained",
    "steps": 500, "batch_size": 1, "context_length": 1024,
    "lr": 3e-4, "device": "cuda", "dtype": "float16",
    "freeze_embed": True,              # old_fridge.freeze embed_tokens
    "quants": ["fp16", "q4_k_m"],      # optional: also emit GGUFs
})
```

Required keys: `dataset`, `out_dir`. Everything else has a sensible
default. When `quants` is set, the trained snapshot is converted to
GGUF and each quant is produced via `llama-quantize` under
`out_dir/gguf/`.

## coffee_maker

Repeat a callable on a schedule, catch exceptions, keep history.
Zero-config cron replacement — for anything fancier reach for
systemd-timers or APScheduler.

```python
from hypernix import coffee_maker

def nightly_pretrain():
    # pull new scraped data, continue pretrain
    ...

maker = coffee_maker.coffee_maker(nightly_pretrain, interval_seconds=86400)
maker.run(cycles=7)            # one week of nightly brews
maker.summary()
# {"cycles": 7, "failed": 0, "mean_duration_s": 1823.4, "last_ok": True}
```

Exceptions don't stop the loop — they're captured in the `Brew`
record. Call `.stop()` from another thread or from inside the brew
itself for a cooperative cancel; `.serve()` also installs a SIGINT
handler so Ctrl-C exits cleanly.

## pressure_cooker

AdamW + three-phase LR schedule + lookahead, in one `torch.optim.Optimizer`
subclass. No separate scheduler object — the schedule is driven by
`PressureCooker._step`.

```python
from hypernix import pressure_cooker

opt = pressure_cooker.pressure_cooker(
    model.parameters(),
    peak_lr=3e-4,
    warmup_steps=200,          # 0 -> peak, linear
    plateau_steps=1000,        # peak, constant
    cooldown_steps=200,        # peak -> 0, cosine
    betas=(0.9, 0.95),
    weight_decay=0.1,
    lookahead_k=5,             # pressure seal every 5 inner steps
    lookahead_alpha=0.5,
)

for batch in loader:
    out = model(batch["input"], labels=batch["labels"])
    out["loss"].backward()
    opt.step()
    opt.zero_grad(set_to_none=True)

    # Introspection
    print(opt.phase(), opt.scheduled_lr())   # "warmup", 1.5e-4 …
```

### Why a custom optimizer?

Stock `AdamW` + `torch.optim.lr_scheduler.CosineAnnealingLR` covers
most cases. `PressureCooker` is a single-object answer when you want:

1. **One step call owns the whole schedule** — no risk of forgetting
   `scheduler.step()`, no order-of-operations bugs.
2. **Three-phase schedule baked in** — warmup / plateau / cosine are
   common enough together that having them in one place saves a few
   lines per training script.
3. **Lookahead's "slow weights" seal** — the Zhang et al. 2019 trick
   that empirically stabilizes AdamW on narrow networks. Off by
   default (`lookahead_k=0`); set to 5 or 10 to enable.

Introspection helpers:

```python
opt.phase()                    # "warmup" | "plateau" | "cooldown" | "done"
opt.scheduled_lr(step=1200)    # what LR is used at step 1200
repr(opt)
# PressureCooker(peak_lr=0.0003, warmup=200, plateau=1000, cooldown=200,
#                lookahead=k=5, alpha=0.5)
```

## End-to-end example

```python
from hypernix import pans, sink, instant_pot, pressure_cooker

# 1. Preprocess raw scraped text into a training corpus.
sink.Sink("clean.txt").pour(pans.GrillPan("raw.txt", min_chars=16))

# 2. Brew a trained snapshot in one call.
trained = instant_pot.brew({
    "repo_id": "nix2.5",
    "dataset": "clean.txt",
    "out_dir": "./out",
    "steps": 1000, "batch_size": 1, "context_length": 1024,
    "quants": ["fp16", "q4_k_m"],
})

# 3. Push the GGUFs (hypernix.upload.upload_gguf or hypernix upload CLI).
```

Or, for anything with more moving parts, stitch together the individual
subsystems (oven, freezer, alarms, fridges, ranges) directly — instant
pot is for the cases where the defaults are right.
