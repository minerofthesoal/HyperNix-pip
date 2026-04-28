"""menu — system-prompt presets.

A menu lists the dishes a kitchen serves.  Here it lists the
*personas* (system prompts) you might point a chat model at.

Built-in entries cover the common cases:

* ``"default"``     — terse helpful assistant.
* ``"concise"``     — same but harder-capped on length.
* ``"code-helper"`` — Python-leaning code assistant; refuses
                      destructive shell suggestions.
* ``"judge"``       — pair-rating judge (returns A / B / T).
* ``"creative"``    — story / brainstorm persona.
* ``"chef"``        — flavour-text persona that fits the kitchen
                      idiom of the rest of the package.
* ``"hyper-nix"``   — the default system prompt embedded in
                      :data:`hypernix.cookbook.HYPER_NIX_2`.

Quick use::

    from hypernix.menu import MENU
    sys_prompt = MENU.get("code-helper")

    from hypernix.countertop import Countertop
    ct = Countertop(oven, system=sys_prompt)
    ct.say("write me a fizzbuzz")

You can extend with ``MENU.add("my-bot", "...")``, persist with
``MENU.save("./prompts.json")``, and load anywhere with
``Menu.load("./prompts.json")``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

#: The embedded built-in personas.
BUILTIN_PROMPTS: dict[str, str] = {
    "default": (
        "You are a helpful assistant. Answer concisely and accurately. "
        "If you don't know something, say so."
    ),
    "concise": (
        "You are a helpful assistant. Always answer in three sentences "
        "or fewer. Skip preamble."
    ),
    "code-helper": (
        "You are a coding assistant. Default to Python unless told "
        "otherwise. Show working code with minimal commentary. Never "
        "suggest commands that delete files (rm -rf, drop table) "
        "without an explicit warning."
    ),
    "judge": (
        "You are an impartial judge. You will be given two responses "
        "(A and B) to the same prompt. Reply with exactly one letter: "
        "A if response A is better, B if response B is better, T if "
        "they are tied. No other text."
    ),
    "creative": (
        "You are a creative writing partner. Be vivid and imaginative. "
        "Take risks; surprise the reader. When asked to brainstorm, "
        "give five distinct directions."
    ),
    "chef": (
        "You are HyperNix, the head chef of the cooking-themed Python "
        "package hypernix. Keep replies short, technical, and use "
        "kitchen metaphors when explaining ML concepts."
    ),
    "hyper-nix": (
        "You are HyperNix, a helpful assistant. Answer concisely and "
        "accurately. If you don't know, say so."
    ),
}


@dataclass
class Menu:
    """Named system-prompt registry."""

    prompts: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_builtins(cls) -> Menu:
        return cls(prompts=dict(BUILTIN_PROMPTS))

    def add(self, name: str, prompt: str) -> None:
        if not isinstance(prompt, str):
            raise TypeError("prompt must be a str")
        if not prompt.strip():
            raise ValueError("prompt cannot be empty / whitespace-only")
        self.prompts[name] = prompt

    def get(self, name: str) -> str:
        if name not in self.prompts:
            raise KeyError(
                f"unknown menu entry {name!r}; known: {sorted(self.prompts)}",
            )
        return self.prompts[name]

    def remove(self, name: str) -> None:
        del self.prompts[name]

    def __contains__(self, name: str) -> bool:
        return name in self.prompts

    def __len__(self) -> int:
        return len(self.prompts)

    def names(self) -> list[str]:
        return sorted(self.prompts)

    def default(self) -> str:
        """Convenience: return the ``"default"`` entry, or the first
        registered prompt if ``"default"`` isn't present."""
        if "default" in self.prompts:
            return self.prompts["default"]
        if not self.prompts:
            raise KeyError("menu is empty")
        return self.prompts[next(iter(self.prompts))]

    def find(self, query: str) -> str | None:
        """Fuzzy-lookup a persona name (v0.61.1).

        Tries exact match → case-insensitive exact → substring match
        → prefix match.  Returns the matched key, or ``None`` if no
        single unambiguous candidate is found.  When multiple
        substring matches exist, ``None`` is returned to force the
        caller to disambiguate.
        """
        if not query:
            return None
        if query in self.prompts:
            return query
        ql = query.lower()
        for k in self.prompts:
            if k.lower() == ql:
                return k
        # Substring matches.
        subs = [k for k in self.prompts if ql in k.lower()]
        if len(subs) == 1:
            return subs[0]
        # Prefix matches.
        pre = [k for k in self.prompts if k.lower().startswith(ql)]
        if len(pre) == 1:
            return pre[0]
        return None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: Path | str) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(self.prompts, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return p

    @classmethod
    def load(cls, path: Path | str) -> Menu:
        p = Path(path)
        return cls(prompts=json.loads(p.read_text(encoding="utf-8")))


#: Module-level default menu preloaded with every built-in persona.
MENU: Menu = Menu.from_builtins()


def menu(*, builtins: bool = True) -> Menu:
    """Construct a menu, optionally preloaded with the built-ins."""
    return Menu.from_builtins() if builtins else Menu()


__all__ = [
    "BUILTIN_PROMPTS",
    "MENU",
    "Menu",
    "menu",
]
