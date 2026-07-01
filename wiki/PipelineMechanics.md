# Pipeline Mechanics — `upload`, `fetcher`, `doctor`

Three small support modules that keep the download → convert → quantize
→ upload pipeline working end-to-end: pushing results to the Hub,
auto-fetching the `llama-quantize` binary, and diagnosing a broken
environment.

---

## `hypernix.upload` — push GGUF files to the Hub

```python
from hypernix.upload import upload_gguf

url = upload_gguf(
    ["hyper-nix-2.q4_k_m.gguf", "hyper-nix-2.q8_0.gguf"],
    repo_id="ray0rf1re/HyperNix.2-gguf",
)
```

`upload_gguf(files, repo_id="ray0rf1re/HyperNix.1-gguf", token=None, commit_message="Add HyperNix GGUF quantizations", private=False, create_if_missing=True) -> str`

| Arg | Notes |
|---|---|
| `files` | Iterable of paths. Every path is checked for existence up front — `FileNotFoundError` immediately if any is missing, before any upload starts. |
| `create_if_missing` | Calls `create_repo(..., exist_ok=True)` first — safe to call repeatedly. |

Upload strategy: a single file goes through `HfApi.upload_file`. Multiple
files that all share the same parent directory go through
`HfApi.upload_folder` with `allow_patterns` limited to just those
filenames (faster than N separate file uploads). Multiple files spread
across different parent directories fall back to one `upload_file` call
per file. Returns `f"https://huggingface.co/{repo_id}"`.

### Required modules

`huggingface_hub` (`HfApi`, `create_repo`) — hard dependency. Standard library: `collections.abc`, `pathlib`.

---

## `hypernix.fetcher` — auto-fetch a `llama-quantize` binary

Downloads a prebuilt `llama-quantize` binary from the official
`ggml-org/llama.cpp` GitHub releases, so users who skipped the
`[llama-cpp]` extra still get working k-quant support. Cached under
`~/.cache/hypernix/bin/` (or `$HYPERNIX_CACHE_DIR`), and `quantize.py`'s
resolver automatically searches this directory — no manual PATH setup
needed after the first fetch.

```python
from hypernix.fetcher import fetch_llama_quantize

path = fetch_llama_quantize()   # cached if already fetched; else downloads
```

`fetch_llama_quantize(*, force=False, quiet=False, prefer_cached=True, search_releases=10) -> Path`

Behavior:
1. If `prefer_cached and not force`, checks `cached_binary()` first and
   returns immediately without touching the network if found.
2. Fetches up to `search_releases` recent llama.cpp releases (newest
   first, one API call via `/releases?per_page=N` — deliberately not
   `/releases/latest`, so the same call covers both the happy path and
   the walk-back fallback).
3. For each release, `_pick_asset()` scores every asset's filename
   against the detected OS tag (`"ubuntu"`/`"macos"`/`"win"`) and arch
   tokens (`x64`/`x86_64`/`amd64` or `arm64`/`aarch64`), excluding
   GPU-backend builds (`cuda`, `hip`, `rocm`, `vulkan`, `sycl`, `musa`,
   `kompute`, `cann`) and cross-platform assets. Prefers filenames
   containing `"bin"` (the `bin-<os>-<arch>` naming convention).
4. If a release has no matching asset, logs and tries the next-older
   release — resilient to upstream occasionally skipping a platform's
   binary on a given tag.
5. Downloads the matching zip to a temp file, extracts via
   `_extract_binary()` (prefers `llama-quantize` over the older
   `quantize` binary name if both are present in the zip; also extracts
   any co-shipped shared libs matching a pattern for `libllama*`/
   `libggml*` `.so`/`.dylib`/`.dll`, plus MSVC runtime DLLs, so the cache
   is self-contained), sets the executable bit on POSIX, then deletes
   the temp zip.
6. Raises `RuntimeError` if every probed release lacked a matching
   asset, with a message pointing at `--llama-quantize`,
   `LLAMA_QUANTIZE`, or `pip install 'hypernix[llama-cpp]'` as alternatives.

`cache_dir()` — respects `$HYPERNIX_CACHE_DIR` first, then
`$XDG_CACHE_HOME`, then falls back to `~/.cache`; always appends
`hypernix/bin`.

`cached_binary()` — returns the cached binary's path if one exists and
(on POSIX) is executable; checks both `llama-quantize` and the older
`quantize` name (plus `.exe` variants on Windows).

### Required modules

Standard library only — `json`, `os`, `platform`, `re`, `shutil`,
`stat`, `sys`, `tempfile`, `urllib.error`, `urllib.request`, `zipfile`,
`collections.abc`, `pathlib`. No third-party dependencies — this module
is deliberately stdlib-only so it works even in a minimal environment
that hasn't installed `[llama-cpp]` yet. Reads `$GITHUB_TOKEN` if set,
to raise GitHub API rate limits.

---

## `hypernix.doctor` — environment diagnostic

```bash
hypernix doctor          # report only
hypernix doctor --fix    # also pip-installs missing runtime deps
```

```python
from hypernix.doctor import run
exit_code = run(fix=False)
```

`run(*, fix=False) -> int` — prints a checklist and returns `0` if every
**mandatory** check passed, else `1`.

### Checks performed

| Check | Mandatory? | Notes |
|---|---|---|
| OS | ✅ | Linux/macOS/Windows; on Linux also reports the detected distro id. |
| Python | ✅ | Expects 3.10–3.13 (3.12 is the CI target, no functional difference for users). |
| torch | ✅ | Floor is 1.13 (last 1.x release, needed for `hypernix.torch_compat` on old Intel Macs). Recommends ≥2.7 for native `nn.RMSNorm` + fused SDPA; 1.13–2.7 still works via the compat shim but without `torch.compile`/FlashAttention. |
| gguf | ✅ | Plain import check. |
| huggingface_hub | ✅ | Plain import check. |
| safetensors | ✅ | Plain import check. |
| sentencepiece | optional | Plain import check. |
| llama-quantize | ✅ | Calls `quantize._find_llama_quantize(auto_fetch=False)` — deliberately does **not** trigger an auto-fetch during a diagnostic run; only reports what's already resolvable. |
| auto-fetch cache | informational | Always reports `True` — just shows whether the fetcher's cache is populated, not whether that's good or bad. |
| `nice` / `ionice` | optional, POSIX-only | Skipped entirely on Windows. |

`_check_import(mod, minver=None)` — imports the module, reads
`__version__`, falling back to `importlib.metadata.version()` for
packages that don't expose it (e.g. `gguf`). **Note:** the `minver`
parameter exists but is never actually compared against the resolved
version anywhere in the function body — currently unused.

### `--fix` behavior

Installs/upgrades `_RUNTIME_DEPS` (`numpy`, `safetensors`,
`huggingface-hub`, `gguf`, `tqdm`, `sentencepiece`) and `_OPTIONAL_DEPS`
(`tokenizers`, `transformers`) via `hypernix.deps.ensure(..., upgrade=True)`.
**`torch` is deliberately never installed or upgraded by `--fix`** — it's
absent from both dependency tuples specifically so users keep control
over their own CUDA/CPU build choice (see `hypernix.deps.PROTECTED`).

### Required modules

- `hypernix.deps`, `hypernix.fetcher` (`cache_dir`, `cached_binary`),
  `hypernix.quantize` (`_detect_distro_id`, `_find_llama_quantize`) — internal
- Standard library: `importlib`, `platform`, `shutil`, `sys`, `pathlib`

---

## See also

- [Download](Download.md) — the pipeline stage before convert/quantize/upload
- [Convert](Convert.md) / [Quantization](Quantization.md) — produce the GGUF files `upload_gguf` pushes
- `hypernix.deps` — the lazy-install mechanism `doctor --fix` and several other modules rely on
