# hypernix

[![PyPI](https://img.shields.io/pypi/v/hypernix.svg)](https://pypi.org/project/hypernix/)
[![Python](https://img.shields.io/pypi/pyversions/hypernix.svg)](https://pypi.org/project/hypernix/)
[![License](https://img.shields.io/pypi/l/hypernix.svg)](https://github.com/minerofthesoal/hypernix-pip/blob/main/LICENSE)

**Download the [`ray0rf1re/hyper-nix.1`](https://huggingface.co/ray0rf1re/hyper-nix.1)
PyTorch model and export GGUF files at `fp32`, `fp16`, `Q8_0`, `Q6_K`, and
`Q4_K_M` precision — on Ubuntu, Arch, Fedora, openSUSE, Alpine, NixOS, or
anything else with CPython 3.10+ and PyTorch 2.7.1.**

The converter is **architecture-agnostic**: it introspects the state dict,
so any HyperNix checkpoint works regardless of depth, hidden size, head
count, FFN width, or vocabulary size.

---

## Install

```bash
pip install "hypernix[llama-cpp]"
```

Or install everything with the distro bootstrap script:

```bash
./scripts/install_deps.sh        # handles apt, pacman, dnf, zypper, apk, nix
source .venv/bin/activate
hypernix doctor                  # sanity-check the environment
```

Requires:

- Linux (x86_64 / aarch64)
- Python **3.10 – 3.13** (3.12 recommended)
- PyTorch **2.7.1**
- `llama-quantize` — shipped via the `[llama-cpp]` extra, or from
  `pacman -S llama.cpp` / `dnf install llama-cpp` / a source build.

## Quickstart

```bash
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
hypernix [--repo-id REPO_ID] [--output-dir DIR] [--quants QUANT ...]
         [--model-dir DIR] [--n-head N] [--context-length N]
         [--threads N] [--llama-quantize BIN] [--keep-intermediate]
         [--upload-to REPO_ID] [--upload-private] [--token TOKEN]
hypernix doctor
```

| Quant alias | llama.cpp enum |
|---|---|
| `fp32`, `f32` | F32 |
| `fp16`, `f16` | F16 |
| `q8`, `q8_0` | Q8_0 |
| `q6`, `q6_k` | Q6_K |
| `q4km`, `q4_k_m` | Q4_K_M |
| `q5km`, `q5_k_m` | Q5_K_M |

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
