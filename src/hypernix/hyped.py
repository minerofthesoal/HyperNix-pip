"""hyped — high-quality TUI chat CLI for the HyperNix family.

Run with the ``hyped`` console script (registered in
``pyproject.toml``)::

    hyped                           # opens the configurator, then chat
    hyped --model hyper-nix.2       # skip the picker and chat now
    hyped --persona chef            # pick a system-prompt persona by name
    hyped --no-color                # disable ANSI colour
    hyped --ascii                   # ASCII fallback (no Unicode boxes)

Two-screen TUI:

1. **Configurator** — pick a model from the curated short-list
   (``hyper-Nix.2``, ``hyper-nix.1``, ``nix2.7a``, ``nix2.6-mm``,
   ``qwen3.5-*``, ``nano-nano-v4``, ``nano-mini-6.99-v2``,
   ``nano-nano-927-v3``, plus a "browse all" tier that lists every
   entry in :data:`hypernix.KNOWN_MODELS`).  Then pick a persona
   (from :data:`hypernix.menu.MENU`), tweak sampling defaults, and
   press Enter to load.
2. **Chat** — full-screen panel layout: status bar at the top,
   scrollable transcript, then a typing prompt at the bottom.
   Streams tokens through :class:`hypernix.bell.Bell` and applies
   :class:`hypernix.flour.Flour` for chat-quality cleanup.

Zero hard dependencies — pure stdlib + ANSI escape codes.
``readline`` is loaded when available so up-arrow recall and
inline editing Just Work.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Any

from . import menu as _menu
from .download import KNOWN_MODELS

try:  # graceful — readline isn't on every Windows Python.
    import readline  # noqa: F401
except Exception:  # noqa: BLE001
    pass


# ---------------------------------------------------------------------------
# Curated model short-list — what the configurator shows by default.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelEntry:
    short: str
    repo_id: str
    label: str
    family: str = ""
    badge: str = ""


CURATED_MODELS: tuple[ModelEntry, ...] = (
    # v0.61.1: hyper-Nix.2 demoted from ★ to ⚠ — chat-tuned but very
    # undertrained, see hypernix.utils.warn_hyper_nix_2.  Real
    # recommended default for chat is now nix2.7a.
    ModelEntry("hyper-nix.2",      "ray0rf1re/hyper-Nix.2",  "⚠ undertrained — see warning",         "HyperNix",   "⚠"),
    ModelEntry("hyper-nix.1",      "ray0rf1re/hyper-nix.1",  "v1 base model — solid, no chat tune",  "HyperNix",   ""),
    ModelEntry("nix2.7a",          "Nix-ai/Nix-2.7a",        "Nix 2.7a — 2B Qwen2-shape",            "Nix",        ""),
    ModelEntry("nix2.6-mm",        "Nix-ai/Nix2.6-mm",       "Nix 2.6-mm — 3B Qwen2-shape",          "Nix",        ""),
    ModelEntry("nix2.5",           "ray0rf1re/Nix2.5",       "Nix 2.5 — 3B Qwen2, tied embeds",      "Nix",        ""),
    ModelEntry("qwen3.5-0.8b",     "Qwen/Qwen3.5-0.8B",      "Qwen3.5 0.8B — AutoModel",             "Qwen 3.5",   ""),
    ModelEntry("qwen3.5-2b",       "Qwen/Qwen3.5-2B",        "Qwen3.5 2B — AutoModel",               "Qwen 3.5",   ""),
    ModelEntry("qwen3.5-4b",       "Qwen/Qwen3.5-4B",        "Qwen3.5 4B — AutoModel",               "Qwen 3.5",   ""),
    ModelEntry("qwen3.5-9b",       "Qwen/Qwen3.5-9B",        "Qwen3.5 9B — AutoModel",               "Qwen 3.5",   ""),
    ModelEntry("nano-nano-v4",     "ray0rf1re/Nano-nano-v4", "Llama-shape, 14L/896d",                "Nano",       ""),
    ModelEntry("nano-mini-6.99-v2", "ray0rf1re/Nano-mini-6.99-v2", "Llama-shape, 12L/768d",          "Nano",       ""),
    ModelEntry("nano-nano-927-v3", "ray0rf1re/nano-nano-927-v3",  "custom NanoNano, 12L/120d",       "Nano",       ""),
)


# ---------------------------------------------------------------------------
# Sampling profile
# ---------------------------------------------------------------------------

@dataclass
class SamplingConfig:
    temperature: float = 0.7
    top_k: int = 40
    top_p: float = 0.95
    max_new_tokens: int = 256
    seed: int | None = None
    persona: str | None = None
    flour_preset: str = "smart"   # smart | aggressive | off

    def to_kwargs(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "top_k": self.top_k,
            "top_p": self.top_p,
            "max_new_tokens": self.max_new_tokens,
            "seed": self.seed,
        }


# ---------------------------------------------------------------------------
# ANSI / panel helpers (lighter than tv.py but visually consistent).
# ---------------------------------------------------------------------------

CSI = "\x1b["
CLEAR = f"{CSI}2J{CSI}H"
HIDE_CURSOR = f"{CSI}?25l"
SHOW_CURSOR = f"{CSI}?25h"
SAVE_POS = f"{CSI}s"
RESTORE_POS = f"{CSI}u"

# 256-color foreground helper
_C256_FG = "\x1b[38;5;{}m"
_C256_BG = "\x1b[48;5;{}m"
_RESET = "\x1b[0m"

# Palette: violet → blue → cyan gradient used for the header sigil
_SIGIL_COLORS = [129, 135, 141, 147, 153, 159, 51, 45, 39, 33, 27, 21]
# Panel border / accent colors (256-color)
_ACCENT_BLUE   = 33    # bright blue
_ACCENT_CYAN   = 51    # electric cyan
_ACCENT_VIOLET = 135   # violet
_ACCENT_GOLD   = 220   # golden yellow for warnings
_ACCENT_GREEN  = 82    # bright green for OK
_ACCENT_RED    = 196   # bright red for errors


def _color(code: int, text: str, *, on: bool = True) -> str:
    return f"{CSI}{code}m{text}{CSI}0m" if on else text


def _c256(n: int, text: str, *, on: bool = True) -> str:
    """Apply a 256-color foreground to text."""
    return f"{_C256_FG.format(n)}{text}{_RESET}" if on else text


def _bold(text: str, *, on: bool = True) -> str:
    return _color(1, text, on=on) if on else text


def _dim(text: str, *, on: bool = True) -> str:
    return f"{CSI}2m{text}{_RESET}" if on else text


def _italic(text: str, *, on: bool = True) -> str:
    return f"{CSI}3m{text}{_RESET}" if on else text


def _render_sigil_line(line: str, colors: list[int], *, on: bool = True) -> str:
    """Apply a rolling color gradient across the characters of a sigil line."""
    if not on:
        return line
    out = []
    ci = 0
    for ch in line:
        if ch != ' ':
            out.append(f"{_C256_FG.format(colors[ci % len(colors)])}{ch}")
            ci += 1
        else:
            out.append(ch)
    return ''.join(out) + _RESET


# HyperNix ASCII art sigil (compact, 5 lines)
_HYPED_SIGIL = [
    r" ██╗  ██╗██╗   ██╗██████╗ ███████╗██████╗ ",
    r" ██║  ██║╚██╗ ██╔╝██╔══██╗██╔════╝██╔══██╗",
    r" ███████║ ╚████╔╝ ██████╔╝█████╗  ██║  ██║",
    r" ██╔══██║  ╚██╔╝  ██╔═══╝ ██╔══╝  ██║  ██║",
    r" ██║  ██║   ██║   ██║     ███████╗██████╔╝",
]

def _panel(
    title: str,
    body: list[str],
    *,
    width: int,
    color: bool,
    ascii_only: bool,
    title_color: int = 135,   # updated: violet 256-color
    border_color: int = 33,   # updated: blue 256-color
) -> list[str]:
    if ascii_only:
        tl, tr, bl, br, h, v = "+", "+", "+", "+", "-", "|"
    else:
        tl, tr, bl, br, h, v = "╭", "╮", "╰", "╯", "─", "│"
    inner = max(1, width - 2)
    if color:
        def _bc(s):
            return f"{_C256_FG.format(border_color)}{s}{_RESET}"
        def _tc(s):
            return f"{_C256_FG.format(title_color)}{_C256_BG.format(234)}\x1b[1m{s}{_RESET}"
    else:
        def _bc(s):
            return s
        def _tc(s):
            return s
    title_render = _tc(f" {title} ")
    title_vis = len(f" {title} ")
    fill = max(0, inner - 2 - title_vis)
    top_left  = _bc(tl + h)
    top_right = _bc(h * fill + tr)
    rows = [top_left + title_render + top_right]
    for ln in body:
        plain = _strip_ansi(ln)
        pad = max(0, inner - len(plain))
        rows.append(_bc(v) + ln + " " * pad + _bc(v))
    rows.append(_bc(bl + h * inner + br))
    return rows


def _strip_ansi(s: str) -> str:
    import re
    return re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", s)


def _term_width(default: int = 100) -> int:
    import shutil
    try:
        return shutil.get_terminal_size((default, 24)).columns
    except Exception:  # noqa: BLE001
        return default


# ---------------------------------------------------------------------------
# Configurator — pick model + persona + sampling
# ---------------------------------------------------------------------------

@dataclass
class Configurator:
    color: bool = True
    ascii_only: bool = False
    width: int | None = None
    chosen_model: ModelEntry | None = None
    sampling: SamplingConfig = field(default_factory=SamplingConfig)
    extra_models: tuple[ModelEntry, ...] = ()

    def _w(self) -> int:
        return max(60, self.width or _term_width())

    # ------------------------------------------------------------------
    # Render: model picker
    # ------------------------------------------------------------------

    def render_model_picker(self) -> str:
        c = self.color and not self.ascii_only
        rows: list[str] = []
        rows.append("")

        # Gradient sigil header
        if c:
            for sigil_line in _HYPED_SIGIL:
                rendered = _render_sigil_line(sigil_line, _SIGIL_COLORS, on=True)
                rows.append(rendered)
            rows.append(_dim("   chat interface  ·  v0.70.6", on=True))
        else:
            rows.append("  === hyped · pick a model ===")
        rows.append("")

        # Group models by family for visual structure.
        body: list[str] = []
        family_groups: dict[str, list[tuple[int, ModelEntry]]] = {}
        for i, m in enumerate(CURATED_MODELS, 1):
            family_groups.setdefault(m.family, []).append((i, m))
        family_order = ["HyperNix", "Nix", "Qwen 3.5", "Nano"]
        for fam in family_order:
            entries = family_groups.get(fam, [])
            if not entries:
                continue
            body.append(_color(33, f"  {fam}", on=c))
            for idx, m in entries:
                # Patch (0.61.1): use ASCII '*' badge in --ascii mode
                # so non-UTF terminals don't render '?' for the star.
                raw_badge = m.badge if not self.ascii_only else ("*" if m.badge else "")
                badge = _color(93, raw_badge, on=c) if raw_badge else " "
                line = f"  {idx:>2}. {badge} {m.short:<22}  {_color(90, m.label, on=c)}"
                body.append(line)
            body.append("")
        body.append(_color(35, "   0. browse all (full KNOWN_MODELS)", on=c))
        body.append("")
        body.append(_color(90, "  Type a number, or use --model <short> to skip this screen.", on=c))

        for ln in body:
            rows.append(ln)
        return "\n".join(rows)

    # ------------------------------------------------------------------
    # Picker flow
    # ------------------------------------------------------------------

    def pick_model_interactive(self) -> ModelEntry:
        print(CLEAR + self.render_model_picker())
        while True:
            try:
                raw = input("\n  choose [1-12, 0=all]: ").strip()
            except EOFError:
                raw = "1"
            if not raw:
                continue
            if raw == "0":
                return self._pick_from_all_known()
            try:
                idx = int(raw)
            except ValueError:
                print(_color(31, "  not a number — try again.", on=self.color))
                continue
            if 1 <= idx <= len(CURATED_MODELS):
                return CURATED_MODELS[idx - 1]
            print(_color(31, f"  out of range — pick 0..{len(CURATED_MODELS)}.", on=self.color))

    def _pick_from_all_known(self) -> ModelEntry:
        c = self.color and not self.ascii_only
        items = sorted(KNOWN_MODELS.items())
        print()
        print(_color(96, _bold(" hyped · all known models", on=c), on=c))
        print()
        for i, (short, info) in enumerate(items, 1):
            line = f"  {i:>3}. {short:<28} {_color(90, info.repo_id, on=c)}"
            print(line)
        print()
        while True:
            try:
                raw = input(f"  choose [1-{len(items)}]: ").strip()
            except EOFError:
                raw = "1"
            if not raw:
                continue
            try:
                idx = int(raw)
            except ValueError:
                print(_color(31, "  not a number.", on=self.color))
                continue
            if 1 <= idx <= len(items):
                short, info = items[idx - 1]
                return ModelEntry(short, info.repo_id, info.notes or "", "")
            print(_color(31, "  out of range.", on=self.color))

    def pick_persona_interactive(self) -> str | None:
        c = self.color and not self.ascii_only
        names = _menu.MENU.names()
        print()
        print(_color(96, _bold(" hyped · pick a persona", on=c), on=c))
        print()
        for i, name in enumerate(names, 1):
            preview = _menu.MENU.get(name)
            preview = preview[:60] + ("…" if len(preview) > 60 else "")
            print(f"  {i:>2}. {name:<14} {_color(90, preview, on=c)}")
        print(_color(35, "   0. (no persona — use the model's default)", on=c))
        print()
        while True:
            try:
                raw = input(f"  choose [0-{len(names)}]: ").strip()
            except EOFError:
                raw = "0"
            if raw == "":
                return None
            if raw == "0":
                return None
            try:
                idx = int(raw)
            except ValueError:
                print(_color(31, "  not a number.", on=self.color))
                continue
            if 1 <= idx <= len(names):
                return names[idx - 1]
            print(_color(31, "  out of range.", on=self.color))

    def pick_sampling_interactive(self) -> SamplingConfig:
        c = self.color and not self.ascii_only
        s = self.sampling
        print()
        print(_color(96, _bold(" hyped · sampling", on=c), on=c))
        print(_color(90, "  press Enter to accept the default in [brackets].", on=c))
        print()
        s.temperature = self._ask_float("temperature", s.temperature)
        s.top_p = self._ask_float("top_p", s.top_p)
        s.top_k = self._ask_int("top_k", s.top_k)
        s.max_new_tokens = self._ask_int("max_new_tokens", s.max_new_tokens)
        return s

    def _ask_float(self, label: str, default: float) -> float:
        try:
            raw = input(f"  {label} [{default}]: ").strip()
        except EOFError:
            return default
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            print(_color(33, "  not a number — keeping default.", on=self.color))
            return default

    def _ask_int(self, label: str, default: int) -> int:
        try:
            raw = input(f"  {label} [{default}]: ").strip()
        except EOFError:
            return default
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            print(_color(33, "  not a number — keeping default.", on=self.color))
            return default

    def run(self) -> tuple[ModelEntry, SamplingConfig]:
        model = self.pick_model_interactive()
        persona = self.pick_persona_interactive()
        sampling = self.pick_sampling_interactive()
        sampling.persona = persona
        self.chosen_model = model
        self.sampling = sampling
        return model, sampling


# ---------------------------------------------------------------------------
# Chat screen
# ---------------------------------------------------------------------------

@dataclass
class ChatScreen:
    oven: Any
    model_entry: ModelEntry
    sampling: SamplingConfig
    color: bool = True
    ascii_only: bool = False
    width: int | None = None
    history: list[dict[str, str]] = field(default_factory=list)
    countertop: Any = None
    bell: Any = None
    flour: Any = None

    def __post_init__(self) -> None:
        # Lazy-build a Countertop bound to the oven so we get auto
        # template-resolution + replay history for free.
        from . import bell as _bell_mod
        from . import countertop as _ct_mod
        from . import flour as _flour_mod
        from . import menu as _menu_mod

        system = None
        if self.sampling.persona:
            try:
                system = _menu_mod.MENU.get(self.sampling.persona)
            except KeyError:
                system = None

        if self.sampling.flour_preset == "smart":
            self.flour = _flour_mod.Flour.smart_default(template="hyper-nix.2")
        elif self.sampling.flour_preset == "aggressive":
            self.flour = _flour_mod.Flour.aggressive(template="hyper-nix.2")
        else:
            self.flour = _flour_mod.Flour.off()

        # Patch (0.61.1): bind the bell to the countertop so say()
        # streams through it; the chat-turn callback below registers
        # an on_token printer that runs during stream_chat.  This way
        # all history-management (append + trim + cleanup) stays in
        # Countertop instead of being duplicated in ChatScreen.
        self.bell = _bell_mod.Bell(flour=self.flour)
        self.countertop = _ct_mod.Countertop(
            oven=self.oven,
            system=system,
            bell=self.bell,
            flour=self.flour,
            sampling=self.sampling.to_kwargs(),
        )

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def _w(self) -> int:
        return max(60, self.width or _term_width())

    def render(self) -> str:
        w = self._w()
        c = self.color and not self.ascii_only
        # Status bar
        persona = self.sampling.persona or "—"
        status_body = [
            f" model:    {_color(36, self.model_entry.short, on=c):<22}  "
            f"repo: {_color(90, self.model_entry.repo_id, on=c)}",
            f" persona:  {persona:<22}  temp={self.sampling.temperature}  "
            f"top_p={self.sampling.top_p}  top_k={self.sampling.top_k}  "
            f"max={self.sampling.max_new_tokens}",
            f" turns:    {len(self.countertop.history) // 2:<22}  "
            f"flour: {self.sampling.flour_preset}",
        ]
        status_panel = _panel(
            "hyped · chat", status_body, width=w,
            color=c, ascii_only=self.ascii_only, title_color=96,
        )

        # Conversation panel — last several turns.
        conv_body: list[str] = []
        if not self.countertop.history:
            conv_body.append(_color(90, "  (no messages yet — say something below)", on=c))
        for msg in self.countertop.history[-12:]:
            role = msg["role"]
            content = msg["content"]
            label = (
                _color(36, "user>", on=c) if role == "user"
                else _color(33, "assistant>", on=c)
            )
            for line in _wrap(content, max_width=w - 14):
                conv_body.append(f" {label} {line}")
                label = "       " if role == "user" else "             "
            conv_body.append("")
        conv_panel = _panel(
            "conversation", conv_body, width=w,
            color=c, ascii_only=self.ascii_only, title_color=33,
        )

        return "\n".join(status_panel + [""] + conv_panel)

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        c = self.color and not self.ascii_only
        commands_help = _color(
            90,
            " /quit  exit · /reset  clear history · /persona <name>  switch · "
            "/save <path>  save transcript",
            on=c,
        )
        try:
            while True:
                sys.stdout.write(CLEAR + self.render() + "\n" + commands_help + "\n\n")
                sys.stdout.flush()
                try:
                    user = input("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if not user:
                    continue
                if user.startswith("/"):
                    if self._handle_command(user):
                        break
                    continue
                self._chat_turn(user)
        finally:
            sys.stdout.write(SHOW_CURSOR)
            sys.stdout.flush()

    def _handle_command(self, line: str) -> bool:
        """Returns True when the command should exit the loop."""
        c = self.color and not self.ascii_only
        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        if cmd in ("/quit", "/exit", "/q"):
            return True
        if cmd in ("/reset", "/clear"):
            self.countertop.reset()
            print(_color(90, "  (history cleared)", on=c))
            time.sleep(0.4)
            return False
        if cmd == "/persona":
            if not arg:
                print(_color(33, "  /persona <name>  (try: " + ", ".join(_menu.MENU.names()) + ")", on=c))
                time.sleep(1.5)
                return False
            try:
                self.countertop.system = _menu.MENU.get(arg)
                self.sampling.persona = arg
                print(_color(36, f"  persona → {arg}", on=c))
            except KeyError:
                print(_color(31, f"  no persona named {arg!r}", on=c))
            time.sleep(0.6)
            return False
        if cmd == "/save":
            from pathlib import Path
            target = Path(arg or "hyped-session.json")
            self.countertop.save(target)
            print(_color(36, f"  saved → {target}", on=c))
            time.sleep(0.6)
            return False
        if cmd == "/help":
            print(_color(33, "  commands: /quit /reset /persona <name> /save <path>", on=c))
            time.sleep(1.0)
            return False
        print(_color(31, f"  unknown command {cmd!r}; try /help", on=c))
        time.sleep(0.6)
        return False

    def _chat_turn(self, user: str) -> None:
        c = self.color and not self.ascii_only
        sys.stdout.write(_color(33, "\nassistant> ", on=c))
        sys.stdout.flush()

        # Patch (0.61.1): register a one-shot token printer on the
        # bell, then route through Countertop.say().  Countertop owns
        # history append + trim + flour.clean_reply.  We pop the
        # callback after the turn so successive turns don't double-
        # print.
        def _print_token(tok: str, _idx: int) -> None:
            sys.stdout.write(tok)
            sys.stdout.flush()

        self.bell.token_callbacks.append(_print_token)
        try:
            self.countertop.say(user)
        except KeyboardInterrupt:
            sys.stdout.write(_color(90, " [interrupted]", on=c))
        finally:
            try:
                self.bell.token_callbacks.remove(_print_token)
            except ValueError:
                pass
        sys.stdout.write("\n\n")
        sys.stdout.flush()
        time.sleep(0.4)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wrap(text: str, *, max_width: int) -> list[str]:
    out: list[str] = []
    for paragraph in text.splitlines() or [""]:
        if not paragraph:
            out.append("")
            continue
        line = ""
        for word in paragraph.split(" "):
            if len(line) + len(word) + 1 > max_width:
                if line:
                    out.append(line)
                line = word
            else:
                line = (line + " " + word) if line else word
        if line:
            out.append(line)
    return out or [""]


def _resolve_short_name(short: str) -> ModelEntry | None:
    key = short.lower()
    for m in CURATED_MODELS:
        if m.short.lower() == key:
            return m
    info = KNOWN_MODELS.get(key)
    if info is not None:
        return ModelEntry(short, info.repo_id, info.notes or "", "")
    return None


# ---------------------------------------------------------------------------
# CLI entry point — installed as ``hyped``
# ---------------------------------------------------------------------------

def cli_main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    color = True
    ascii_only = False
    model_short: str | None = None
    persona: str | None = None

    if "--no-color" in args:
        color = False
        args.remove("--no-color")
    if "--ascii" in args:
        ascii_only = True
        args.remove("--ascii")
    if "--model" in args:
        i = args.index("--model")
        if i + 1 < len(args):
            model_short = args[i + 1]
            del args[i : i + 2]
    if "--persona" in args:
        i = args.index("--persona")
        if i + 1 < len(args):
            persona = args[i + 1]
            del args[i : i + 2]
    if "--help" in args or "-h" in args:
        print(
            "usage: hyped [--model SHORT] [--persona NAME] [--no-color] [--ascii]\n"
            "  --model     skip the picker and chat with the named model\n"
            "  --persona   use a named system prompt from hypernix.menu\n"
            "  --no-color  disable ANSI colour\n"
            "  --ascii     ASCII fallback (no Unicode boxes)",
        )
        return 0

    cfg = Configurator(color=color, ascii_only=ascii_only)
    if model_short:
        entry = _resolve_short_name(model_short)
        if entry is None:
            print(f"hyped: unknown model {model_short!r}", file=sys.stderr)
            return 2
        sampling = SamplingConfig()
        if persona:
            sampling.persona = persona
    else:
        try:
            entry, sampling = cfg.run()
        except KeyboardInterrupt:
            print()
            return 130
        if persona:
            sampling.persona = persona

    # v0.61.1: surface the MAJOR undertrained warning before we
    # even try to load.  ``preheat`` will repeat the warning idempotently
    # but firing it here too means a user reading scrollback sees it
    # right next to the model they picked.
    try:
        from .utils import warn_hyper_nix_2
        warn_hyper_nix_2(entry.repo_id)
    except Exception:  # noqa: BLE001
        pass

    print(_color(96, _bold(f"\n  loading {entry.short} ({entry.repo_id})…", on=color), on=color))
    try:
        from .old_oven import preheat
    except Exception as exc:  # noqa: BLE001
        print(f"hyped: failed to import oven: {exc}", file=sys.stderr)
        return 1
    try:
        oven = preheat(entry.repo_id, quiet=True)
    except Exception as exc:  # noqa: BLE001
        print(f"hyped: failed to load model: {exc}", file=sys.stderr)
        return 1

    chat = ChatScreen(
        oven=oven, model_entry=entry, sampling=sampling,
        color=color, ascii_only=ascii_only,
    )
    try:
        chat.run()
    finally:
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.flush()
    print(_color(90, "  goodbye.", on=color))
    return 0


__all__ = [
    "CURATED_MODELS",
    "ChatScreen",
    "Configurator",
    "ModelEntry",
    "SamplingConfig",
    "cli_main",
]

