# CLI reference

`hypernix` ships a console script, `hypernix` (also aliased to `hnx` for brevity), which dispatches
to **34 subcommands** plus the `all` pipeline as the default (see `_SUBCOMMANDS`
in `src/hypernix/cli.py`). Most subcommands wrap one library function, so
they're easy to script; a few (`brew`, `cli`, `net`, `gkey`) are themselves
small sub-CLIs with their own sub-subcommands.

```
usage: hypernix <subcommand> [options]  (or: hnx <subcommand> [options])

Core pipeline:
  all                    download -> convert -> [quantize]  (default)
  download               fetch a HuggingFace snapshot
  convert                produce fp32 / fp16 GGUF from a snapshot
  quantize               run llama-quantize on an fp16 / fp32 GGUF
  verify                 read-validate a GGUF and print headers
  info                   package + optional GGUF header summary
  upload                 push files to a HuggingFace repo
  doctor                 environment diagnostic (pass --fix to install deps)
  fetch-llama-quantize   pre-seed the llama-quantize cache

Training & inference:
  train                  init / expand / run training utilities
  generate               sample text from a local snapshot
  oven                   code-generation wrapper
  chat                   interactive REPL against any supported model
  brew                   one-shot recipe pipeline, or the brewer architecture-builder sub-CLI
  camo / camouflage      RLHF/RLAF alignment scaffolding
  fizzle / fiz           architecture fuse/merge module
  stml                   VRAM -> trainable-context-length calculator

Assistants & dashboards:
  cli                    interactive TUI/CLI menu over all of the above
  pipeline               ASR -> LLM -> TTS pipeline (see note below)
  assistant              interactive assistant REPL (see note below)
  vera                   Vera assistant CLI
  tvtop                  classic live training dashboard
  cctvtop                Python training dashboard w/ hardware metrics + optional VNC
  map                    steampunk schematic TUI for model/training state

Data & infra:
  scavenger              search + pull HF datasets under storage/quality budgets
  websearch              non-API web search utility
  net                    Tailscale mesh connect / export / log tailing
  gkey                   API key issuance, scoping, revocation (Gatekeeper + Keymaster)
  config                 HyperNix configuration management
  prot / protect         hardware health monitoring and protection
  wiki                   this documentation, read straight from installed source

Shortcuts:
  --auto-oven            download default snapshot + run code completion
                         (equivalent to `hypernix oven --auto ...`)

Run `hypernix <subcommand> --help` for per-command flags.
```

> **Known limitations — read before relying on these:** `hypernix pipeline`
> and `hypernix assistant` both accept an LLM-selection flag (`--llm`,
> `--model`) but currently **ignore it**. Internally they call a hardcoded
> stub responder that returns a small set of canned/simulated replies —
> not real inference from any model you point them at. The ASR and TTS
> stages, and every other subcommand on this page, are real. See the
> `pipeline` and `assistant` sections below for specifics.

## Additional Companion Scripts

Apart from the main `hypernix` / `hnx` entry points, the package installs these
companion scripts (see `[project.scripts]` in `pyproject.toml` for the
authoritative list):

* `hnx` — Short alias for `hypernix`.
* `hypernix-quantize` — Alias for `hypernix` (historical name, predates the `quantize` subcommand naming).
* `tvtop` — Classic TUI training dashboard.
* `tvtop-old` / `tvtop-plus-plus` / `tvtoppp` — Older TUI dashboard generations, kept for compatibility.
* `tvtop-older` — Original single-panel dashboard.
* `cctvtop` — Python training dashboard with hardware metrics and optional VNC (same as `hypernix cctvtop`).
* `hyped` — Configurable high-quality chat TUI with a model/persona configurator.
* `hyped+` / `hyped-pro` — Standalone Node.js TUI backed by a real Python dispatch layer (cloud APIs, auto-downloaded local models, Gatekeeper routing), slash autocompletion, price estimator, system prompt compactor, and a `/gui` desktop mode (Qt6 X11/Wayland, GTK4 fallback).
* `hyped-pro-gui` — Launch the hyped-pro desktop GUI directly, without the TUI.
* `multilama` — Unified interface over multiple llama.cpp variants (vanilla, ik_llama.cpp, PrismML fork, KoboldCpp).
* `eth` — Ethanol GPU overclock and VRAM helper. Refuses to apply changes without `--confirm`.
* `gkey` — Same as `hypernix gkey`, as its own executable.
* `hnx-map` — Same as `hypernix map`, as its own executable.

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

## `brew`

```bash
# One-shot pipeline from a recipe file:
hypernix brew recipe.json --set output_dir=./out

# Architecture-builder sub-CLI (brewer):
hypernix brew new --preset small --out-dir ./arch
hypernix brew list
```

A path ending in `.json` is treated as an `instant_pot` recipe and run
end-to-end (download/convert/quantize/etc. as described in the recipe).
Anything else dispatches into the `brewer` architecture-builder sub-CLI,
with presets from `33m`/`micro`/`small`/`medium`/`large` (GPU) through
`cpu-nano`/`cpu-tiny`/`cpu-small` (CPU-only).

## `pipeline` and `assistant` — current limitations

Both of these are real, runnable REPLs — but the LLM stage in each is
currently a **hardcoded stub**, not a live model:

```bash
hypernix pipeline --audio recording.wav --asr whisper --llm nix2.5 --tts piper
hypernix assistant --model nix2.5
```

- `pipeline`'s `--llm` value is accepted but never read; the "LLM" stage
  always calls an internal `SimpleLLM` class that returns a short
  simulated response string.
- `assistant`'s `--model` value is accepted but never read; replies come
  from a small hardcoded demo responder ("I'm a demo assistant — integrate
  a real LLM for full responses!").
- The ASR and TTS stages of `pipeline`, and everything else in this
  document, call real code paths.

If you need real generation today, use `chat`, `generate`, or `oven`
directly against a downloaded model — those are fully wired up.

## `cli`

```bash
hypernix cli            # rich TUI menu
hypernix cli --simple   # plain-text menu, no `rich` dependency
```

Interactive menu covering downloads, conversion, quantization, training,
and evaluation without needing to remember individual subcommand flags.

## `tvtop` / `cctvtop`

```bash
hypernix tvtop      # classic single-panel dashboard, tails a training log
hypernix cctvtop     # richer dashboard with hardware telemetry, optional VNC
```

Run `hypernix tvtop --help` / `hypernix cctvtop --help` for the full flag
set — both are primarily driven by pointing them at a training log file.

## `camo` / `camouflage`

```bash
hypernix camo -Lmodel ./snapshot -Ai -M gpt-4o-mini -Sp "Be terse." -s 200
```

RLHF/RLAF alignment scaffolding. `-Ai` enables AI-assisted evaluation
(scoring generations with a separate evaluator model via `-M`) instead of
manual scoring; `-Sp` sets the system prompt used during rollout, `-s` the
number of steps.

## `fizzle` / `fiz`

```bash
hypernix fizzle --help
```

The Fuzed Architecture module — fuses/merges model weights and LoRA
adapters. See `hypernix fizzle --help` for the current flag set.

## `stml`

```bash
hypernix stml --vram 8 --params 3 --precision fp16 --batch-size 1
```

Calculates a trainable context length given available VRAM (GB), model
size (billions of params), batch size, and precision. Useful before
`train run` to avoid an OOM crash mid-run.

## `scavenger`

```bash
hypernix scavenger --keywords "code,python" --max-storage 20 \
    --min-likes 5 --data-type parquet --download some-org/some-dataset
```

Searches HuggingFace datasets and pulls them under a storage/quality
budget (`--max-storage` in GB, `--min-likes`, `--max-age`, etc.) instead
of downloading everything that matches a keyword.

## `websearch`

```bash
hypernix websearch "llama.cpp quantization formats" -n 5 --json
```

A non-API web search utility (`-e` to pick an engine, `--json` for
machine-readable output) — useful in scripts/agents that need search
results without a paid search-provider API key.

## `net`

```bash
hypernix net connect 100.64.0.5        # connect to a Tailscale mesh peer
hypernix net mport 8080                # expose the mesh port locally
hypernix net export 8080 --apply       # export a local port to the mesh
hypernix net tail acheck ./train.log   # tail a remote log; add -r to resume
```

Distributed network manager built on Tailscale — mainly for driving
`tvtop`/`cctvtop` against a training run happening on another machine.

## `gkey`

```bash
hypernix gkey create --type service --scopes download,upload --expires 2027-01-01
hypernix gkey list
hypernix gkey revoke <key_id>
```

Unified CLI over the Gatekeeper + Keymaster modules for issuing, scoping,
and revoking API keys used by `hyped-pro`'s cloud routing.

## `config`

```bash
hypernix config --help
```

Reads/writes HyperNix's persistent configuration (defaults for
`--output-dir`, `--token`, etc). See `hypernix config --help` for the
current subcommands.

## `map`

```bash
hypernix map --help
```

A steampunk-themed schematic TUI — dials, pipes, and steam-gauge style
visualization of model/training state. Also installed standalone as
`hnx-map`.

## `vera` / `prot` (`protect`)

```bash
hypernix vera --help
hypernix prot --help
```

`vera` is a separate assistant CLI; `prot`/`protect` is a hardware health
monitoring and protection module (thermal/power guardrails during long
training runs). Both are early/minimal — check `--help` for what's
currently implemented rather than assuming full parity with `chat` or
`cli`.

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
