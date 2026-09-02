# hyprslug — quantise a GGUF without llama.cpp

Also answers to **doomslug**, **doomslugthedestroyer** and **dstd**.

```bash
hyprslug model.f16.gguf IQ0.5_XXXL -o model.iq05.gguf
steamroller model.f16.gguf IQ0.9_L -hnx
hypernix quantize --source model.f16.gguf --output out.gguf --type IQ0.75_M -hnx
```

## What this fixes

Everything that quantised in this package used to shell out to
`llama-quantize`. That has two problems.

The small one: a machine that has not built llama.cpp cannot quantise.

The large one: the sub-bit tiers — `IQ0.9_L`, `IQ0.75_M`, `IQ0.5_XXXL` —
are HyperNix types that `llama-quantize` has **never heard of**, so for
those it was never going to be the answer. What
[`steamroller`](Quantization.md) actually did was copy the Q3_K_L staging
file and write a sidecar JSON naming a tier.

So a "0.5-bit model" was byte-identical to the 3-bit model it came from,
the same size on disk, and no more quantised than its input. The tier was
a label on an unchanged file.

## How you get below one bit

Not by storing a fraction of a bit per weight — you cannot — but by
storing **fewer signs than weights** and reconstructing the rest. Every
tier keeps one FP16 scale per 256-weight block; the magnitude is gone
entirely and the scale stands in for all of it.

| Tier | Signs kept | Block | bits/weight | GGML type |
|---|---|---|---|---|
| `IQ0.9_L` | 7 of every 8 | 30 B | 0.938 | 200 |
| `IQ0.75_M` | 3 of every 4 | 26 B | 0.812 | 201 |
| `IQ0.5_XXXL` | 2 of every 4 | 18 B | 0.562 | 202 |

The signs kept are the **first k of each group**, and that is forced
rather than chosen. Selecting them by magnitude was tried first and is
wrong: the decoder has no bits telling it which positions were stored, so
it fills left to right regardless, and a cleverer encoder only lands the
signs on the wrong weights. It showed up as the widest tier having the
*worst* reconstruction error — a test now pins that error is monotonic in
bit rate.

Where an importance matrix earns its place is the **scale**, which once
the magnitudes are gone is most of what is left to get right. The scale
is the weighted *mean* absolute value, not the maximum: the maximum
minimises a different quantity and biases every reconstruction high.

## Type ids at 200

Deliberately far above anything llama.cpp has allocated. A stock loader
hits an unknown type id and refuses the file **by name** instead of
reading a 0.5-bit tensor as Q4_K and producing noise. Refusing loudly is
the whole point of picking a number that cannot collide.

`hypernix chat` and `hypernix generate` check for this before handing a
file to any runtime, and say so:

```
model.iq05.gguf is IQ0.5_XXXL, a HyperNix extension type. No llama.cpp
build can read it — the type ids are deliberately above anything upstream
has allocated so a stock loader refuses the file instead of reading its
tensors as the wrong type.
  Run the model it was quantised from, or quantise to an upstream tier:
  hypernix quantize --type Q4_K_M
```

## What it will and will not touch

Normalisation weights, biases and anything one-dimensional are copied at
source precision — all of the damage, none of the size. Token embeddings
and the output head are configurable, because which dominates a file
depends on the model.

A tensor whose element count does not divide into 256 is copied and
**reported**. A run that quietly left half a model at F16 while reporting
`IQ0.5` would be the same failure this module exists to fix.

```
IQ0.5_XXXL  (quad_code_xxxl)
  4821.3 MB -> 512.7 MB (9.4x)
  226/291 tensors packed, 96.8% of weights
  65 copied at source precision:
    blk.0.attn_norm.weight: 1-D (norm or bias): all of the damage, none of the size
```

## `-hnx` means never

`resolve_binary()` downloads a llama.cpp build when it cannot find one,
so a lookup that happens and goes unused still leaves llama.cpp on the
machine. In `-hnx` mode the lookup does not happen, and a test replaces
`resolve_binary` with an assertion to keep it that way.

There is also no staging pass in this mode: the packer reads the
unquantised source directly, and going through Q3_K_L first would only
throw away precision it is about to use.

## Honestly

Below about 1.5 bits per weight a model stops being a slightly worse
version of itself and becomes a different, much worse model. No packing
changes that, and every tier carries the warning. What changed here is
that the file now genuinely is what its header says it is.

Full parity with the upstream llama.cpp types (Q4_K_M and friends) is not
here yet; `-hnx` with an upstream type says so rather than
half-supporting it.

## See also

- [Quantization](Quantization.md) — the GGUF pipeline and the upstream quant ladder
- [CLI](CLI.md) — `hypernix quantize`, `steamroller`, `hyprslug`
