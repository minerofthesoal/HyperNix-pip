# HnxRun — running the models llama.cpp cannot

```bash
hypernix generate --model model.iq05.gguf --prompt "hello"
hypernix chat     --model model.iq05.gguf
```

```python
from hypernix.models import hnxrun

model = hnxrun.load_model("model.iq05.gguf")   # weights stay packed
print(model.describe())
print(model.resident_bits_per_weight)          # 0.657
tokens = hnxrun.generate_tokens(model, [1, 5, 9], max_new_tokens=32)
text   = hnxrun.generate_text("model.iq05.gguf", "hello", max_new_tokens=32)
```

## The gap this closes

The [IQ0.x tiers](HyprSlug.md) have been real quantisations since
0.72.3 pt 2. The tensors genuinely carry 0.56 bits per weight and the
container is a well-formed GGUF. What they were **not** was runnable.

The type ids are at 200 and above — deliberately outside anything
upstream has allocated, so a stock loader refuses the file by name
instead of reading a 0.5-bit tensor as `Q4_K` and producing noise. Every
llama.cpp refuses them. So does the reference reader:

```
>>> gguf.GGUFReader("model.iq05.gguf")
ValueError: np.uint32(202) is not a valid GGMLQuantizationType
```

Which left a file that was correct, 30× smaller, and had nowhere to go.
"It is a real quantisation" is not much comfort when nothing will load
it.

## What this is

A reference implementation of the llama-family graph, in torch, that
reads every type this package writes: F32/F16/BF16, the llama.cpp block
types through [llamaquants](HyprSlug.md), and the HyperNix sub-bit types
through `subbit`. Quantised weights stay packed in memory and are
unpacked a slice at a time inside each matmul (see below); the graph is
RMSNorm → RoPE → grouped-query causal attention with a KV cache →
SwiGLU → output head.

Correctness first. No kernels, no fused anything, and it will not beat
llama.cpp — **it is not trying to.** For an upstream quant type
`hypernix generate` still routes to llama.cpp, which is better at
`Q4_K_M` than this ever will be. The point is that a 0.5-bit model has
somewhere to run at all.

## Sub-bit in memory too, not just on disk

The obvious way to write this runtime is to dequantise everything to
float32 at load time. That turns 0.56 bits into 32 — *larger* than the
F16 model the quantisation was made from — and hands back every byte the
tier existed to save. The file would still be small and the tier would
be pointless, which is the failure that is easy to ship because
everything still works.

So the packed bytes are what is held. Rows are unpacked a group at a
time inside each matmul, into a buffer that is thrown away:

| Tier | On disk | Resident | bits/weight resident |
|---|---|---|---|
| `IQ0.5_XXXL` | 10,816 | 8,768 | **0.657** |
| `IQ0.75_M` | 14,112 | 12,096 | **0.906** |
| `IQ0.9_L` | 15,776 | 13,760 | 1.031 |
| `Q4_K_M` | 72,672 | 70,688 | 5.294 |
| `Q8_0` | 116,384 | 114,432 | 8.570 |
| *(materialised)* | — | 427,264 | 32.0 |

Slightly above each packing's own rate because the norms are
one-dimensional and stay in float32. They are a rounding error of a real
model's size and most of the gap on a toy one — which is why `IQ0.9_L`
reads 1.031 here and would read about 0.94 on anything real.

`load_model(path, materialize=True)` takes the other trade: float32 up
front, roughly 16× faster per token, and the memory profile of the model
it was made from. Both paths produce **bit-identical** logits — they
unpack the same bytes with the same decoder — so this is purely a
memory-for-time dial, not a quality one.

### Slicing granularity

The packed stream is blocks over the *flattened* tensor, so a slice has
to land on a block boundary. One row is not always a whole number of
blocks: a 64-wide layer packed in 256-element blocks puts four rows in
one block. The unit is therefore the smallest run of rows that is whole,
`block // gcd(block, columns)` — one row for any real model, a handful
for a narrow one. Getting this wrong reads the wrong bytes and gives a
plausible, wrong model rather than an error, so it is tested against the
materialised weights row by row.

## The RoPE convention, which is where this goes wrong

llama.cpp's converter **permutes** Q and K on the way into a GGUF so
that rotary embedding applies to *adjacent pairs* rather than to split
halves. Read those tensors back and apply the half-split form — which is
what every Hugging Face implementation does — and you get a model that
loads, runs, and generates confident nonsense.

Adjacent pairs, matching the file. The KV cache is checked against a
full recompute in the tests, because a cache that drifts from the
uncached path gives output that is plausible and not what the model
would have said.

## Two different questions

The tests keep these apart deliberately, because confusing them is how a
quantiser ends up secretly not quantising.

**Does the quantiser work?** Measured at the weights, where the answer is
arithmetic. Each tier stores `kept` signs of every `group` and
reconstructs the rest by repeating the last stored one — right half the
time — so the fraction of surviving signs is fixed by the design:

| Tier | Stored | Signs that should survive | Measured |
|---|---|---|---|
| `IQ0.9_L` | 7 of 8 | 93.75% | 93.6% |
| `IQ0.75_M` | 3 of 4 | 87.5% | 87.4% |
| `IQ0.5_XXXL` | 2 of 4 | 75% | 74.8% |

50% would mean the stored signs are landing on the wrong weights — a
fault invisible in file size and fatal to the model.

**Is the model any good?** Measured at the logits, where the answer at
half a bit is *no*, and is supposed to be. A test that demanded good
output from a 0.5-bit model would be demanding the impossible, and the
only way to pass it would be to stop quantising. What is asserted is
**ordering**: more bits must not produce a worse model.

## Tokenizers

A GGUF describes its own vocabulary — `tokenizer.ggml.tokens`, plus
`merges` for BPE or `scores` for SentencePiece — so no second file has
to be kept in sync. Both families are implemented in the straightforward
way rather than the fast way: rank-ordered merging for BPE, Viterbi over
the scores for SPM. Greedy longest-match is the classic SPM shortcut and
it silently produces a different segmentation.

A file with no tokenizer metadata gets `None` and `generate_text` says
so, because inventing an encoding produces output that reads as a broken
model rather than as a missing tokenizer. `generate_tokens` still works
with ids you already have.

## Refusals

- An architecture it does not implement. Running the llama graph over a
  model that is not one produces confident nonsense rather than an
  error, so the name is checked against what the forward pass matches.
- A file with no `token_embd.weight` — a fragment, not a model.
- A token id outside the vocabulary.

## See also

- [HyprSlug](HyprSlug.md) — the quantiser that writes these files
- [Dflash2](Dflash2.md) — a draft model inside the model
- [Imatrix](Imatrix.md) — deciding which weights the quantiser protects
