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
  HPC-LOCAL-001  local snapshot missing and download failed
  HPC-LOCAL-002  local inference failed (OOM, dtype, arch mismatch, ...)
  HPC-T1-001     T1 key missing or rejected by the Gatekeeper
  HPC-CFG-001    unknown vendor / model short name
"""
from __future__ import annotations

import json
import logging
import os
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
    ModelDef("qwable-3.6-27b-mtp", "Mia-AiLab/Qwable-3.6-27b-MTP", "huggingface", "\u2605", 32768),
    ModelDef("qwable-9b-fable5", "empero-ai/Qwable-9B-Claude-Fable-5", "huggingface", "\u2605", 32768),
    ModelDef("qwopus-3.6-35b-a3b-coder-mtp", "Jackrong/Qwopus3.6-35B-A3B-Coder-MTP-GGUF", "huggingface", "\u2605", 32768),
    ModelDef("qwopus-3.6-27b-coder", "Jackrong/Qwopus3.6-27B-Coder", "huggingface", "\u2605", 32768),
    ModelDef("qwopus-3.5-9b-v3", "Jackrong/Qwopus3.5-9B-v3", "huggingface", "\u2605", 32768),
    ModelDef("qwopus-3.6-35b-a3b-v1-mtp", "Jackrong/Qwopus3.6-35B-A3B-v1-MTP-GGUF", "huggingface", "\u2605", 32768),
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


def local_snapshot_dir(model: ModelDef) -> Path:
    from .config import get_models_dir
    return get_models_dir() / model.repo.split("/")[-1]


def is_downloaded(model: ModelDef) -> tuple[bool, Path]:
    from .download import verify_snapshot
    d = local_snapshot_dir(model)
    if not d.exists():
        return False, d
    try:
        verify_snapshot(d)
        return True, d
    except FileNotFoundError:
        return False, d


def ensure_downloaded(model: ModelDef, quiet: bool = False) -> Path:
    """Download ``model``'s HF snapshot if it isn't already cached.

    Writes progress to stderr via ``hypernix.download``'s own logger (so
    both the bridge, which inherits its child's stderr straight to the
    user's terminal, and direct GUI calls, which run in-process, show the
    same real download progress). Raises HypedProError on failure — it
    never returns a path that doesn't actually verify.
    """
    from .download import download_model

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
    from .config import get_provider_key
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
) -> str:
    provider = PROVIDERS[model.vendor]
    if provider.kind != "cloud":
        raise HypedProError("HPC-CFG-001", f"{model.vendor} is not a cloud provider")
    key = _resolve_api_key(model.vendor, api_key)
    url = f"{provider.api_base}{provider.chat_path}"

    if provider.protocol == "anthropic-messages":
        headers = {
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        }
        body: dict[str, Any] = {
            "model": model.repo,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            body["system"] = system
        data = _http_post_json(url, headers, body)
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
        if not text:
            raise HypedProError("HPC-CLOUD-003", f"no text content in Anthropic response: {data!r}"[:400])
        return text

    if provider.protocol == "openai-chat":
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
        full_messages = list(messages)
        if system:
            full_messages = [{"role": "system", "content": system}] + full_messages
        body = {
            "model": model.repo,
            "messages": full_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        data = _http_post_json(url, headers, body)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise HypedProError("HPC-CLOUD-003", f"unexpected response shape: {data!r}"[:400]) from exc

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
    from .old_oven import preheat

    dtype = DEFAULT_LOCAL_DTYPE
    device = os.environ.get("HYPED_PRO_DEVICE")
    cache_key = (model.repo, dtype, device)
    oven = _OVEN_CACHE.get(cache_key)
    if oven is not None:
        return oven
    try:
        oven = preheat(repo_id=model.repo, device=device, dtype=dtype, quiet=quiet)
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
) -> str:
    from .config import get_provider_key
    from .gatekeeper import Gatekeeper
    from .keymaster import Keymaster

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
        reply = send_cloud_chat(get_model("gpt-4o"), messages, system=system, api_key=openai_key)
    else:
        reply = send_local_chat(model, messages, system=system)

    try:
        gk.record_usage(meta.key_id, endpoint="/chat", model=model.short, tokens_used=len(reply) // 4 + 1)
    except Exception as exc:  # noqa: BLE001
        log.warning("HPC-T1-001 usage recording failed (reply still returned): %s", exc)
    return reply


# ---------------------------------------------------------------------------
# Single entry point used by both front-ends.
# ---------------------------------------------------------------------------


def send_chat_message(
    model_short: str,
    messages: list[dict[str, str]],
    system: str | None = None,
    api_key: str | None = None,
) -> str:
    model = get_model(model_short)
    provider = PROVIDERS[model.vendor]
    if model.vendor == "t1":
        return send_t1_chat(model, messages, t1_key=api_key, system=system)
    if provider.kind == "cloud":
        return send_cloud_chat(model, messages, system=system, api_key=api_key)
    # local / huggingface
    ensure_downloaded(model, quiet=True)
    return send_local_chat(model, messages, system=system)


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
            }
            for m in MODELS
        ],
    }
