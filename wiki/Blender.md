# Blender — `hypernix.blender`

Given a set of input streams (file paths or iterables of strings), a
blender yields lines from all of them at some blend ratio. Four tiers,
from a hand whisk up to a commercial blender:

| Tier | Class | Strategy |
|---|---|---|
| 1 | `HandBlender` | Straight concatenation — source A fully, then B, then C. |
| 2 | `PersonalBlender` | Round-robin interleave — one line from each source in turn, dropping exhausted sources, until all are exhausted. |
| 3 | `CountertopBlender` | Weighted random sampling with replacement, keeping the specified ratio in expectation. |
| 4 | `HighPowerBlender` | Buffers every source into RAM, concatenates, then shuffles. Near-uniform output; strongest homogenization available, at the cost of memory scaling with total input size. |

All four yield strings and plug into [`hypernix.sink.Sink.pour()`](Pans.md).

## `HandBlender(sources)`

```python
from hypernix.blender import HandBlender
list(HandBlender(["a.txt", "b.txt"]))  # every line of a.txt, then every line of b.txt
```

## `PersonalBlender(sources)`

Pulls one line from each source per round; a source that raises
`StopIteration` is dropped from future rounds while the others continue.

## `CountertopBlender(sources, weights=None, seed=0)`

```python
from hypernix.blender import CountertopBlender
b = CountertopBlender(["scraped.txt", "curated.txt"], weights=[0.7, 0.3])
```

`weights` is a list of nonnegative floats, one per source — probability
of drawing from that source at each step (via `random.Random(seed).choices`).
Defaults to uniform (`[1.0] * len(sources)`) if omitted. Raises
`ValueError` if `len(weights) != len(sources)`. Exhausted sources are
removed from the candidate pool as they run out; sampling continues
among the remaining sources until all are exhausted.

## `HighPowerBlender(sources, seed=0)`

Reads every source fully into memory (`_buffered`, exposed post-iteration
for inspection), shuffles with `random.Random(seed)`, then yields the
shuffled result. For multi-GB corpora, prefer `CountertopBlender` instead
— this tier's memory footprint scales with total input size.

## Factory

```python
from hypernix.blender import blender
mixed = blender("countertop-blender", ["scraped.txt", "curated.txt"], weights=[0.7, 0.3])
```

`blender(tier, sources, **kw)` — `tier` case-insensitive, `_` normalized
to `-`. Valid tiers (also in `TIERS: dict[str, type]`): `"hand-blender"`,
`"personal-blender"`, `"countertop-blender"`, `"high-power-blender"`.
Unknown tier raises a plain `KeyError`; bad kwargs raise the raw
dataclass `TypeError` (no friendlier remapping, unlike `pans.pick_pan`).

### Required modules

Standard library only — `random`, `dataclasses`, `pathlib`, `collections.abc`.

---

## See also

- [Pans](Pans.md) — the sink these blenders typically feed into
- `hypernix.toaster` — per-line formatting of a single source rather than mixing multiple
- `hypernix.food_processor` — chunking a single large document rather than mixing sources
