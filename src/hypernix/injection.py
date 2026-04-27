"""injection — splice tokens / phrases into chat sequences.

Most chat models honour a small set of "scaffolding" tokens that
shape how they reason or respond.  ``injection`` surfaces a
clean primitive for inserting them at predictable positions:

* :class:`ThinkingInjector` — wraps the assistant's pre-reply
  scratchpad in ``<think>...</think>`` tokens (the convention
  popularised by Qwen's ``thinking`` mode and adopted by
  HyperNix-2).
* :class:`TestingInjector` — prepends a benchmark-style
  ``<|test|>`` token so callers can short-circuit a chat oven
  into evaluation mode.
* :class:`SystemOverrideInjector` — appends a one-shot system
  override (``<|system_override|>...``) without disturbing the
  caller's persistent system prompt.
* :class:`CustomInjector` — generic prefix / suffix injector for
  ad-hoc tokens.

Two injection scopes:

* :meth:`Injector.inject_messages` — operates on a
  ``[{"role", "content"}, ...]`` list (the input to
  ``oven.chat`` / ``Countertop.say``).  Returns a new list; the
  caller's list is left untouched.
* :meth:`Injector.inject_text` — operates on the rendered
  prompt string (e.g. for callers that already turned messages
  into a prompt via ``cookbook.apply_template``).

Both use the same ``mode`` enum:

* ``"prefix"`` — at the start of the assistant's pre-generation
  context,
* ``"suffix"`` — at the end (just before ``add_generation_prompt``),
* ``"wrap"``   — open at the start, close at the end.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Injection:
    """One concrete injection event recorded for provenance."""

    name: str
    open: str
    close: str = ""
    mode: str = "prefix"
    content: str = ""

    def render(self) -> str:
        if self.mode == "wrap":
            return f"{self.open}{self.content}{self.close}"
        if self.mode == "suffix":
            return self.open
        return self.open  # prefix


@dataclass
class Injector:
    """Base injector — subclasses set the open / close strings and
    the default mode."""

    open: str = ""
    close: str = ""
    content: str = ""
    mode: str = "prefix"
    name: str = "Injector"
    history: list[Injection] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.mode not in ("prefix", "suffix", "wrap"):
            raise ValueError(f"unknown mode {self.mode!r}; valid: prefix / suffix / wrap")

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def _record(self) -> Injection:
        ev = Injection(
            name=self.name, open=self.open, close=self.close,
            mode=self.mode, content=self.content,
        )
        self.history.append(ev)
        return ev

    def inject_text(self, prompt: str) -> str:
        """Splice into a rendered prompt string.  ``prefix`` and
        ``suffix`` modes append the open string at the start /
        end; ``wrap`` mode wraps the whole prompt."""
        ev = self._record()
        if self.mode == "prefix":
            return ev.open + prompt
        if self.mode == "suffix":
            return prompt + ev.open
        return ev.open + prompt + ev.close

    def inject_messages(
        self, messages: Iterable[dict[str, str]],
    ) -> list[dict[str, str]]:
        """Splice into a chat-message list.  Returns a new list."""
        msgs = [dict(m) for m in messages]
        ev = self._record()
        if self.mode == "prefix":
            msgs.insert(0, {"role": "system", "content": ev.open + (ev.content or "")})
        elif self.mode == "suffix":
            msgs.append({"role": "system", "content": ev.open + (ev.content or "")})
        else:  # wrap
            msgs.insert(0, {"role": "system", "content": ev.open})
            msgs.append({"role": "system", "content": ev.close})
        return msgs


# ---------------------------------------------------------------------------
# Thinking
# ---------------------------------------------------------------------------

@dataclass
class ThinkingInjector(Injector):
    """Wraps the assistant's pre-reply scratchpad in
    ``<think>...</think>`` tokens — the convention HyperNix-2,
    Qwen-3 thinking mode, and DeepSeek-R1 distilled checkpoints
    share."""

    open: str = "<think>"
    close: str = "</think>"
    content: str = ""
    mode: str = "wrap"
    name: str = "ThinkingInjector"


# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

@dataclass
class TestingInjector(Injector):
    """Prepends a benchmark-style ``<|test|>`` marker so an oven
    or judge can short-circuit normal chat behaviour and emit
    deterministic eval responses."""

    open: str = "<|test|>"
    close: str = "<|/test|>"
    mode: str = "prefix"
    name: str = "TestingInjector"


# ---------------------------------------------------------------------------
# System override
# ---------------------------------------------------------------------------

@dataclass
class SystemOverrideInjector(Injector):
    """Appends a *one-shot* system override.  Keeps the caller's
    persistent system prompt intact while letting a single turn
    push extra instructions."""

    open: str = "<|system_override|>"
    close: str = "<|/system_override|>"
    mode: str = "suffix"
    name: str = "SystemOverrideInjector"


# ---------------------------------------------------------------------------
# Generic
# ---------------------------------------------------------------------------

@dataclass
class CustomInjector(Injector):
    """Generic injector — supply your own ``open`` / ``close`` /
    ``content``.  Useful for niche tokens (e.g. ``<|search|>``,
    ``<|json|>``, ``<|tool_call|>``)."""

    name: str = "CustomInjector"


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

KINDS: dict[str, type[Injector]] = {
    "thinking": ThinkingInjector,
    "testing": TestingInjector,
    "system-override": SystemOverrideInjector,
    "custom": CustomInjector,
}


def injector(kind: str = "thinking", **kw: Any) -> Injector:
    if kind not in KINDS:
        raise ValueError(f"unknown injector kind {kind!r}; valid: {sorted(KINDS)}")
    return KINDS[kind](**kw)


def inject(
    messages: Iterable[dict[str, str]] | str,
    *,
    kind: str = "thinking",
    **kw: Any,
):
    """One-shot helper.  ``inject(messages, kind="thinking")``."""
    inj = injector(kind=kind, **kw)
    if isinstance(messages, str):
        return inj.inject_text(messages)
    return inj.inject_messages(messages)


__all__ = [
    "CustomInjector",
    "Injection",
    "Injector",
    "KINDS",
    "SystemOverrideInjector",
    "TestingInjector",
    "ThinkingInjector",
    "inject",
    "injector",
]
