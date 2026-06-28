# CLI reference

`hypernix` ships a console script, `hypernix` (also aliased to `hnx` for brevity), which dispatches
to 13 subcommands plus the `all` pipeline as the default. Every
subcommand wraps exactly one library function, so they're easy to
script.

```
usage: hypernix <subcommand> [options]  (or: hnx <subcommand> [options])

Subcommands:
  all                    download -> convert -> [quantize]  (default)
  download               fetch a HuggingFace snapshot
  convert                produce fp32 / fp16 GGUF from a snapshot
  quantize               run llama-quantize on an fp16 / fp32 GGUF
  verify                 read-validate a GGUF and print headers
  info                   package + optional GGUF header summary
  upload                 push files to a HuggingFace repo
  doctor                 environment diagnostic (pass --fix to install deps)
  fetch-llama-quantize   pre-seed the llama-quantize cache
  train                  init / expand / run training utilities
  generate               sample text from a local snapshot
  oven                   code-generation wrapper
  chat                   interactive REPL against any supported model

Shortcuts:
  --auto-oven            download default snapshot + run code completion
                         (equivalent to `hypernix oven --auto ...`)

Run `hypernix <subcommand> --help` for per-command flags.
```

## Additional Companion Scripts

Apart from the main `hypernix` / `hnx` entry points, the package installs companion scripts:

* `tvtop` — Classic TUI training dashboard.
* `tvtop++` / `tvtoppp` — Premium TUI training dashboard with process list, block history, and dampened slope curve estimations.
* `hyped` — Configurable high-quality chat TUI.
* `eth` — Ethanol GPU overclock and VRAM helper.

## `all` — the classic pipeline

```bash
hypernix --repo-id ray0rf1re/hyper-nix.1 --output-dir ./out \
    --quants fp32 fp16 q8_0 q6_k q4_k_m

hypernix --model-dir ./local-snapshot --output-dir ./out   # skip download
```

Full flag set:

| Flag | Default | What |
|---|---|---|
| `--repo-id REPO` | `ray0rf1re/hyper-nix.1` | HF repo id |
| `--revision REF` | latest | git ref / tag |
| `--model-dir PATH` | — | reuse a local snapshot |
| `--output-dir PATH` | `./hypernix-gguf` | where GGUFs land |
| `--name NAME` | `HyperNix` | header display name |
| `--arch NAME` | `hypernix` | GGUF `general.architecture` |
| `--quants [Q ...]` | `fp32 fp16` | any mix from the [quant aliases](Quantization.md#quantize_gguf) |
| `--n-head N` | from config | override head count |
| `--context-length N` | from config | override context length |
| `--threads N` | `cpu_count//2` | llama-quantize threads |
| `--llama-quantize PATH` | auto | explicit binary path |
| `--no-auto-fetch` | false | disable the GitHub-release fallback |
| `--auto` | false | walk back releases + PyPI fallback |
| `--keep-intermediate` | false | keep the fp16 GGUF |
| `--token TOKEN` | `$HF_TOKEN` | for gated repos / uploads |
| `--upload-to REPO` | — | push produced GGUFs |
| `--upload-private` | false | mark the target repo private |

## `download`

```bash
hypernix download --repo-id nix2.5                 # short name
hypernix download --repo-id Qwen/Qwen3.5-4B --token $HF_TOKEN
```

| Flag | Default |
|---|---|
| `--repo-id` | `ray0rf1re/hyper-nix.1` |
| `--revision` | latest |
| `--local-dir PATH` | HF cache |
| `--cache-dir PATH` | `~/.cache/huggingface/hub` |
| `--token` | `$HF_TOKEN` |
| `--quiet` | false |
| `--no-verify` | false |

Prints the local snapshot path to stdout.

## `convert`

```bash
hypernix convert --model-dir ./snapshot --output ./out-fp16.gguf --dtype fp16
```

| Flag | Default |
|---|---|
| `--model-dir PATH` | required |
| `--output PATH` | required |
| `--dtype` | `fp16` (`fp16` / `f16` / `fp32` / `f32`) |
| `--arch NAME` | `hypernix` |
| `--name NAME` | `HyperNix` |
| `--n-head N` | from config |
| `--context-length N` | from config |

## `quantize`

```bash
hypernix quantize --source ./out-fp16.gguf --output ./out-q4.gguf --type q4_k_m
```

| Flag | Default |
|---|---|
| `--source PATH` | required |
| `--output PATH` | required |
| `--type Q` | required (see [quant aliases](Quantization.md#quantize_gguf)) |
| `--threads N` | `cpu_count//2` |
| `--llama-quantize PATH` | auto |
| `--no-auto-fetch` | false |
| `--auto` | false (walks back releases + PyPI fallback) |

## `verify`

```bash
hypernix verify ./out-q4_k_m.gguf            # header summary
hypernix verify ./out-q4_k_m.gguf --tensors  # + tensor list
```

Exit code 0 on successful parse, non-zero otherwise.

## `info`

```bash
hypernix info                   # version + python + torch
hypernix info --gguf a.gguf     # + full verify output
```

## `upload`

```bash
hypernix upload --repo-id ray0rf1re/HyperNix.1-gguf a.gguf b.gguf c.gguf
```

| Flag | Default |
|---|---|
| `--repo-id` | `ray0rf1re/HyperNix.1-gguf` |
| `--token` | `$HF_TOKEN` |
| `--private` | false |
| `--commit-message MSG` | `"Add HyperNix GGUF quantizations"` |
| positional: file list | required |

## `doctor`

```bash
hypernix doctor              # report
hypernix doctor --fix        # install missing runtime deps
```

Reports Python / torch / numpy / safetensors / huggingface-hub / gguf /
tqdm / sentencepiece versions, OS + distro, and the resolved
`llama-quantize` path. `--fix` routes through `hypernix.deps.ensure`
to install any runtime deps that aren't pinned by the wheel
(`torch` is never touched — users control their CUDA flavor).

## `fetch-llama-quantize`

Pre-seed the `~/.cache/hypernix/bin/` cache so the first `quantize`
call is fast:

```bash
hypernix fetch-llama-quantize
hypernix fetch-llama-quantize --force          # redownload
hypernix fetch-llama-quantize --auto           # include PyPI fallback
hypernix fetch-llama-quantize --search-releases 20
```

## `train`

Sub-subcommands: `init`, `expand`, `run`. See [Training.md](Training.md)
for the mental model. Full flag reference:

### `train init`

```bash
hypernix train init \
    --out-dir ./fresh --tokenizer-source ./hyper-nix-v1 \
    --vocab-size 32000 --hidden-size 1024 --intermediate-size 4096 \
    --num-hidden-layers 16 --num-attention-heads 16 \
    --max-position-embeddings 2048 --rope-theta 10000.0 \
    --seed 0
```

### `train expand`

```bash
hypernix train expand \
    --src-dir ./hyper-nix-v1 --dst-dir ./hyper-nix-v2 \
    --hidden-size 1536 --intermediate-size 6144 \
    --num-hidden-layers 24 --num-attention-heads 24 \
    --init-std 0.02 --seed 0
```

### `train run`

```bash
hypernix train run \
    --model-dir ./hyper-nix-v2 --dataset ./corpus.txt \
    --out-dir ./trained \
    --steps 1000 --batch-size 2 --context-length 512 \
    --lr 3e-4 --weight-decay 0.1 --grad-clip 1.0 \
    --dtype float32 --log-every 10 --save-every 500 --seed 0
```

## `generate`

```bash
hypernix generate --model-dir ./snapshot --prompt "def fib(n):" \
    --max-new-tokens 128 --temperature 0.2 --top-k 40 --top-p 0.95 \
    --seed 0 --device cuda --dtype float16
```

Small sampler, no chat template, no stop-sequence trimming. For
code-oriented generation use `oven`; for conversations use `chat`.

## `oven`

Code-generation wrapper — preheat + `complete` or `fill` in one call.

```bash
# Prompt completion.
hypernix oven --repo-id nano-mini --prompt "def fib(n):" \
    --max-new-tokens 128 --temperature 0.2 --top-k 40 --top-p 0.95

# Fill-in-the-middle.
hypernix oven --model-dir ./snapshot \
    --fill-prefix "def add(a, b):\n    return " \
    --fill-suffix "\n\nprint(add(1, 2))" \
    --max-new-tokens 32

# Just download + save the self-contained .pt bundle.
hypernix oven --repo-id nix2.5 --save-pt ./nix.pt
```

Shortcut: `hypernix --auto-oven --prompt "..."` == `hypernix oven --auto --prompt "..."`.

## `chat`

```bash
# Single-turn (scripting).
hypernix chat --repo-id nix2.5 --message "Capital of France?"

# Interactive REPL.
hypernix chat --repo-id gemma-4-e4b --system "You are terse."
```

Same flags as `oven` minus the FIM options, plus `--system` and
`--message`.

## Environment variables

| Var | What |
|---|---|
| `HF_TOKEN` | HuggingFace token for gated repos / upload |
| `HYPERNIX_AUTO_INSTALL=0` | Disable the runtime pip-install shim |
| `HYPERNIX_CACHE_DIR` | Override `~/.cache/hypernix/` |

## Exit codes

- `0` — success
- `1` — runtime error (download failed, quantize crashed, etc.)
- `2` — bad usage (missing required flag, non-existent model-dir, …)
