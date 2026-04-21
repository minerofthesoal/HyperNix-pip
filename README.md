# hypernix

[![PyPI](https://img.shields.io/pypi/v/hypernix.svg)](https://pypi.org/project/hypernix/)
[![Python](https://img.shields.io/pypi/pyversions/hypernix.svg)](https://pypi.org/project/hypernix/)
[![License](https://img.shields.io/pypi/l/hypernix.svg)](https://github.com/minerofthesoal/hypernix-pip/blob/main/LICENSE)

**Download the [`ray0rf1re/hyper-nix.1`](https://huggingface.co/ray0rf1re/hyper-nix.1)
PyTorch model and export GGUF files at `fp32` and `fp16` precision — on
Ubuntu, Arch, Fedora, openSUSE, Alpine, NixOS, or anything else with CPython
3.10+ and PyTorch 2.7.1. k-quants (`Q8_0`, `Q6_K`, `Q4_K_M`, `Q5_K_M`) are
available as opt-in via `--quants` when a `llama-quantize` binary is
available locally.**

The converter is **architecture-agnostic**: it introspects the state dict,
so any HyperNix checkpoint works regardless of depth, hidden size, head
count, FFN width, or vocabulary size.

---

## Install

From PyPI (recommended):

```bash
pip install "hypernix[llama-cpp]"
```

From a **GitHub Release** download (the `.whl` or `.tar.gz` attached to a
release) — these are real Python distributions, `pip` accepts them
directly:

```bash
pip install hypernix-0.1.2-py3-none-any.whl
# or:
pip install hypernix-0.1.2.tar.gz
```

From a **GitHub Actions artifact** download (the `hypernix-dist-*.zip`
you get from the Actions tab) — GitHub wraps every artifact in a `.zip`
on download, so you must **extract first**:

```bash
unzip hypernix-dist-0.1.2-*.zip -d hypernix-dist
pip install hypernix-dist/hypernix-0.1.2-py3-none-any.whl
```

Each artifact zip contains an `INSTALL.txt` with platform-specific
one-liners; the build also publishes `hypernix-wheel-<ver>` and
`hypernix-sdist-<ver>` artifacts so you can grab the raw wheel or sdist
without unzipping a multi-file bundle.

Or install everything with the distro bootstrap script:

```bash
./scripts/install_deps.sh        # handles apt, pacman, dnf, zypper, apk, nix
source .venv/bin/activate
hypernix doctor                  # sanity-check the environment
```

Requires:

- Linux (x86_64 / aarch64)
- Python **3.10 – 3.13** (3.12 recommended)
- PyTorch **2.7 or newer** (CPU, CUDA 11.8, CUDA 12.x, or ROCm)
- `llama-quantize` — shipped via the `[llama-cpp]` extra, or from
  `pacman -S llama.cpp` / `dnf install llama-cpp` / a source build. If none
  of those are available, hypernix auto-downloads a prebuilt CPU binary
  from the upstream [`ggml-org/llama.cpp`](https://github.com/ggml-org/llama.cpp/releases)
  GitHub release and caches it under `~/.cache/hypernix/bin/`. Disable with
  `--no-auto-fetch`, or pre-seed the cache with
  `hypernix fetch-llama-quantize`.

### Picking a torch build (CPU / CUDA 11 / CUDA 12)

`pip install hypernix` pulls the default torch wheel for your platform,
which is currently a CUDA-12 build on Linux x86_64. If you have an older
CUDA 11 driver (or a GPU that doesn't have CUDA-12 support) install
torch from the CUDA-11.8 index **first**, then install hypernix — pip
will reuse the already-installed torch instead of replacing it:

```bash
# CUDA 11.8 (older drivers / Kepler-through-Pascal GPUs on old stacks)
pip install --index-url https://download.pytorch.org/whl/cu118 torch
pip install hypernix

# CUDA 12.x (modern default)
pip install --index-url https://download.pytorch.org/whl/cu124 torch
pip install hypernix

# CPU-only (no GPU, or you don't want to pull CUDA deps)
pip install --index-url https://download.pytorch.org/whl/cpu torch
pip install hypernix
```

`hypernix doctor` prints the installed torch build (`cuda=11.8`,
`cuda=12.4`, or `cpu`) so you can confirm after install.

## Quickstart

```bash
# Default: fp32 + fp16 only — no external binary required.
hypernix \
  --repo-id ray0rf1re/hyper-nix.1 \
  --output-dir ./hypernix-gguf

# Opt in to k-quants (needs llama-quantize on PATH, or the [llama-cpp] extra):
hypernix \
  --repo-id ray0rf1re/hyper-nix.1 \
  --output-dir ./hypernix-gguf \
  --quants fp32 fp16 q8_0 q6_k q4_k_m
```

Python API:

```python
from hypernix import download_model, convert_to_gguf, quantize_gguf

model_dir = download_model("ray0rf1re/hyper-nix.1")
fp16 = convert_to_gguf(model_dir, "hyper-nix-fp16.gguf", dtype="fp16")
quantize_gguf(fp16, "hyper-nix-q4_k_m.gguf", "q4_k_m")
quantize_gguf(fp16, "hyper-nix-q6_k.gguf",   "q6_k")
quantize_gguf(fp16, "hyper-nix-q8_0.gguf",   "q8_0")
```

Publish all artifacts to [`ray0rf1re/HyperNix.1-gguf`](https://huggingface.co/ray0rf1re/HyperNix.1-gguf):

```bash
HF_TOKEN=hf_xxx hypernix --upload-to ray0rf1re/HyperNix.1-gguf
```

---

## Supported distros

| Distro | Install |
|---|---|
| Ubuntu 22.04+ / Debian 12+ | `sudo apt install python3.12 python3.12-venv && pip install "hypernix[llama-cpp]"` |
| Arch / Manjaro / EndeavourOS | `sudo pacman -S python python-pip llama.cpp && pip install hypernix` |
| Fedora / RHEL / Alma / Rocky | `sudo dnf install python3.12 llama-cpp && pip install hypernix` |
| openSUSE Tumbleweed | `sudo zypper install python312 llama.cpp && pip install hypernix` |
| Alpine 3.20+ | `sudo apk add python3 py3-pip bash && pip install "hypernix[llama-cpp]"` |
| NixOS | `nix-shell -p python312 llama-cpp --run 'pip install hypernix'` |

`hypernix doctor` prints an environment report with the exact `llama-quantize`
path it will use, Python / PyTorch / dependency versions, and distro id.

## Laptop-grade CPUs

`scripts/quantize_i7_7660u.sh` is tuned for a 2C/4T Kaby Lake ultrabook
(Intel i7-7660U) and works on any faster CPU:

```bash
# fp16 + Q8_0 + Q6_K + Q4_K_M into ./hypernix-gguf
./scripts/quantize_i7_7660u.sh

# build, then push to ray0rf1re/HyperNix.1-gguf
HF_TOKEN=hf_xxx ./scripts/quantize_i7_7660u.sh --upload
```

It caps BLAS/OpenMP to 4 threads, runs at reduced CPU + I/O priority
when `nice`/`ionice` are available, and only keeps a single fp16
intermediate on disk.

## CLI reference

```
hypernix <subcommand> [options]

Subcommands (all script-friendly, each wraps one library function):
  all                   download -> convert -> [quantize]  (default)
  download              fetch a HuggingFace snapshot
  convert               produce an fp32 or fp16 GGUF from a snapshot
  quantize              run llama-quantize on an fp16/fp32 GGUF
  verify                read-validate a GGUF and print its headers
  info                  package + optional GGUF header summary
  upload                push files to a HuggingFace repo
  doctor                environment diagnostic
  fetch-llama-quantize  pre-seed the llama-quantize cache
  train init            create a fresh HyperNix snapshot
  train expand          warm-start a bigger model from a smaller one
  train run             minimal causal-LM training loop
```

`hypernix` with only flags (no subcommand) still runs the full `all`
pipeline, so existing scripts keep working.

| Quant alias | llama.cpp enum |
|---|---|
| `fp32`, `f32` | F32 |
| `fp16`, `f16` | F16 |
| `q8`, `q8_0` | Q8_0 |
| `q6`, `q6_k` | Q6_K |
| `q4km`, `q4_k_m` | Q4_K_M |
| `q5km`, `q5_k_m` | Q5_K_M |

## Training larger HyperNix models

The `train` subcommand is a small scaffold for standing up a same-size
or bigger HyperNix model. Install with:

```bash
pip install "hypernix[train]"
```

Initialize a new HyperNix at a chosen shape:

```bash
hypernix train init \
  --out-dir ./hyper-nix-v2 \
  --tokenizer-source ./hyper-nix-v1 \
  --hidden-size 1536 --intermediate-size 6144 \
  --num-hidden-layers 24 --num-attention-heads 24
```

Warm-start a **bigger** model from an existing smaller checkpoint —
overlapping rows/columns copy over, new slots init from `N(0, std)`,
extra blocks duplicate the last old block:

```bash
hypernix train expand \
  --src-dir ./hyper-nix-v1 \
  --dst-dir ./hyper-nix-v2 \
  --hidden-size 1536 --intermediate-size 6144 \
  --num-hidden-layers 24
```

Run a minimal causal-LM training loop on a raw-text file (smoke-test /
short continue-pretrain, not a full trainer):

```bash
hypernix train run \
  --model-dir ./hyper-nix-v2 \
  --dataset ./corpus.txt \
  --out-dir ./hyper-nix-v2-trained \
  --steps 1000 --batch-size 2 --context-length 512
```

The output of `train init`/`train expand`/`train run` is a standard
HuggingFace snapshot directory, so you can feed it straight into
`hypernix convert` (or `hypernix all --model-dir`).

## How it works

1. `huggingface_hub.snapshot_download` pulls weights + tokenizer files.
2. The converter loads the state dict, infers dimensions from tensor
   shapes (so any HyperNix size works), and maps tensor names onto
   llama.cpp's canonical GGUF layout when a recognizable pattern matches
   (Llama, GPT-NeoX, GPT-2, nanoGPT). Unknown names round-trip verbatim.
3. `llama-quantize` consumes the fp16 GGUF to produce each k-quant.

The CLI emits exactly one fp16 intermediate and reuses it for every
k-quant in the plan.

## Examples

- [`examples/quickstart.py`](examples/quickstart.py) — 5-line Python API demo.
- [`examples/custom_arch.py`](examples/custom_arch.py) — arbitrary-size HyperNix.
- [`examples/upload_to_hub.py`](examples/upload_to_hub.py) — publish to the Hub.

## Build / release

Local build:

```bash
pip install build twine
python -m build              # produces dist/*.whl and dist/*.tar.gz
twine check --strict dist/*
```

### GitHub Actions

Three workflows live under `.github/workflows/`:

| Workflow | Trigger | Does |
|---|---|---|
| **`ci.yml`** | push / PR | ruff lint, pytest across Python **3.10–3.13** on `ubuntu-latest` + `ubuntu-22.04`, editable install, `setup.py --version` compat, plus a `build-check` job that verifies the sdist really contains `tests/`, `examples/`, `scripts/`, `.github/workflows/`, `MANIFEST.in`, `setup.py`, `setup.cfg`. |
| **`build.yml`** | reusable (`workflow_call`) + manual `workflow_dispatch` + push to `main` touching packaging | Builds sdist + wheel, runs `twine check --strict`, test-installs **both** the wheel *and* the sdist in clean venvs, bundles `scripts/ + examples/ + README + LICENSE` into an extra tarball for non-pip users, generates `SHA256SUMS`, and uploads a single 90-day-retention artifact containing all four files (`*.whl`, `*.tar.gz`, `*-scripts-examples.tar.gz`, `SHA256SUMS`). |
| **`release.yml`** | tag `vX.Y.Z` (or `vX.Y.Z-rc1` / `-pre` / `aN` / `bN`) | Calls `build.yml` for a single source of truth, verifies the tag matches `pyproject.toml`, classifies stable vs prerelease, creates a GitHub Release with all artifacts attached (prerelease flag set automatically), then publishes to **PyPI** (stable tags) or **TestPyPI** (prerelease tags) via Trusted Publishing — no API token needed. Manual `workflow_dispatch` can also push to TestPyPI for smoke-testing. |
| **`public-release.yml`** | manual `workflow_dispatch` with `version` input | One-click public release: validates PEP 440 version, bumps `pyproject.toml` + `setup.cfg` + `src/hypernix/__init__.py`, runs ruff + pytest + `python -m build`, commits the bump, creates an annotated tag with an auto-generated changelog from `git log`, and pushes — which fires `release.yml`. Has a `dry_run` toggle that preserves the built artifacts as an artifact for inspection. |

Trusted Publishing setup (one-time, per registry):

- On **PyPI** → add publisher: repo `minerofthesoal/hypernix-pip`, workflow `release.yml`, environment `pypi`.
- On **TestPyPI** → same repo, workflow `release.yml`, environment `testpypi`.

Cutting a release:

```bash
# bump version in pyproject.toml AND setup.cfg -> e.g. 0.2.0
git commit -am "hypernix 0.2.0"
git tag -a v0.2.0 -m "hypernix 0.2.0"
git push origin main v0.2.0          # triggers release.yml
```

For a prerelease:

```bash
git tag -a v0.2.0-rc1 -m "hypernix 0.2.0-rc1"
git push origin v0.2.0-rc1           # -> TestPyPI + prerelease GitHub Release
```

Users can verify downloads with the attached `SHA256SUMS`:

```bash
sha256sum --check SHA256SUMS
```

## License

Apache-2.0.
