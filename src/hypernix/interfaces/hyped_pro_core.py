"""hyped_pro_core — shared provider/model registry and real dispatch logic
for hyped+ (hyped-pro).

This is the single source of truth for:

  * the curated model catalog (``MODELS``)
  * the provider/vendor registry (``PROVIDERS``) — real API bases, auth
    env vars, and docs URLs, verified against each vendor's own docs
  * dispatch: :func:`send_chat_message` routes one chat turn to the right
    backend (a real cloud HTTP call, a real local HyperNix/transformers
    snapshot via :mod:`hypernix.old_oven`, or the local HNX1
    Gatekeeper/Keymaster quota layer) and returns a real reply or raises a
    real, coded error. It never fabricates a response.

Two front-ends share this module instead of re-implementing it:

  * :mod:`hypernix.hyped_pro_bridge` — a line-delimited-JSON stdio worker
    that the Node ``hyped_pro.ts`` TUI spawns once and keeps alive, so a
    local model stays loaded in VRAM across turns instead of reloading
    every message.
  * :mod:`hypernix.hyped_pro_gui` — the Qt6/GTK desktop GUI, which imports
    this module directly (no subprocess).

Error codes (raised as :class:`HypedProError`, ``.code`` attribute) are
grepable and printed to stderr by both front-ends:

  HPC-CLOUD-001  no API key configured for this vendor
  HPC-CLOUD-002  the vendor HTTP call failed (network / non-2xx)
  HPC-CLOUD-003  the vendor response could not be parsed
  HPC-CLOUD-004  agentic tool-call loop exceeded its round limit
  HPC-LOCAL-001  local snapshot missing and download failed
  HPC-LOCAL-002  local inference failed (OOM, dtype, arch mismatch, ...)
  HPC-LOCAL-003  GGUF agentic tool-call loop exceeded its round limit
  HPC-DEPS-001   a required package (huggingface_hub, torch, transformers,
                 llama_cpp) isn't installed for the interpreter actually
                 running this process — common on machines with multiple
                 Pythons (pyenv/uv/conda); see HYPED_PRO_PYTHON
  HPC-T1-001     T1 key missing or rejected by the Gatekeeper
  HPC-CFG-001    unknown vendor / model short name
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("hypernix.hyped_pro_core")

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class HypedProError(RuntimeError):
    """A real, coded failure — never silently swallowed into a fake reply."""

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Provider registry — every entry here is a real, currently-documented API.
# `kind` decides how dispatch routes a chat turn:
#   "cloud" -> real HTTP call to api_base + chat_path
#   "local" -> real local inference via hypernix.old_oven (HuggingFace
#              snapshot, auto-downloaded with hypernix.download)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderInfo:
    vendor: str
    kind: str                    # "cloud" | "local"
    label: str
    api_base: str | None = None
    chat_path: str | None = None
    protocol: str | None = None  # "anthropic-messages" | "openai-chat"
    auth_header: str | None = None  # "bearer" | "x-api-key"
    auth_env_var: str | None = None
    docs_url: str = ""
    notes: str = ""


PROVIDERS: dict[str, ProviderInfo] = {
    "anthropic": ProviderInfo(
        vendor="anthropic", kind="cloud", label="Anthropic",
        api_base="https://api.anthropic.com", chat_path="/v1/messages",
        protocol="anthropic-messages", auth_header="x-api-key",
        auth_env_var="ANTHROPIC_API_KEY",
        docs_url="https://docs.claude.com/en/api/messages",
    ),
    "openai": ProviderInfo(
        vendor="openai", kind="cloud", label="OpenAI",
        api_base="https://api.openai.com", chat_path="/v1/chat/completions",
        protocol="openai-chat", auth_header="bearer",
        auth_env_var="OPENAI_API_KEY",
        docs_url="https://platform.openai.com/docs/api-reference/chat",
    ),
    # Moonshot AI (Kimi). OpenAI-compatible endpoint, verified against
    # Moonshot's own API overview (platform.kimi.ai / platform.moonshot.ai).
    # Older docs reference api.moonshot.cn — that's the earlier
    # China-region domain; api.moonshot.ai is the current global one.
    "moonshot": ProviderInfo(
        vendor="moonshot", kind="cloud", label="Moonshot AI (Kimi)",
        api_base="https://api.moonshot.ai", chat_path="/v1/chat/completions",
        protocol="openai-chat", auth_header="bearer",
        auth_env_var="MOONSHOT_API_KEY",
        docs_url="https://platform.kimi.ai/docs/api/overview",
        notes="Kimi K3 is cloud-only at launch; weights are not self-hostable yet.",
    ),
    # Alibaba Cloud Model Studio / DashScope (Qwen). OpenAI-compatible
    # endpoint, international region. Region-specific endpoints exist
    # (Singapore/Tokyo/Beijing/HK); this is the general international one.
    "dashscope": ProviderInfo(
        vendor="dashscope", kind="cloud", label="Alibaba Cloud (Qwen)",
        api_base="https://dashscope-intl.aliyuncs.com",
        chat_path="/compatible-mode/v1/chat/completions",
        protocol="openai-chat", auth_header="bearer",
        auth_env_var="DASHSCOPE_API_KEY",
        docs_url="https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope",
    ),
    # T1 is not an external cloud API — it's HyperNix's own local
    # Gatekeeper/Keymaster quota-enforcement layer (see hypernix.gatekeeper
    # / hypernix.keymaster). Claiming it were a real external endpoint
    # would be exactly the kind of fabricated provider info this rewrite
    # is meant to remove, so it stays local.
    "t1": ProviderInfo(
        vendor="t1", kind="local", label="HNX1 T1 (Gatekeeper-routed)",
        auth_env_var="HNX_T1_KEY",
        docs_url="",
        notes="Routes through hypernix.gatekeeper.Gatekeeper; delegates to "
              "OpenAI if a key is configured, else the local oven.",
    ),
    "huggingface": ProviderInfo(
        vendor="huggingface", kind="local", label="Local (HuggingFace)",
        auth_env_var="HF_TOKEN",
        docs_url="https://huggingface.co/docs/huggingface_hub",
        notes="Auto-downloaded via hypernix.download.download_model and run "
              "in-process through hypernix.old_oven.",
    ),
}


# ---------------------------------------------------------------------------
# Curated model catalog. `repo` is either an HF repo id (local vendor) or
# the vendor's own API model name (cloud vendor). `context_window` values
# are the vendor-documented figures, not guesses.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelDef:
    short: str
    repo: str
    vendor: str
    badge: str
    context_window: int
    notes: str = ""
    # "safetensors" (default): loaded via hypernix.old_oven/transformers.
    # "gguf": loaded via llama-cpp-python (llama_cpp.Llama.from_pretrained).
    # GGUF repos ship multiple quantizations as separate files in one repo,
    # so gguf_filename picks a specific one rather than "the whole repo".
    format: str = "safetensors"
    gguf_filename: str | None = None
    # Full GPU offload (-1) is right for anything that comfortably fits in
    # VRAM. For models too large to fully fit even at their smallest quant,
    # this pins a conservative partial-offload default instead of OOMing;
    # HYPED_PRO_GGUF_NGL overrides it for any model regardless.
    gguf_default_ngl: int | None = None
    # Which hypernix.multilama backend loads this GGUF ("vanilla", "ik",
    # "prismml", "kobold"). None => multilama.auto_select_backend() picks
    # one from the repo/filename (e.g. Bonsai's Q1_0_g128 -> "prismml").
    gguf_backend: str | None = None

    @property
    def kind(self) -> str:
        return PROVIDERS[self.vendor].kind


MODELS: list[ModelDef] = [
    # -- cloud: Alibaba Cloud Model Studio (DashScope), OpenAI-compatible --
    ModelDef("qwen3.7-plus", "qwen3.7-plus", "dashscope", "\u26a1", 131072),
    # -- cloud: Moonshot AI --
    ModelDef("kimi-k3", "kimi-k3", "moonshot", "\u26a1", 262144,
             notes="Cloud-only at launch (July 2026); no public weights yet."),
    # -- cloud: Anthropic --
    ModelDef("claude-sonnet-5", "claude-sonnet-5", "anthropic", "\u26a1", 200000),
    ModelDef("claude-opus-4.8", "claude-opus-4-8", "anthropic", "\u26a1", 200000),
    ModelDef("claude-fable-5", "claude-fable-5", "anthropic", "\u2605", 200000),
    ModelDef("claude-haiku-4.5", "claude-haiku-4-5-20251001", "anthropic", "\u26a1", 200000),
    # -- cloud: OpenAI --
    ModelDef("gpt-4o", "gpt-4o", "openai", "\u26a1", 128000),
    # -- local: open-weight HuggingFace snapshots, auto-downloaded --
    ModelDef("deepseek-r1", "deepseek-ai/DeepSeek-R1", "huggingface", "\u2605", 128000),
    ModelDef("deepseek-v4-flash", "deepseek-ai/DeepSeek-V4-Flash", "huggingface", "\u26a1", 128000),
    ModelDef("gemma-4-27b", "google/gemma-4-27b-it", "huggingface", "\u2605", 8192),
    ModelDef("hyper-nix.2", "ray0rf1re/hyper-Nix.2", "huggingface", "\u26a0\ufe0f", 4096,
             notes="Severely undertrained — see hypernix.utils.warn_hyper_nix_2."),
    # K2-family Kimi models are open-weight and self-hostable (unlike K3).
    ModelDef("kimi-k2.7-code", "moonshotai/Kimi-K2.7-Code", "huggingface", "\u2605", 262144),
    # Was Mia-AiLab/Qwable-3.6-27b-MTP (format defaulted to safetensors,
    # wrong — it's GGUF-only). Swapped off that repo entirely rather than
    # just fixing the format: the community has reported llama.cpp failing
    # to load it ("missing tensor 'blk.64.attn_norm.weight'"), and the
    # repo owner's own comment ("I am aware, will be fixed today!") means
    # it was mid-fix, not stable. The same publisher's plain (non-MTP)
    # Qwable-3.6-27b is a single clean GGUF file with no such reports.
    ModelDef("qwable-3.6-27b", "Mia-AiLab/Qwable-3.6-27b", "huggingface", "\u2605", 32768,
             format="gguf", gguf_filename="Qwable-27b_Q4_K_M.gguf",
             notes="16.5GB — the -MTP sibling repo has community-reported tensor-loading "
                   "failures and was mid-fix per the owner; this plain version doesn't have that report."),
    # Was empero-ai/Qwable-9B-Claude-Fable-5 (safetensors). Its base,
    # Qwen3.5-9B, uses a hybrid Gated-DeltaNet/full-attention stack that's
    # neither in HyperNixModel's _NATIVE_MODEL_TYPES nor recognized by the
    # installed transformers (model_type='qwen3_5') — the same "falls back
    # to HyperNixModel, may produce garbage" trap confirmed live on
    # qwopus-3.5-9b-v3. Swapped to the same publisher's official GGUF,
    # which llama.cpp has real native support for.
    ModelDef("qwable-9b-fable5", "empero-ai/Qwable-9B-Claude-Fable-5-GGUF", "huggingface", "\u2605", 32768,
             format="gguf", gguf_filename="Qwable-9B-Claude-Fable-5-Q4_K_M.gguf",
             notes="Text-only quant (the repo also ships a vision mmproj hyped-pro doesn't use, "
                   "since there's no image-input path here)."),
    # -- local: GGUF repos, loaded via llama-cpp-python (llama_cpp.Llama),
    # not the safetensors/old_oven path. These two were previously listed
    # without format="gguf" — they're GGUF-only repos (no safetensors),
    # so the safetensors loader would have failed to find any weight file.
    # 35B-A3B MoE: even the smallest quant (Q3_K_M, 17.2GB) doesn't fully
    # fit in 8GB VRAM alone — gguf_default_ngl leaves most layers on GPU
    # and the rest on CPU rather than fully offloading and OOMing; tune
    # via HYPED_PRO_GGUF_NGL for your own VRAM budget.
    ModelDef("qwopus-3.6-35b-a3b-coder-mtp", "Jackrong/Qwopus3.6-35B-A3B-Coder-MTP-GGUF", "huggingface", "\u2605", 32768,
             format="gguf", gguf_filename="Qwopus3.6-35B-A3B-Coder-MTP-Q3_K_M.gguf", gguf_default_ngl=20,
             notes="35B-A3B MoE, 17.2GB at its smallest quant — won't fully fit on an 8GB card; "
                   "partial CPU offload by default (see gguf_default_ngl)."),
    # Confirmed genuinely safetensors (not broken/fake), but tagged
    # model_type='qwen3_6' — like qwopus-3.5-9b-v3 below, neither
    # HyperNixModel nor the installed transformers recognizes that, so
    # load_snapshot's fallback path is likely to warn and may produce
    # degraded output rather than a clean failure. A Coder-MTP-GGUF
    # sibling exists but wasn't verified enough to swap to with
    # confidence (MTP-in-GGUF adds its own real complexity — see the
    # Qwopus 35B-A3B MTP entries above needing partial offload even
    # before that) — flagging honestly here instead of guessing.
    ModelDef("qwopus-3.6-27b-coder", "Jackrong/Qwopus3.6-27B-Coder", "huggingface", "\u2605", 32768,
             notes="model_type='qwen3_6' isn't recognized by HyperNixModel or transformers here — "
                   "expect a 'falling back to HyperNixModel, may produce garbage' warning, same as "
                   "qwopus-3.5-9b-v3."),
    # Confirmed live: model_type='qwen3_5' isn't recognized by
    # HyperNixModel or the installed transformers — load_snapshot falls
    # back with an explicit "may produce garbage" warning rather than a
    # clean failure. Left in the catalog (it's a real, honest option) but
    # flagged rather than presented as equivalent to a fully-supported entry.
    ModelDef("qwopus-3.5-9b-v3", "Jackrong/Qwopus3.5-9B-v3", "huggingface", "\u2605", 32768,
             notes="model_type='qwen3_5' isn't recognized by HyperNixModel or transformers here — "
                   "confirmed to fall back with a 'may produce garbage' warning, not a clean load."),
    ModelDef("qwopus-3.6-35b-a3b-v1-mtp", "Jackrong/Qwopus3.6-35B-A3B-v1-MTP-GGUF", "huggingface", "\u2605", 32768,
             format="gguf", gguf_filename="Qwopus3.6-35B-A3B-v1-MTP-Q3_K_M.gguf", gguf_default_ngl=20,
             notes="35B-A3B MoE, 17.2GB at its smallest quant — won't fully fit on an 8GB card; "
                   "partial CPU offload by default (see gguf_default_ngl)."),
    # -- local: GGUF, small enough to fully fit and GPU-offload on an 8GB card --
    ModelDef("qwen3-4b-gguf", "Qwen/Qwen3-4B-GGUF", "huggingface", "\u2605", 32768,
             format="gguf", gguf_filename="Qwen3-4B-Q4_K_M.gguf",
             notes="2.5GB at Q4_K_M — fits comfortably in 8GB VRAM with room for a large context. "
                   "131072 ctx available via YaRN RoPE scaling (not enabled by default)."),
    # Nanbeige4.2 is a looped transformer with general.architecture=nanbeige
    # — not in upstream llama.cpp (confirmed on the model card), so this
    # goes through multilama's "nanbeige" backend (Nanbeige/llama.cpp @
    # nanbeige42), not vanilla. Same class of problem as Bonsai below.
    ModelDef("nanbeige4.2-3b-gguf", "owao/Nanbeige4.2-3B-GGUF", "huggingface", "\u2605", 32768,
             format="gguf", gguf_filename="Nanbeige4.2-3B-Q4_K_M.gguf", gguf_backend="nanbeige",
             notes="2.57GB at Q4_K_M — fits comfortably in 8GB VRAM once built. Looped-transformer "
                   "architecture (general.architecture=nanbeige) needs the Nanbeige/llama.cpp "
                   "nanbeige42 branch built from source; no prebuilt releases exist for it."),
    # Custom 1-bit (Q1_0_g128) kernels from a PrismML fork of llama.cpp,
    # NOT upstream ggml-org/llama.cpp. Routed through hypernix.multilama's
    # "prismml" backend (auto-selected — see multilama.auto_select_backend),
    # which will actually run this once that fork's llama-server is built
    # from source; multilama has no prebuilt release to fetch for it, so
    # the first attempt raises with the exact build command instead of
    # silently trying (and failing) with the wrong kernels.
    ModelDef("bonsai-27b-gguf", "prism-ml/Bonsai-27B-gguf", "huggingface", "\u26a0\ufe0f", 262144,
             format="gguf", gguf_filename="Bonsai-27B-Q1_0.gguf", gguf_backend="prismml",
             notes="Custom Q1_0_g128 1-bit kernels — needs the PrismML llama.cpp fork built from "
                   "source once (github.com/PrismML-Eng/llama.cpp); hypernix.multilama's prismml "
                   "backend handles running it after that. ~3.9GB, fits 8GB VRAM easily once built."),
]

_MODELS_BY_SHORT: dict[str, ModelDef] = {m.short: m for m in MODELS}


def get_model(short: str) -> ModelDef:
    m = _MODELS_BY_SHORT.get(short)
    if m is None:
        raise HypedProError("HPC-CFG-001", f"unknown model {short!r}")
    return m


# ---------------------------------------------------------------------------
# Local snapshot cache checks (no download side effects)
# ---------------------------------------------------------------------------


def _require(module_name: str, extra_hint: str) -> None:
    """Import ``module_name`` or raise a clear, actionable HypedProError.

    A bare ``ModuleNotFoundError`` propagating up from deep inside
    hypernix.download/old_oven is genuinely confusing on a machine with
    more than one Python interpreter on the system (pyenv, uv, conda,
    system python3 all coexisting): "pip install X" looks like it should
    have fixed it, and often *did* — just into a different interpreter
    than the one this bridge/GUI process is actually running under. This
    names the exact interpreter in use (``sys.executable``) and points at
    ``HYPED_PRO_PYTHON`` so the fix is obvious instead of a bare traceback.
    """
    import importlib
    try:
        importlib.import_module(module_name)
    except ImportError as exc:
        raise HypedProError(
            "HPC-DEPS-001",
            f"'{module_name}' is not installed for this interpreter "
            f"({sys.executable}). Install it there with: "
            f"{sys.executable} -m pip install {extra_hint} --break-system-packages. "
            f"If you use pyenv/uv/conda and installed it into a different "
            f"python, point hyped-pro at that one instead with "
            f"HYPED_PRO_PYTHON=/path/to/python3 (currently: {sys.executable}). "
            f"Underlying error: {exc}",
        ) from exc


def local_snapshot_dir(model: ModelDef) -> Path:
    from hypernix.system.config import get_models_dir
    return get_models_dir() / model.repo.split("/")[-1]


def _is_downloaded_gguf(model: ModelDef) -> tuple[bool, Path | None]:
    """Check HuggingFace Hub's own cache for the specific GGUF file.

    GGUF models don't go through hypernix.download/get_models_dir() at
    all — llama_cpp.Llama.from_pretrained() downloads (if needed) and
    caches through huggingface_hub's standard cache
    (~/.cache/huggingface/hub), the same as every other HF download. This
    checks that cache directly with local_files_only=True so a status
    check never triggers a network call or loads the model into memory.
    """
    _require("huggingface_hub", "huggingface_hub")
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        path = hf_hub_download(repo_id=model.repo, filename=model.gguf_filename, local_files_only=True)
        return True, Path(path)
    except LocalEntryNotFoundError:
        return False, None
    except Exception:  # noqa: BLE001 — treat any other lookup failure as "not cached"
        return False, None


def is_downloaded(model: ModelDef) -> tuple[bool, Path]:
    if model.format == "gguf":
        found, path = _is_downloaded_gguf(model)
        return found, (path or Path())
    _require("huggingface_hub", "huggingface_hub")
    from hypernix.models.download import verify_snapshot
    d = local_snapshot_dir(model)
    if not d.exists():
        return False, d
    try:
        verify_snapshot(d)
        return True, d
    except FileNotFoundError:
        return False, d


def ensure_downloaded(model: ModelDef, quiet: bool = False) -> Path:
    """Download ``model``'s weights if they aren't already cached.

    For safetensors models, writes progress to stderr via
    ``hypernix.download``'s own logger (so both the bridge, which
    inherits its child's stderr straight to the user's terminal, and
    direct GUI calls, which run in-process, show the same real download
    progress). For GGUF models, delegates to huggingface_hub's own
    downloader against the same cache llama_cpp.Llama.from_pretrained()
    will read from. Raises HypedProError on failure — it never returns a
    path that doesn't actually verify.
    """
    _require("huggingface_hub", "huggingface_hub")

    if model.format == "gguf":
        found, path = _is_downloaded_gguf(model)
        if found and path is not None:
            return path
        from huggingface_hub import hf_hub_download
        try:
            print(f"[hypernix] fetching {model.gguf_filename} from {model.repo} ...", file=sys.stderr)
            path = Path(hf_hub_download(repo_id=model.repo, filename=model.gguf_filename))
            print(f"[hypernix] {model.short} ready at {path}", file=sys.stderr)
            return path
        except Exception as exc:  # noqa: BLE001
            raise HypedProError(
                "HPC-LOCAL-001",
                f"could not download {model.gguf_filename!r} from {model.repo!r} "
                f"for model {model.short!r}: {exc}",
            ) from exc

    from hypernix.models.download import download_model

    downloaded, path = is_downloaded(model)
    if downloaded:
        return path
    try:
        return download_model(repo_id=model.repo, quiet=quiet, verify=True)
    except Exception as exc:  # noqa: BLE001
        raise HypedProError(
            "HPC-LOCAL-001",
            f"could not download {model.repo!r} for model {model.short!r}: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# Cloud dispatch — real HTTP calls, stdlib-only (no extra deps required).
# ---------------------------------------------------------------------------


def _resolve_api_key(vendor: str, override: str | None) -> str:
    if override:
        return override
    from hypernix.system.config import get_provider_key
    key = get_provider_key(vendor)
    if not key:
        env_var = PROVIDERS[vendor].auth_env_var or ""
        raise HypedProError(
            "HPC-CLOUD-001",
            f"no API key configured for {vendor}. Set it with /key {vendor} <key>, "
            f"or export {env_var}.",
        )
    return key


def _http_post_json(url: str, headers: dict[str, str], body: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw_err = exc.read().decode("utf-8", errors="replace")
        raise HypedProError(
            "HPC-CLOUD-002",
            f"HTTP {exc.code} from {url}: {raw_err[:500]}",
        ) from exc
    except urllib.error.URLError as exc:
        raise HypedProError("HPC-CLOUD-002", f"network error calling {url}: {exc.reason}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HypedProError("HPC-CLOUD-003", f"non-JSON response from {url}: {raw[:200]!r}") from exc


def send_cloud_chat(
    model: ModelDef,
    messages: list[dict[str, str]],
    system: str | None = None,
    api_key: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    max_thinking_tokens: int | None = None,
    enable_tools: bool = True,
    max_tool_rounds: int = 8,
) -> str:
    provider = PROVIDERS[model.vendor]
    if provider.kind != "cloud":
        raise HypedProError("HPC-CFG-001", f"{model.vendor} is not a cloud provider")
    key = _resolve_api_key(model.vendor, api_key)
    url = f"{provider.api_base}{provider.chat_path}"

    if provider.protocol == "anthropic-messages":
        from hypernix.interfaces import hyped_pro_tools as tools_mod

        headers = {
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        }
        tools_schema = tools_mod.anthropic_tools_schema() if enable_tools else None
        conversation: list[dict[str, Any]] = list(messages)

        for round_num in range(max_tool_rounds + 1):
            body: dict[str, Any] = {"model": model.repo, "max_tokens": max_tokens, "messages": conversation}
            if system:
                body["system"] = system
            if tools_schema:
                body["tools"] = tools_schema
            if max_thinking_tokens is not None and max_thinking_tokens > 0:
                # Real Anthropic API constraints: max_tokens is the *total*
                # budget (thinking + visible text combined), so it must
                # exceed budget_tokens or the API rejects the request;
                # extended thinking also requires temperature=1.
                body["max_tokens"] = max(max_tokens, max_thinking_tokens + 1)
                body["thinking"] = {"type": "enabled", "budget_tokens": max_thinking_tokens}
                body["temperature"] = 1
            data = _http_post_json(url, headers, body)
            blocks = data.get("content") or []
            stop_reason = data.get("stop_reason")
            # Only "text" blocks collected — a "thinking" block sits
            # alongside them in its own structured type when extended
            # thinking is on, so it's simply never gathered here rather
            # than needing to be stripped after.
            text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
            tool_use_blocks = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use"]

            if not tool_use_blocks or stop_reason != "tool_use":
                if not text and not tool_use_blocks:
                    raise HypedProError("HPC-CLOUD-003", f"no text content in Anthropic response: {data!r}"[:400])
                return text

            if round_num == max_tool_rounds:
                raise HypedProError("HPC-CLOUD-004", f"tool-call loop exceeded {max_tool_rounds} rounds without a final answer")

            conversation.append({"role": "assistant", "content": blocks})
            tool_results = []
            for tb in tool_use_blocks:
                tname, targs, tid = tb.get("name", ""), (tb.get("input") or {}), tb.get("id", "")
                print(f"[hypernix] tool call: {tname}({targs})", file=sys.stderr)
                try:
                    result = tools_mod.execute_tool(tname, targs)
                    tool_results.append({"type": "tool_result", "tool_use_id": tid, "content": result})
                except tools_mod.ToolError as exc:
                    tool_results.append({"type": "tool_result", "tool_use_id": tid, "content": exc.message, "is_error": True})
            conversation.append({"role": "user", "content": tool_results})

        raise HypedProError("HPC-CLOUD-004", f"tool-call loop exceeded {max_tool_rounds} rounds without a final answer")

    if provider.protocol == "openai-chat":
        from hypernix.interfaces import hyped_pro_tools as tools_mod

        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
        tools_schema = tools_mod.openai_tools_schema() if enable_tools else None
        conversation: list[dict[str, Any]] = list(messages)
        if system:
            conversation = [{"role": "system", "content": system}] + conversation

        for round_num in range(max_tool_rounds + 1):
            body: dict[str, Any] = {"model": model.repo, "messages": conversation, "temperature": temperature, "max_tokens": max_tokens}
            if tools_schema:
                body["tools"] = tools_schema
            data = _http_post_json(url, headers, body)
            try:
                msg = data["choices"][0]["message"]
            except (KeyError, IndexError, TypeError) as exc:
                raise HypedProError("HPC-CLOUD-003", f"unexpected response shape: {data!r}"[:400]) from exc

            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                return msg.get("content") or ""

            if round_num == max_tool_rounds:
                raise HypedProError("HPC-CLOUD-004", f"tool-call loop exceeded {max_tool_rounds} rounds without a final answer")

            conversation.append(msg)
            for tc in tool_calls:
                fn = tc.get("function") or {}
                tname = fn.get("name", "")
                try:
                    targs = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    targs = {}
                print(f"[hypernix] tool call: {tname}({targs})", file=sys.stderr)
                try:
                    result = tools_mod.execute_tool(tname, targs)
                except tools_mod.ToolError as exc:
                    result = f"ERROR: {exc.message}"
                conversation.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": result})

        raise HypedProError("HPC-CLOUD-004", f"tool-call loop exceeded {max_tool_rounds} rounds without a final answer")

    raise HypedProError("HPC-CFG-001", f"no protocol handler for vendor {model.vendor}")


# ---------------------------------------------------------------------------
# Local dispatch — real in-process inference via hypernix.old_oven.
# Ovens are cached by (repo, dtype, device) so a long-lived process (the
# bridge, or the GUI) keeps the model resident across turns.
# ---------------------------------------------------------------------------

_OVEN_CACHE: dict[tuple[str, str, str | None], Any] = {}

# GTX 1080 / Pascal (sm_61) has no bf16 support and no flash-attention-2;
# float16 is the correct default here. Override with HYPED_PRO_DTYPE if
# running on newer hardware.
DEFAULT_LOCAL_DTYPE = os.environ.get("HYPED_PRO_DTYPE", "float16")


def _get_oven(model: ModelDef, quiet: bool = True):
    _require("torch", "torch")
    from hypernix.models.neo_oven import preheat

    dtype = DEFAULT_LOCAL_DTYPE
    device = os.environ.get("HYPED_PRO_DEVICE")
    cache_key = (model.repo, dtype, device)
    oven = _OVEN_CACHE.get(cache_key)
    if oven is not None:
        return oven
    try:
        oven = preheat(repo_id=model.repo, device=device, dtype=dtype, quiet=quiet)
    except ImportError as exc:
        # preheat() can lazily need transformers (AutoModel fallback for
        # non-native architectures) even when torch itself is fine.
        _require("transformers", "transformers")
        # _require just succeeded (transformers importable) but preheat()
        # still raised ImportError for something else — surface it plainly.
        raise HypedProError(
            "HPC-DEPS-001",
            f"missing a dependency needed to load {model.short!r} for this "
            f"interpreter ({sys.executable}): {exc}",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HypedProError(
            "HPC-LOCAL-001",
            f"failed to load local snapshot for {model.short!r} ({model.repo}): {exc}",
        ) from exc
    _OVEN_CACHE[cache_key] = oven
    return oven


def send_local_chat(
    model: ModelDef,
    messages: list[dict[str, str]],
    system: str | None = None,
    max_new_tokens: int = 256,
    temperature: float = 0.7,
) -> str:
    oven = _get_oven(model)
    full_history = list(messages)
    if system:
        full_history = [{"role": "system", "content": system}] + full_history
    try:
        return oven.chat(full_history, max_new_tokens=max_new_tokens, temperature=temperature)
    except Exception as exc:  # noqa: BLE001
        raise HypedProError("HPC-LOCAL-002", f"local inference failed for {model.short!r}: {exc}") from exc


# ---------------------------------------------------------------------------
# GGUF dispatch — via hypernix.multilama, HyperNix's unified interface over
# several llama.cpp variants (vanilla in-process bindings, plus the ik_llama.cpp
# / PrismML / KoboldCpp server-binary backends for quant types or kernels
# vanilla doesn't support — see multilama's module docstring). hyped_pro_core
# doesn't talk to llama_cpp directly anymore; multilama owns that so the TUI,
# the GUI, and any other future caller all get the same backend selection and
# the same fallback behavior for free.
# ---------------------------------------------------------------------------

_MULTILAMA_CACHE: dict[tuple[str, str, str, int], Any] = {}

# Default context size for GGUF models. Deliberately conservative — KV
# cache grows with context, and this has to share whatever VRAM headroom
# is left after the weights themselves. Override with HYPED_PRO_GGUF_CTX.
DEFAULT_GGUF_CTX = int(os.environ.get("HYPED_PRO_GGUF_CTX", "8192"))


def _get_multilama(model: ModelDef):
    from hypernix.models import multilama as ml

    ngl_env = os.environ.get("HYPED_PRO_GGUF_NGL")
    n_gpu_layers = int(ngl_env) if ngl_env is not None else (
        model.gguf_default_ngl if model.gguf_default_ngl is not None else -1
    )
    backend_name = model.gguf_backend or ml.auto_select_backend(model.repo, model.gguf_filename or "")
    cache_key = (model.repo, model.gguf_filename or "", backend_name, n_gpu_layers)
    llm = _MULTILAMA_CACHE.get(cache_key)
    if llm is not None:
        return llm
    try:
        llm = ml.load(
            repo_id=model.repo,
            filename=model.gguf_filename or "",
            backend=backend_name,
            n_gpu_layers=n_gpu_layers,
            n_ctx=DEFAULT_GGUF_CTX,
        )
    except ml.MultiLlamaError as exc:
        detail = exc.message.rstrip(". ")
        note = f" {model.notes}" if model.notes else ""
        raise HypedProError(
            exc.code,
            f"failed to load GGUF {model.gguf_filename!r} from {model.repo!r} for "
            f"{model.short!r} via multilama backend {backend_name!r}: {detail}.{note}",
        ) from exc
    _MULTILAMA_CACHE[cache_key] = llm
    return llm


def send_local_chat_gguf(
    model: ModelDef,
    messages: list[dict[str, str]],
    system: str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.7,
    enable_tools: bool = True,
    max_tool_rounds: int = 8,
) -> str:
    from hypernix.interfaces import hyped_pro_tools as tools_mod
    from hypernix.models import multilama as ml

    llm = _get_multilama(model)
    tools_schema = tools_mod.openai_tools_schema() if enable_tools else None
    conversation: list[dict[str, Any]] = list(messages)
    system_arg = system

    try:
        for round_num in range(max_tool_rounds + 1):
            msg = llm.chat_message(
                conversation, system=system_arg, max_tokens=max_tokens,
                temperature=temperature, tools=tools_schema,
            )
            # system is only prepended once — chat_message() does that
            # itself from the system= kwarg, so it must not also live in
            # conversation or it would duplicate on every round.
            system_arg = None
            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                return msg.get("content") or ""
            if round_num == max_tool_rounds:
                raise HypedProError("HPC-LOCAL-003", f"tool-call loop exceeded {max_tool_rounds} rounds without a final answer")
            conversation.append(msg)
            for tc in tool_calls:
                fn = tc.get("function") or {}
                tname = fn.get("name", "")
                try:
                    targs = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    targs = {}
                print(f"[hypernix] tool call: {tname}({targs})", file=sys.stderr)
                try:
                    result = tools_mod.execute_tool(tname, targs)
                except tools_mod.ToolError as exc:
                    result = f"ERROR: {exc.message}"
                conversation.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": result})
        raise HypedProError("HPC-LOCAL-003", f"tool-call loop exceeded {max_tool_rounds} rounds without a final answer")
    except ml.MultiLlamaError as exc:
        raise HypedProError(exc.code, f"GGUF inference failed for {model.short!r} ({llm.backend.name}): {exc.message}") from exc
    except HypedProError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HypedProError("HPC-LOCAL-002", f"GGUF inference failed for {model.short!r}: {exc}") from exc


# ---------------------------------------------------------------------------
# T1 dispatch — routes through the real local Gatekeeper/Keymaster quota
# layer (see hypernix.gatekeeper), matching hyped.py's own _call_t1. This
# is intentionally NOT an HTTP call to an external "T1 API" — there isn't
# one; T1 is HyperNix's own quota-enforcement wrapper around whichever
# backend (OpenAI, or local) is actually configured.
# ---------------------------------------------------------------------------


def send_t1_chat(
    model: ModelDef,
    messages: list[dict[str, str]],
    t1_key: str | None = None,
    system: str | None = None,
    max_tokens: int | None = None,
) -> str:
    from hypernix.security.gatekeeper import Gatekeeper
    from hypernix.security.keymaster import Keymaster
    from hypernix.system.config import get_provider_key

    key = t1_key or get_provider_key("t1")
    if not key:
        raise HypedProError("HPC-T1-001", "no HNX T1 key set. Use /key t1 <key>.")

    km = Keymaster()
    gk = Gatekeeper(keymaster=km)
    try:
        meta = gk.authenticate(key)
        gk.check_quota(meta.key_id, endpoint="/chat", tokens_requested=100)
    except Exception as exc:  # noqa: BLE001
        raise HypedProError("HPC-T1-001", f"T1 authentication/quota check failed: {exc}") from exc

    openai_key = get_provider_key("openai")
    if openai_key:
        kwargs = {"max_tokens": max_tokens} if max_tokens is not None else {}
        reply = send_cloud_chat(get_model("gpt-4o"), messages, system=system, api_key=openai_key, **kwargs)
    elif model.format == "gguf":
        kwargs = {"max_tokens": max_tokens} if max_tokens is not None else {}
        reply = send_local_chat_gguf(model, messages, system=system, **kwargs)
    else:
        kwargs = {"max_new_tokens": max_tokens} if max_tokens is not None else {}
        reply = send_local_chat(model, messages, system=system, **kwargs)

    try:
        gk.record_usage(meta.key_id, endpoint="/chat", model=model.short, tokens_used=len(reply) // 4 + 1)
    except Exception as exc:  # noqa: BLE001
        log.warning("HPC-T1-001 usage recording failed (reply still returned): %s", exc)
    return reply


# ---------------------------------------------------------------------------
# Single entry point used by both front-ends.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Thinking/reasoning-block filtering. Several model families (Qwen3's
# thinking mode, DeepSeek-R1-style reasoners) inline their reasoning in the
# regular completion text wrapped in <think>...</think> (or the less common
# <thinking>/<reasoning> spellings some templates use) rather than putting
# it in a separate structured field — vendors that DO use a separate field
# (e.g. a distinct reasoning_content) are already unaffected, since callers
# only ever read the plain content/message text, never that field.
# ---------------------------------------------------------------------------

_THINK_BLOCK_CAPTURE_RE = re.compile(r"<(think|thinking|reasoning)>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
_THINK_UNCLOSED_CAPTURE_RE = re.compile(r"<(think|thinking|reasoning)>(.*)\Z", re.IGNORECASE | re.DOTALL)


def extract_thinking(text: str) -> tuple[str, str | None]:
    """Split a reply into (visible_text, thinking_text_or_None).

    Same tag handling as strip_thinking (including the truncated/unclosed
    case — an opening tag with no closing one because max_tokens cut
    generation off mid-thought), but keeps the thinking content instead of
    discarding it, so a caller that wants to *show* thinking (in its own
    style, e.g. /settings thinking-display) can, instead of it just being
    gone.
    """
    thinking_parts: list[str] = []

    def collect(m: re.Match) -> str:
        thinking_parts.append(m.group(2).strip())
        return ""

    cleaned = _THINK_BLOCK_CAPTURE_RE.sub(collect, text)
    cleaned = _THINK_UNCLOSED_CAPTURE_RE.sub(collect, cleaned)
    cleaned = cleaned.strip()
    thinking = "\n\n".join(p for p in thinking_parts if p) or None
    if not cleaned and text.strip():
        cleaned = "(model was still thinking when it ran out of output tokens — raise max output tokens with /settings)"
    return cleaned, thinking


def strip_thinking(text: str) -> str:
    """Remove inline <think>/<thinking>/<reasoning> blocks from a reply.

    Handles the truncated case too — if max_tokens cut generation off
    mid-thought, there's an opening tag with no closing one; that's
    stripped as well rather than left dangling in what's shown to the
    person, and a short note takes its place so an empty-looking reply
    doesn't look like a silent failure.
    """
    cleaned, _ = extract_thinking(text)
    return cleaned


def send_chat_message(
    model_short: str,
    messages: list[dict[str, str]],
    system: str | None = None,
    api_key: str | None = None,
    max_tokens: int | None = None,
    max_thinking_tokens: int | None = None,
    hide_thinking: bool = True,
    enable_tools: bool = True,
) -> dict[str, str | None]:
    """Returns {"content": <visible reply>, "thinking": <extracted thinking
    or None>}. When hide_thinking is True, thinking is always None (and
    simply removed from content, same as before) — when False, it's
    extracted rather than discarded, so a caller that wants to *show*
    thinking (e.g. hyped_pro.ts's /settings thinking-display, in its own
    color) has real content to render, not just a flag.
    """
    model = get_model(model_short)
    provider = PROVIDERS[model.vendor]
    kwargs: dict[str, Any] = {}
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    if model.vendor == "t1":
        reply = send_t1_chat(model, messages, t1_key=api_key, system=system, **kwargs)
    elif provider.kind == "cloud":
        cloud_kwargs = dict(kwargs)
        if max_thinking_tokens is not None:
            cloud_kwargs["max_thinking_tokens"] = max_thinking_tokens
        reply = send_cloud_chat(model, messages, system=system, api_key=api_key, enable_tools=enable_tools, **cloud_kwargs)
    else:
        ensure_downloaded(model, quiet=True)
        if model.format == "gguf":
            reply = send_local_chat_gguf(model, messages, system=system, enable_tools=enable_tools, **kwargs)
        else:
            # hypernix.old_oven has no tool-calling infrastructure (no
            # structured tool_calls parsing in CodeOven.chat()) — rather
            # than fake support that would silently never trigger, tools
            # simply aren't offered on this path. enable_tools is accepted
            # here for a uniform call signature but has no effect.
            reply = send_local_chat(model, messages, system=system, **{"max_new_tokens": max_tokens} if max_tokens is not None else {})

    if hide_thinking:
        return {"content": strip_thinking(reply), "thinking": None}
    content, thinking = extract_thinking(reply)
    return {"content": content, "thinking": thinking}


def catalog_json() -> dict[str, Any]:
    """Serializable view of MODELS + PROVIDERS for the bridge's `catalog` cmd."""
    return {
        "providers": {
            v: {
                "vendor": p.vendor, "kind": p.kind, "label": p.label,
                "api_base": p.api_base, "chat_path": p.chat_path,
                "auth_env_var": p.auth_env_var, "docs_url": p.docs_url,
                "notes": p.notes,
            }
            for v, p in PROVIDERS.items()
        },
        "models": [
            {
                "short": m.short, "repo": m.repo, "vendor": m.vendor,
                "kind": m.kind, "badge": m.badge,
                "context_window": m.context_window, "notes": m.notes,
                "format": m.format, "gguf_filename": m.gguf_filename, "gguf_backend": m.gguf_backend,
            }
            for m in MODELS
        ],
    }
