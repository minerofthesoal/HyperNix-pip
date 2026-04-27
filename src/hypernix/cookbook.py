"""cookbook — chat-template registry.

A cookbook holds the *recipes* that turn a list of plain
``{"role", "content"}`` messages into the exact prompt string a
given model expects.  Different model families use different
formats (ChatML, Llama 3 turn tags, Alpaca instructions, plain
``role: content`` transcripts) and getting one wrong silently
makes a chat model behave like a base model.

Built-in templates:

* ``"chatml"``       — OpenAI ChatML / Qwen / hyper-Nix.2 native.
* ``"hyper-nix.2"``  — alias for ChatML; recommended template for
                       :data:`hypernix.DEFAULT_REPO_ID`.
* ``"llama3"``       — ``<|start_header_id|>role<|end_header_id|>`` form.
* ``"llama2"``       — ``[INST] ... [/INST]`` form with system in ``<<SYS>>``.
* ``"alpaca"``       — ``### Instruction:`` / ``### Response:``.
* ``"vicuna"``       — ``USER:`` / ``ASSISTANT:`` lines.
* ``"plain"``        — ``role: content`` transcript fallback.

Quick use::

    from hypernix.cookbook import COOKBOOK

    prompt = COOKBOOK.get("hyper-nix.2").apply(
        [
            {"role": "system", "content": "You are a helpful chef."},
            {"role": "user", "content": "How do I dice an onion?"},
        ],
        add_generation_prompt=True,
    )

The :func:`for_model` helper picks the right template by short
name or full HF repo id; it knows about every model registered in
:data:`hypernix.KNOWN_MODELS`.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass
class ChatTemplate:
    """A pure-string chat-format renderer.

    Each turn becomes::

        {prefix}{content}{suffix}

    with ``{prefix}`` chosen per role from
    ``role_prefixes[role]`` (falling back to ``"{role}: "``).
    ``add_generation_prompt`` appends ``assistant_prefix`` so the
    model knows it's the assistant's turn to speak.
    """

    name: str
    role_prefixes: Mapping[str, str] = field(default_factory=dict)
    role_suffixes: Mapping[str, str] = field(default_factory=dict)
    bos: str = ""
    eos: str = ""
    assistant_prefix: str = "assistant: "
    default_system: str | None = None
    notes: str = ""

    def apply(
        self,
        messages: list[dict[str, str]],
        *,
        add_generation_prompt: bool = True,
    ) -> str:
        """Render ``messages`` into a single prompt string.

        If the first message isn't a system message and
        :attr:`default_system` is set, the default is prepended.
        """
        msgs = list(messages)
        if (
            self.default_system
            and (not msgs or msgs[0].get("role") != "system")
        ):
            msgs = [{"role": "system", "content": self.default_system}, *msgs]

        parts: list[str] = [self.bos] if self.bos else []
        for m in msgs:
            role = m.get("role", "user")
            content = m.get("content", "")
            prefix = self.role_prefixes.get(role, f"{role}: ")
            suffix = self.role_suffixes.get(role, "\n")
            parts.append(f"{prefix}{content}{suffix}")
        if add_generation_prompt:
            parts.append(self.assistant_prefix)
        return "".join(parts)

    def stop_tokens(self) -> list[str]:
        """Best-effort list of strings that mark the end of an
        assistant turn — useful for early-stopping a sampler."""
        out: list[str] = []
        for role, suf in self.role_suffixes.items():
            if role == "assistant" and suf:
                out.append(suf)
        if self.eos:
            out.append(self.eos)
        return out


# ---------------------------------------------------------------------------
# Built-in templates
# ---------------------------------------------------------------------------

_CHATML = ChatTemplate(
    name="chatml",
    role_prefixes={
        "system": "<|im_start|>system\n",
        "user": "<|im_start|>user\n",
        "assistant": "<|im_start|>assistant\n",
    },
    role_suffixes={
        "system": "<|im_end|>\n",
        "user": "<|im_end|>\n",
        "assistant": "<|im_end|>\n",
    },
    assistant_prefix="<|im_start|>assistant\n",
    eos="<|im_end|>",
    notes="OpenAI ChatML / Qwen / hyper-Nix.2 native format.",
)

_HYPER_NIX_2 = ChatTemplate(
    name="hyper-nix.2",
    # Patch (0.51.1): copy the dicts so mutating one template's
    # role tables doesn't leak into the other (was an aliasing bug
    # in 0.51.0).
    role_prefixes=dict(_CHATML.role_prefixes),
    role_suffixes=dict(_CHATML.role_suffixes),
    assistant_prefix=_CHATML.assistant_prefix,
    eos=_CHATML.eos,
    default_system=(
        "You are HyperNix, a helpful assistant. Answer concisely and "
        "accurately. If you don't know, say so."
    ),
    notes=(
        "ChatML format with HyperNix-flavoured default system prompt. "
        "Recommended for ray0rf1re/hyper-Nix.2."
    ),
)

_LLAMA3 = ChatTemplate(
    name="llama3",
    role_prefixes={
        "system": "<|start_header_id|>system<|end_header_id|>\n\n",
        "user": "<|start_header_id|>user<|end_header_id|>\n\n",
        "assistant": "<|start_header_id|>assistant<|end_header_id|>\n\n",
    },
    role_suffixes={
        "system": "<|eot_id|>",
        "user": "<|eot_id|>",
        "assistant": "<|eot_id|>",
    },
    bos="<|begin_of_text|>",
    assistant_prefix="<|start_header_id|>assistant<|end_header_id|>\n\n",
    eos="<|eot_id|>",
    notes="Llama 3 / 3.1 / 3.2 / 3.3 chat format.",
)

_LLAMA2 = ChatTemplate(
    name="llama2",
    role_prefixes={
        "system": "<<SYS>>\n",
        "user": "[INST] ",
        "assistant": " ",
    },
    role_suffixes={
        "system": "\n<</SYS>>\n",
        "user": " [/INST]",
        "assistant": " </s><s>",
    },
    bos="<s>",
    assistant_prefix=" ",
    eos="</s>",
    notes="Llama 2 chat format (INST tags + <<SYS>>).",
)

_ALPACA = ChatTemplate(
    name="alpaca",
    role_prefixes={
        "system": "",
        "user": "### Instruction:\n",
        "assistant": "### Response:\n",
    },
    role_suffixes={
        "system": "\n\n",
        "user": "\n\n",
        "assistant": "\n\n",
    },
    assistant_prefix="### Response:\n",
    notes="Alpaca / Stanford-instruct format.",
)

_VICUNA = ChatTemplate(
    name="vicuna",
    role_prefixes={
        "system": "",
        "user": "USER: ",
        "assistant": "ASSISTANT: ",
    },
    role_suffixes={
        "system": "\n\n",
        "user": "\n",
        "assistant": "\n",
    },
    assistant_prefix="ASSISTANT: ",
    notes="Vicuna v1.1 plain-text format.",
)

_PLAIN = ChatTemplate(
    name="plain",
    role_prefixes={
        "system": "system: ",
        "user": "user: ",
        "assistant": "assistant: ",
    },
    role_suffixes={
        "system": "\n",
        "user": "\n",
        "assistant": "\n",
    },
    assistant_prefix="assistant: ",
    notes="Plain role: content transcript; works with any tokenizer.",
)


HYPER_NIX_2 = _HYPER_NIX_2  #: Public alias for the recommended hyper-Nix.2 template.

BUILTINS: dict[str, ChatTemplate] = {
    "chatml": _CHATML,
    "hyper-nix.2": _HYPER_NIX_2,
    "hypernix.2": _HYPER_NIX_2,
    "hyper-nix2": _HYPER_NIX_2,
    "hyper-nix": _HYPER_NIX_2,
    "hypernix": _HYPER_NIX_2,
    "llama3": _LLAMA3,
    "llama-3": _LLAMA3,
    "llama2": _LLAMA2,
    "llama-2": _LLAMA2,
    "alpaca": _ALPACA,
    "vicuna": _VICUNA,
    "plain": _PLAIN,
}


# ---------------------------------------------------------------------------
# Cookbook (registry)
# ---------------------------------------------------------------------------

@dataclass
class Cookbook:
    """Registry of named chat templates."""

    templates: dict[str, ChatTemplate] = field(default_factory=dict)

    @classmethod
    def from_builtins(cls) -> Cookbook:
        return cls(templates=dict(BUILTINS))

    def add(self, name: str, template: ChatTemplate) -> None:
        if not isinstance(template, ChatTemplate):
            raise TypeError("template must be a ChatTemplate")
        self.templates[name.lower()] = template

    def get(self, name: str) -> ChatTemplate:
        key = name.lower()
        if key not in self.templates:
            raise KeyError(
                f"unknown chat template {name!r}; known: "
                f"{sorted(self.templates)}",
            )
        return self.templates[key]

    def __contains__(self, name: str) -> bool:
        return name.lower() in self.templates

    def names(self) -> list[str]:
        return sorted(self.templates)


#: Module-level default cookbook preloaded with every built-in.
COOKBOOK: Cookbook = Cookbook.from_builtins()


# ---------------------------------------------------------------------------
# Model → template resolver
# ---------------------------------------------------------------------------

#: Patterns matched against the (lower-cased) repo id / short name; the
#: first hit wins.  Order matters — more specific patterns first.
_MODEL_PATTERNS: tuple[tuple[str, str], ...] = (
    ("hyper-nix.2", "hyper-nix.2"),
    ("hypernix.2", "hyper-nix.2"),
    ("hyper-nix2", "hyper-nix.2"),
    ("hypernix2", "hyper-nix.2"),
    ("hyper-nix",  "plain"),         # v1 had no chat template
    ("nix-2.7",    "chatml"),
    ("nix2.7",     "chatml"),
    ("nix2.6",     "chatml"),
    ("nix2.5",     "chatml"),
    ("qwen3",      "chatml"),
    ("qwen2",      "chatml"),
    ("llama-3",    "llama3"),
    ("llama3",     "llama3"),
    ("llama-2",    "llama2"),
    ("llama2",     "llama2"),
    ("vicuna",     "vicuna"),
    ("alpaca",     "alpaca"),
    ("nano-nano",  "plain"),
    ("nano-mini",  "plain"),
)


def for_model(name_or_repo: str, *, default: str = "plain") -> ChatTemplate:
    """Pick the best chat template for a model by short name or
    full HF repo id.  Falls back to ``default`` (``"plain"``) if no
    pattern matches."""
    key = name_or_repo.lower()
    for pat, tmpl_name in _MODEL_PATTERNS:
        if pat in key:
            return COOKBOOK.get(tmpl_name)
    return COOKBOOK.get(default)


def cookbook(*, builtins: bool = True) -> Cookbook:
    """Construct a cookbook, optionally preloaded with the built-ins."""
    return Cookbook.from_builtins() if builtins else Cookbook()


def apply_template(
    messages: list[dict[str, str]],
    *,
    template: str | ChatTemplate = "hyper-nix.2",
    add_generation_prompt: bool = True,
) -> str:
    """One-shot helper: resolve ``template`` and call ``.apply``."""
    tmpl = template if isinstance(template, ChatTemplate) else COOKBOOK.get(template)
    return tmpl.apply(messages, add_generation_prompt=add_generation_prompt)


def list_templates() -> dict[str, str]:
    """Return ``{name: notes}`` for every registered template."""
    seen: dict[int, ChatTemplate] = {}
    for t in COOKBOOK.templates.values():
        seen.setdefault(id(t), t)
    return {t.name: t.notes for t in seen.values()}


__all__ = [
    "BUILTINS",
    "COOKBOOK",
    "ChatTemplate",
    "Cookbook",
    "HYPER_NIX_2",
    "apply_template",
    "cookbook",
    "for_model",
    "list_templates",
]
