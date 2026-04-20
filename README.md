# hypernix

A Python 3.12 / PyTorch 2.7.1 pip package that downloads the
[`ray0rf1re/hyper-nix.1`](https://huggingface.co/ray0rf1re/hyper-nix.1)
model and converts it to **GGUF** at multiple quantization levels
(`fp32`, `fp16`, `Q8_0`, `Q6_K`, `Q4_K_M`) on Linux.

> HyperNix is a **custom architecture** (not Llama / Mistral / Qwen). The
> converter is shape-aware: it introspects the state dict, so it works for
> **any** HyperNix checkpoint regardless of depth, hidden size, head count,
> FFN width, or vocabulary size. No dimensions are hard-coded.

- Upstream weights: <https://huggingface.co/ray0rf1re/hyper-nix.1>
- Target GGUF release: <https://huggingface.co/ray0rf1re/HyperNix.1-gguf>

---

## 1. Install (Python 3.12, Linux)

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install --upgrade pip
pip install "hypernix[llama-cpp]"          # bundles a llama-quantize binary
```

If you already have `llama-quantize` from a local llama.cpp build, plain
`pip install hypernix` is enough; the tool will pick it up from `$PATH`.

Hard requirements:

- Linux
- Python **3.12** (enforced via `requires-python`)
- PyTorch **2.7.1** (pinned)
- `gguf`, `safetensors`, `huggingface_hub`, `sentencepiece`, `tqdm`
- `llama-quantize` for the k-quants — ship it via the `[llama-cpp]` extra
  or provide your own.

---

## 2. One-shot CLI

```bash
hypernix \
  --repo-id ray0rf1re/hyper-nix.1 \
  --output-dir ./hypernix-gguf \
  --quants fp32 fp16 q8_0 q6_k q4_k_m
```

Supported quant aliases:

| CLI name           | llama.cpp enum |
|--------------------|----------------|
| `fp32`, `f32`      | `F32`          |
| `fp16`, `f16`      | `F16`          |
| `q8`, `q8_0`       | `Q8_0`         |
| `q6`, `q6_k`       | `Q6_K`         |
| `q4km`, `q4_k_m`   | `Q4_K_M`       |
| `q5km`, `q5_k_m`   | `Q5_K_M`       |

Useful flags:

- `--model-dir PATH` — skip the download and use an existing snapshot.
- `--n-head N` — override the attention-head count (rare; the inferred
  `hidden // 64` guess covers the common case).
- `--context-length N` — override the context length metadata.
- `--threads N` — passed to `llama-quantize`.
- `--llama-quantize /path/to/llama-quantize` — point at a custom binary.
- `--keep-intermediate` — don't delete the fp16 GGUF used as the
  quantization source.
- `--upload-to REPO_ID` — after quantization, push every GGUF to a
  HuggingFace repo (e.g. `ray0rf1re/HyperNix.1-gguf`).
- `--upload-private` — create the target upload repo as private.
- `--token TOKEN` — HuggingFace access token (else reads `HF_TOKEN`).

Example: convert and publish in one shot.

```bash
export HF_TOKEN=hf_xxx
hypernix --upload-to ray0rf1re/HyperNix.1-gguf
```

---

## 3. Local script for Intel i7-7660U (or better)

`scripts/quantize_i7_7660u.sh` is tuned for a Kaby Lake ultrabook
(2 cores / 4 threads, ~8 GB RAM, no AVX-512). It caps BLAS/OpenMP to 4
threads, runs at reduced CPU + I/O priority so the laptop stays
responsive, and only keeps a single fp16 intermediate on disk.

```bash
# default: fp16, Q8_0, Q6_K, Q4_K_M -> ./hypernix-gguf
./scripts/quantize_i7_7660u.sh

# also build fp32
./scripts/quantize_i7_7660u.sh --with-fp32

# build and publish to ray0rf1re/HyperNix.1-gguf
HF_TOKEN=hf_xxx ./scripts/quantize_i7_7660u.sh --upload
```

The script works unchanged on any CPU that matches or exceeds the
i7-7660U (Coffee Lake, Ice Lake, Alder Lake, Zen 2+, Apple Silicon via
Rosetta, etc.). Pass `--threads N` to raise the thread cap on faster
machines.

---

## 4. Examples

- [`examples/quickstart.py`](examples/quickstart.py) — minimal 5-line
  conversion using the Python API.
- [`examples/custom_arch.py`](examples/custom_arch.py) — shows the
  converter handling arbitrary HyperNix shapes (any layer count, hidden
  size, heads, vocab).
- [`examples/upload_to_hub.py`](examples/upload_to_hub.py) — pushes the
  produced GGUFs to `ray0rf1re/HyperNix.1-gguf`.

### Python API

```python
from hypernix import download_model, convert_to_gguf, quantize_gguf
from hypernix.upload import upload_gguf

model_dir = download_model("ray0rf1re/hyper-nix.1")

fp16 = convert_to_gguf(model_dir, "hyper-nix-fp16.gguf", dtype="fp16")
q8   = quantize_gguf(fp16, "hyper-nix-q8_0.gguf", "q8_0")
q6   = quantize_gguf(fp16, "hyper-nix-q6_k.gguf", "q6_k")
q4   = quantize_gguf(fp16, "hyper-nix-q4_k_m.gguf", "q4_k_m")

upload_gguf([fp16, q8, q6, q4], repo_id="ray0rf1re/HyperNix.1-gguf")
```

---

## 5. How it works

1. `huggingface_hub.snapshot_download` pulls `config.json`, weight shards
   (`*.safetensors` or `pytorch_model.bin*`), and any tokenizer files.
2. `hypernix.convert` loads the state dict, infers dimensions from tensor
   shapes, and maps tensor names to llama.cpp's canonical GGUF layout
   when a recognizable pattern matches (Llama, NeoX, GPT-2, and nanoGPT
   naming schemes are all recognized). Unknown tensors are preserved
   verbatim, so a fully custom naming scheme still round-trips.
3. `hypernix.quantize` shells out to `llama-quantize` for `Q8_0`,
   `Q6_K`, `Q4_K_M`, etc., using the fp16 GGUF as the source.

The CLI skips re-work: it emits exactly one fp16 intermediate and reuses
it for every k-quant in the plan.

---

## 6. Typical output

On the default plan (`fp16 q8_0 q6_k q4_k_m`) for the 92M HyperNix 0.1
checkpoint you should expect roughly:

| File       | Size (approx) |
|------------|---------------|
| `*-fp32.gguf`  | ~370 MB     |
| `*-fp16.gguf`  | ~185 MB     |
| `*-q8_0.gguf`  | ~100 MB     |
| `*-q6_k.gguf`  |  ~76 MB     |
| `*-q4_k_m.gguf`|  ~58 MB     |

Your numbers will differ when running against larger HyperNix variants.

---

## 7. Supported distros

The Python code itself is distro-agnostic — it only needs CPython 3.12,
PyTorch 2.7.1, and a `llama-quantize` binary. The converter has been
exercised on:

| Distro                          | Install command                                                                 |
|---------------------------------|---------------------------------------------------------------------------------|
| **Ubuntu 24.04 / Debian 13**    | `sudo apt install python3.12 python3.12-venv && pip install "hypernix[llama-cpp]"` |
| **Ubuntu 22.04** (via deadsnakes)| `sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt install python3.12 python3.12-venv && pip install "hypernix[llama-cpp]"` |
| **Arch / Manjaro / EndeavourOS**| `sudo pacman -S python python-pip llama.cpp && pip install hypernix`            |
| **Fedora 40+ / RHEL 9 / Alma / Rocky** | `sudo dnf install python3.12 llama-cpp && pip install hypernix`          |
| **openSUSE Tumbleweed**         | `sudo zypper install python312 llama.cpp && pip install hypernix`               |
| **Alpine 3.20+**                | `sudo apk add python3 py3-pip bash && pip install "hypernix[llama-cpp]"`        |
| **NixOS**                       | `nix-shell -p python312 llama-cpp --run 'pip install hypernix'`                 |

Or just let the bootstrap script figure it out:

```bash
./scripts/install_deps.sh        # detects /etc/os-release and installs
source .venv/bin/activate
hypernix doctor
```

`hypernix doctor` prints a summary of the environment and tells you
exactly what's missing:

```
[ok] OS                       Linux 6.8.0 (x86_64) distro=ubuntu
[ok] Python                   python 3.12.3 (ok)
[ok] torch                    torch 2.7.1 (ok)
[ok] gguf                     gguf 0.18.0
[ok] llama-quantize           /home/user/.venv/lib/python3.12/site-packages/llama_cpp/llama-quantize
[--] ionice (optional)        missing (optional)
```

`llama-quantize` is located via, in order: the `--llama-quantize` flag,
`$LLAMA_QUANTIZE`, `$PATH`, `/usr/bin`, `/usr/local/bin`,
`/opt/llama.cpp`, `~/.local/bin`, `~/llama.cpp/build/bin`, any
`$GGUF_QUANTIZE_PATH` entries, and the binary bundled with
`llama-cpp-python`.

---

## 8. Releases / CI

Two GitHub Actions workflows ship with the repo:

- **`.github/workflows/ci.yml`** — runs `pytest` + CLI smoke tests on
  every push and PR against Ubuntu 22.04 and Ubuntu 24.04.
- **`.github/workflows/release.yml`** — on a version tag (`vX.Y.Z`),
  builds an sdist + wheel with `python -m build`, checks them with
  `twine`, attaches them to a GitHub Release, and publishes to PyPI via
  [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (no
  API token required — configure the PyPI project with GitHub publisher =
  `minerofthesoal/hypernix-pip`, workflow = `release.yml`, environment =
  `pypi`). Manual `workflow_dispatch` runs build the artifacts and
  upload them for download without publishing.

Cutting a release:

```bash
# bump version in pyproject.toml -> e.g. 0.2.0
git commit -am "hypernix 0.2.0"
git tag -a v0.2.0 -m "hypernix 0.2.0"
git push origin main v0.2.0
```

The tag push triggers the build + GitHub Release + PyPI publish job.

---

## License

Apache-2.0.
