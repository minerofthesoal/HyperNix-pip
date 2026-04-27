"""countertop — multi-turn chat session workspace.

A countertop is where you keep the dishes you're actively working
with.  The :class:`Countertop` class is the same idea for chat:

* keeps a system message + the running list of user / assistant
  turns,
* knows the chat template to use (resolved automatically from the
  oven's repo id, overridable),
* generates a reply each time you call :meth:`Countertop.say`,
* trims the oldest turns when the conversation outgrows
  ``max_history_tokens``,
* persists to / loads from JSON so you can pick up a session in a
  new process.

Quick start::

    from hypernix.old_oven import preheat
    from hypernix.countertop import Countertop

    oven = preheat("hyper-nix.2")
    chat = Countertop(oven, system="You are a helpful chef.")

    print(chat.say("How do I dice an onion?"))
    print(chat.say("And how about a shallot?"))

    chat.save("session.json")

Streaming::

    from hypernix.bell import stdout_bell
    chat = Countertop(oven, system="…", bell=stdout_bell())
    chat.say("explain transformers in 3 sentences")  # tokens stream live

Together with :mod:`hypernix.cookbook` and :mod:`hypernix.menu`,
this is the headline v0.51 chat surface.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import cookbook as _cookbook
from .bell import Bell
from .cookbook import ChatTemplate
from .flour import Flour


@dataclass
class Countertop:
    """A persistent multi-turn chat session bound to an oven.

    Args:
        oven: An object exposing ``.chat(messages, **kwargs) -> str``
            (e.g. :class:`hypernix.old_oven.CodeOven`).
        system: Optional system prompt prepended on the first turn.
            ``None`` means no system message.
        template: Chat template name or :class:`ChatTemplate`
            instance.  When ``None`` it's auto-resolved from
            ``oven.repo_id`` via :func:`hypernix.cookbook.for_model`.
        max_history_tokens: When the running transcript exceeds this
            many *characters* (a cheap proxy for tokens), the oldest
            user / assistant pair is dropped.  ``None`` disables
            trimming.
        bell: Optional :class:`hypernix.bell.Bell` for streaming
            output.  If set, :meth:`say` streams through it.
        flour: Optional :class:`hypernix.flour.Flour` chat-quality
            processor.  When set, every reply is cleaned via
            :meth:`Flour.clean_reply` (strip role-leak / stop
            markers).  When ``bell`` is also set, the same flour is
            attached to the bell so logits are processed during
            generation as well.
        sampling: Default sampling kwargs forwarded to ``oven.chat``.
    """

    oven: Any
    system: str | None = None
    template: str | ChatTemplate | None = None
    max_history_tokens: int | None = None
    bell: Bell | None = None
    flour: Flour | None = None
    sampling: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Resolve template lazily on first use; here we just normalise.
        if isinstance(self.template, str):
            self.template = _cookbook.COOKBOOK.get(self.template)
        # Hand the flour to the bell so logits are processed during
        # streamed generation too.
        if self.flour is not None and self.bell is not None and self.bell.flour is None:
            self.bell.flour = self.flour

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def say(
        self,
        user: str,
        *,
        max_new_tokens: int | None = None,
        temperature: float | None = None,
        top_k: int | None = None,
        top_p: float | None = None,
        seed: int | None = None,
    ) -> str:
        """Append ``user`` to the transcript, generate a reply, append
        the reply, return it."""
        self.history.append({"role": "user", "content": user})
        self._trim()
        kwargs: dict[str, Any] = dict(self.sampling)
        for k, v in (
            ("max_new_tokens", max_new_tokens),
            ("temperature", temperature),
            ("top_k", top_k),
            ("top_p", top_p),
            ("seed", seed),
        ):
            if v is not None:
                kwargs[k] = v

        messages = self._messages_with_system()
        if self.bell is not None:
            reply = self.bell.stream_chat(self.oven, messages, **kwargs)
        else:
            reply = self.oven.chat(messages, **kwargs)
        # Strip a single trailing newline that some templates leave on.
        reply = reply.rstrip("\n")
        if self.flour is not None:
            reply = self.flour.clean_reply(reply)
        self.history.append({"role": "assistant", "content": reply})
        return reply

    def reset(self) -> None:
        """Clear the running transcript (keeps ``system`` and config)."""
        self.history = []

    def messages(self) -> list[dict[str, str]]:
        """Return the full message list including the system prompt
        (if any) — handy for handing to a different runner."""
        return self._messages_with_system()

    def render(self, *, add_generation_prompt: bool = True) -> str:
        """Render the current transcript through the chat template
        without generating anything.  Useful for debugging the prompt
        you're about to send."""
        tmpl = self._template()
        return tmpl.apply(
            self._messages_with_system(),
            add_generation_prompt=add_generation_prompt,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: Path | str) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "system": self.system,
            "history": self.history,
            "template": self._template_name(),
            "max_history_tokens": self.max_history_tokens,
            "sampling": self.sampling,
        }
        p.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return p

    @classmethod
    def load(cls, path: Path | str, oven: Any) -> Countertop:
        p = Path(path)
        data = json.loads(p.read_text(encoding="utf-8"))
        ct = cls(
            oven=oven,
            system=data.get("system"),
            template=data.get("template"),
            max_history_tokens=data.get("max_history_tokens"),
            sampling=data.get("sampling") or {},
        )
        ct.history = list(data.get("history") or [])
        return ct

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _template(self) -> ChatTemplate:
        if isinstance(self.template, ChatTemplate):
            return self.template
        repo = getattr(self.oven, "repo_id", "") or ""
        tmpl = _cookbook.for_model(str(repo))
        self.template = tmpl
        return tmpl

    def _template_name(self) -> str | None:
        if isinstance(self.template, ChatTemplate):
            return self.template.name
        if isinstance(self.template, str):
            return self.template
        return None

    def _messages_with_system(self) -> list[dict[str, str]]:
        msgs = list(self.history)
        if self.system:
            msgs = [{"role": "system", "content": self.system}, *msgs]
        return copy.deepcopy(msgs)

    def _trim(self) -> None:
        """Drop the oldest user/assistant pair while the rendered
        transcript exceeds ``max_history_tokens`` characters."""
        if not self.max_history_tokens:
            return
        # Keep at least the most recent user turn.
        while len(self.history) > 1:
            rendered = self._template().apply(
                self._messages_with_system(),
                add_generation_prompt=True,
            )
            if len(rendered) <= self.max_history_tokens:
                return
            # Drop the oldest non-system pair (history doesn't include
            # system; system lives on the dataclass).
            drop = 2 if len(self.history) >= 2 else 1
            del self.history[:drop]


# ---------------------------------------------------------------------------
# Convenience constructor
# ---------------------------------------------------------------------------

def countertop(
    oven: Any,
    *,
    system: str | None = None,
    persona: str | None = None,
    template: str | ChatTemplate | None = None,
    max_history_tokens: int | None = None,
    bell: Bell | None = None,
    flour: Flour | None = None,
    **sampling: Any,
) -> Countertop:
    """Build a :class:`Countertop`.

    ``persona`` is a shortcut for picking a system prompt by name from
    :data:`hypernix.menu.MENU` — equivalent to passing
    ``system=MENU.get(persona)`` but avoids the import dance at the
    call site.
    """
    if persona is not None:
        if system is not None:
            raise ValueError("pass exactly one of system= or persona=")
        from .menu import MENU
        system = MENU.get(persona)
    return Countertop(
        oven=oven,
        system=system,
        template=template,
        max_history_tokens=max_history_tokens,
        bell=bell,
        flour=flour,
        sampling=sampling,
    )


__all__ = ["Countertop", "countertop"]
