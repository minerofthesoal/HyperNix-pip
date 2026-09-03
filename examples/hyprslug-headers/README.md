# hyprslug-headers — the three ways out

The problem this directory is about, in the form it usually arrives:

```
llama_model_loader: failed to load model from
  ~/.lmstudio/models/HyperNix/Qwen3.8-2B-IQ0.9_L/Qwen3.8-2B-IQ0.9_L.gguf
```

That error is correct. LM Studio's bundled `llama.cpp` read the tensor
table, found GGML type 200, and stopped — because it has no
dequantisation kernel for 200. The type id is how it noticed; the missing
kernel is why it stopped. **No header fixes that.** A header claiming a
type `llama.cpp` knows would make the file load and produce noise, which
is worse than the error.

So there are three things you can actually do, and which one you want
depends on what you are willing to give up.

| | keeps the tier | loads in LM Studio | costs |
|---|---|---|---|
| `serve` | yes | yes, over HTTP | a running process |
| `wrap`  | no  | yes, as a file | 2–8× the size |
| `stamp` | yes | no | nothing |

## serve — keep the 0.9 bits

The model stays sub-bit inside `hnxrun` and LM Studio talks to it over
the endpoint it already speaks.

```bash
hypernix hyprslug-headers serve model.iq09.gguf --port 1234
# then point the client at http://127.0.0.1:1234/v1
curl -s localhost:1234/v1/models | jq '.data[0].hypernix'
```

`--cache-bytes 2G` spends memory to buy back some of the decode time.
`--host 0.0.0.0` publishes an unauthenticated inference endpoint to the
network, and the command says so out loud.

## wrap — make it a file anything opens

```bash
hypernix hyprslug-headers wrap model.iq09.gguf -o compat.gguf --to Q4_K_M
```

The tensors are decoded and re-encoded into a type stock `llama.cpp`
has. The result opens in LM Studio, in `llama.cpp`, in the reference
`gguf` reader — and **is not a 0.9-bit model any more**. It is a Q4_K_M
copy of one, several times larger, carrying the error of both
quantisations. The command prints that rather than leaving it to be
discovered from a file size.

Defaults per tier, chosen as the narrowest upstream type that does not
throw away more than the extension type already has:

| from | to |
|---|---|
| `IQ0.25_UXL`, `IQ0.5_XXXL`, `IQ0.75_M`, `IQ0.9_L`, `INT1` | `Q2_K` |
| `FP2` | `Q3_K` |
| `INT4` | `Q4_K` |

## stamp — make the file explain itself

```bash
hypernix hyprslug-headers stamp model.iq09.gguf
hypernix hyprslug-headers show  model.iq09.gguf --json
```

Writes a `hyprslug.header.*` block into the GGUF's own metadata: block
geometry, bits per weight, and either the group/kept pair or the code
levels. Arithmetic rather than a codec name, so a loader that has never
heard of type 203 still knows it is looking at 256-weight blocks of 8
bytes with three signs kept of every sixteen — enough to write a decoder
without this package.

It does not make the file loadable. It makes it *describable*.

## Finding out which of your models this applies to

```bash
hypernix hyprslug-headers install     # sets up the runtime, then scans
hypernix hyprslug-headers scan ~/.lmstudio/models
hypernix hyprslug-headers status --json
```

`install` looks in LM Studio's model tree (and Bionic's — they share it)
and lists the files that will fail to load there, so the answer arrives
before the question. Set `LMSTUDIO_HOME` if it lives somewhere unusual.
