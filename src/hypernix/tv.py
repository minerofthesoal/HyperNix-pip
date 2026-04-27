"""tv — the kitchen TV.  A btop++-style training dashboard.

Run with the ``tvtop`` console script (registered in
``pyproject.toml``)::

    tvtop                       # tail the latest run under ./trained-*
    tvtop --log path/to.log     # explicit log path
    tvtop --no-color            # ASCII-only render (CI / log files)

Or programmatically::

    from hypernix.tv import TVTop, Frame
    tv = TVTop(log_path="train.log")
    tv.run()                    # blocks until the log finishes / Ctrl-C

What it shows:

* Current training step / total / percent complete.
* Sparkline of the most recent loss values.
* Live ETA, throughput (steps/sec), wall time, peak memory (when
  the log records it).
* Hardware vitals: CPU%, RAM%, GPU memory + utilisation when
  available (``nvidia-smi`` queried at the same cadence as the
  log poll).
* Recent log tail (last N lines).

Zero hard dependencies — uses only the stdlib (``curses``-free,
plain ANSI escape codes), so it runs anywhere a terminal works.
On a non-TTY stdout (CI, redirect to file) the renderer
gracefully degrades to a one-line-per-frame text mode.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Terminal helpers (ANSI / no-curses)
# ---------------------------------------------------------------------------

CSI = "\x1b["
CLEAR_SCREEN = f"{CSI}2J{CSI}H"
CLEAR_LINE = f"{CSI}2K"
HIDE_CURSOR = f"{CSI}?25l"
SHOW_CURSOR = f"{CSI}?25h"


def _color(code: int, text: str, *, enabled: bool = True) -> str:
    if not enabled:
        return text
    return f"{CSI}{code}m{text}{CSI}0m"


def _bold(text: str, *, enabled: bool = True) -> str:
    return _color(1, text, enabled=enabled) if enabled else text


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------

#: Match log lines like ``step 100/2000 loss=2.345 lr=3e-4``.  The
#: regex is generous — the training pipeline emits ``[hypernix
#: train] step …`` and freshly-printed ``loss=…`` updates; both
#: shapes are picked up.
_STEP_RE = re.compile(
    r"step\s+(?P<step>\d+)\s*(?:/\s*(?P<total>\d+))?\s+loss\s*=\s*(?P<loss>[-\d.eE+]+)"
    r"(?:\s+lr\s*=\s*(?P<lr>[-\d.eE+]+))?"
    r"(?:\s+throughput\s*=\s*(?P<tput>[-\d.eE+]+))?",
    re.IGNORECASE,
)


@dataclass
class Frame:
    """One snapshot of training state derived from the log tail."""

    step: int = 0
    total_steps: int | None = None
    loss: float | None = None
    lr: float | None = None
    throughput: float | None = None  # steps / sec
    elapsed_seconds: float = 0.0
    eta_seconds: float | None = None
    cpu_percent: float | None = None
    ram_percent: float | None = None
    gpu_util_percent: float | None = None
    gpu_mem_used_mib: int | None = None
    gpu_mem_total_mib: int | None = None
    recent_losses: list[float] = field(default_factory=list)
    log_tail: list[str] = field(default_factory=list)

    @property
    def progress(self) -> float:
        if self.total_steps and self.total_steps > 0:
            return min(1.0, self.step / self.total_steps)
        return 0.0


# ---------------------------------------------------------------------------
# Sparkline
# ---------------------------------------------------------------------------

_SPARK_BARS: tuple[str, ...] = ("▁", "▂", "▃", "▄", "▅", "▆", "▇", "█")
_ASCII_BARS: tuple[str, ...] = (".", ":", "-", "=", "+", "*", "#", "@")


def sparkline(values: Iterable[float], *, ascii_only: bool = False) -> str:
    vs = [float(v) for v in values]
    if not vs:
        return ""
    bars = _ASCII_BARS if ascii_only else _SPARK_BARS
    lo, hi = min(vs), max(vs)
    if hi == lo:
        return bars[len(bars) // 2] * len(vs)
    out: list[str] = []
    for v in vs:
        idx = int((v - lo) / (hi - lo) * (len(bars) - 1))
        out.append(bars[idx])
    return "".join(out)


# ---------------------------------------------------------------------------
# Hardware probes (no hard deps)
# ---------------------------------------------------------------------------

def _safe_psutil_percent() -> tuple[float | None, float | None]:
    try:
        import psutil  # type: ignore
        return psutil.cpu_percent(interval=None), psutil.virtual_memory().percent
    except Exception:  # noqa: BLE001
        return None, None


def _read_proc_stat_cpu() -> float | None:
    """Lightweight /proc/stat sampler so we get a CPU % even without
    psutil.  Returns None on non-Linux."""
    try:
        with open("/proc/stat", encoding="utf-8") as fh:
            line = fh.readline()
        parts = line.split()[1:8]
        nums = [int(x) for x in parts]
        idle = nums[3]
        total = sum(nums)
        # Cheap one-shot — the "live" CPU% requires two samples.  We
        # store the previous sample on the function attribute.
        prev = getattr(_read_proc_stat_cpu, "_prev", None)
        _read_proc_stat_cpu._prev = (idle, total)  # type: ignore[attr-defined]
        if prev is None:
            return None
        d_idle = idle - prev[0]
        d_total = total - prev[1]
        if d_total <= 0:
            return None
        return max(0.0, 100.0 * (1.0 - d_idle / d_total))
    except Exception:  # noqa: BLE001
        return None


def _read_meminfo_percent() -> float | None:
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            data = {
                k.strip(): int(v.split()[0])
                for k, v in (line.split(":", 1) for line in fh if ":" in line)
            }
        total = data.get("MemTotal", 0)
        avail = data.get("MemAvailable", 0)
        if not total:
            return None
        return max(0.0, 100.0 * (1.0 - avail / total))
    except Exception:  # noqa: BLE001
        return None


def _query_nvidia_smi() -> tuple[int | None, int | None, float | None]:
    """Returns ``(mem_used_mib, mem_total_mib, util_percent)`` or
    triple None if nvidia-smi isn't available."""
    if shutil.which("nvidia-smi") is None:
        return (None, None, None)
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, check=False, timeout=2,
        )
        if out.returncode != 0:
            return (None, None, None)
        first = out.stdout.strip().splitlines()[0]
        used, total, util = (s.strip() for s in first.split(","))
        return (int(used), int(total), float(util))
    except Exception:  # noqa: BLE001
        return (None, None, None)


# ---------------------------------------------------------------------------
# Log tail reader
# ---------------------------------------------------------------------------

@dataclass
class LogTail:
    path: Path
    history_size: int = 12
    _last_size: int = field(default=0, init=False)
    _buf: deque[str] = field(default=None, init=False)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._buf = deque(maxlen=self.history_size)

    def poll(self) -> list[str]:
        """Return any new log lines since the last poll."""
        if not self.path.exists():
            return []
        new_size = self.path.stat().st_size
        if new_size < self._last_size:
            self._last_size = 0  # log was rotated / truncated
        with self.path.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(self._last_size)
            chunk = fh.read()
            self._last_size = fh.tell()
        lines = [line for line in chunk.splitlines() if line.strip()]
        for line in lines:
            self._buf.append(line)
        return lines

    @property
    def tail(self) -> list[str]:
        return list(self._buf)


# ---------------------------------------------------------------------------
# TVTop
# ---------------------------------------------------------------------------

@dataclass
class TVTop:
    log_path: Path | str | None = None
    refresh_seconds: float = 1.0
    color: bool = True
    ascii_only: bool = False
    width: int | None = None
    started_at: float = field(default_factory=time.time)
    losses: deque[float] = field(default_factory=lambda: deque(maxlen=80))
    log_tail: LogTail | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.log_path is not None:
            self.log_tail = LogTail(Path(self.log_path), history_size=12)

    # ------------------------------------------------------------------
    # Frame construction
    # ------------------------------------------------------------------

    def latest_frame(self) -> Frame:
        f = Frame()
        if self.log_tail is not None:
            self.log_tail.poll()
            for line in self.log_tail.tail:
                m = _STEP_RE.search(line)
                if m:
                    f.step = int(m.group("step"))
                    if m.group("total"):
                        f.total_steps = int(m.group("total"))
                    if m.group("loss"):
                        loss = float(m.group("loss"))
                        f.loss = loss
                        if not self.losses or self.losses[-1] != loss:
                            self.losses.append(loss)
                    if m.group("lr"):
                        f.lr = float(m.group("lr"))
                    if m.group("tput"):
                        f.throughput = float(m.group("tput"))
            f.log_tail = list(self.log_tail.tail)
        f.elapsed_seconds = time.time() - self.started_at
        if f.throughput is None and f.step > 0 and f.elapsed_seconds > 0:
            f.throughput = f.step / f.elapsed_seconds
        if f.total_steps and f.throughput and f.throughput > 0:
            f.eta_seconds = max(0.0, (f.total_steps - f.step) / f.throughput)
        # Hardware
        cpu, ram = _safe_psutil_percent()
        if cpu is None:
            cpu = _read_proc_stat_cpu()
        if ram is None:
            ram = _read_meminfo_percent()
        f.cpu_percent = cpu
        f.ram_percent = ram
        used, total, util = _query_nvidia_smi()
        f.gpu_mem_used_mib = used
        f.gpu_mem_total_mib = total
        f.gpu_util_percent = util
        f.recent_losses = list(self.losses)
        return f

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _term_width(self) -> int:
        if self.width is not None:
            return self.width
        try:
            return shutil.get_terminal_size((80, 24)).columns
        except Exception:  # noqa: BLE001
            return 80

    def _bar(self, frac: float, width: int) -> str:
        filled = int(round(frac * width))
        empty = width - filled
        ch_full = "█" if not self.ascii_only else "#"
        ch_empty = "░" if not self.ascii_only else "."
        return ch_full * filled + ch_empty * empty

    def render(self, f: Frame) -> str:
        w = self._term_width()
        c = self.color and not self.ascii_only
        lines: list[str] = []
        title = "  📺  hypernix tvtop  —  training dashboard "
        bar_w = max(20, w - 32)
        lines.append(_bold(title.ljust(w), enabled=c))
        lines.append("─" * w)

        # Progress bar
        pct = f.progress * 100.0
        prog_bar = self._bar(f.progress, bar_w)
        head = f"  step  {f.step:>7}"
        if f.total_steps:
            head += f" / {f.total_steps:<7}"
        head += f"  [{prog_bar}] {pct:5.1f}%"
        lines.append(_color(36, head, enabled=c))

        # Loss + sparkline
        loss_str = f"loss={f.loss:.4f}" if f.loss is not None else "loss=—"
        lr_str = f"lr={f.lr:.2e}" if f.lr is not None else "lr=—"
        tput_str = f"tput={f.throughput:.2f} step/s" if f.throughput else "tput=—"
        spark = sparkline(f.recent_losses, ascii_only=self.ascii_only) or "—"
        lines.append(
            _color(33, f"  {loss_str:<14}{lr_str:<14}{tput_str:<24}", enabled=c)
            + f"loss-curve [{spark}]",
        )

        # Time + ETA
        elapsed = _fmt_duration(f.elapsed_seconds)
        eta = _fmt_duration(f.eta_seconds) if f.eta_seconds is not None else "—"
        lines.append(_color(35, f"  elapsed={elapsed:<10}  ETA={eta}", enabled=c))

        # Hardware
        cpu = f"{f.cpu_percent:5.1f}%" if f.cpu_percent is not None else "  —  "
        ram = f"{f.ram_percent:5.1f}%" if f.ram_percent is not None else "  —  "
        gpu_util = f"{f.gpu_util_percent:5.1f}%" if f.gpu_util_percent is not None else "  —  "
        gpu_mem = (
            f"{f.gpu_mem_used_mib:>5}/{f.gpu_mem_total_mib:<5} MiB"
            if f.gpu_mem_used_mib is not None and f.gpu_mem_total_mib else "—"
        )
        lines.append(
            _color(32, f"  CPU {cpu}   RAM {ram}   GPU {gpu_util}   VRAM {gpu_mem}", enabled=c),
        )

        # Recent log lines
        lines.append("─" * w)
        lines.append(_bold("  recent log:", enabled=c))
        for line in (f.log_tail or [])[-8:]:
            lines.append("    " + line[: w - 4])

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    def is_tty(self) -> bool:
        return bool(getattr(sys.stdout, "isatty", lambda: False)())

    def run(self, *, max_frames: int | None = None) -> None:
        """Block and refresh until Ctrl-C, the log stops growing for
        ``stop_after_idle_seconds``, or ``max_frames`` is reached.

        Exits cleanly on ``KeyboardInterrupt`` and always restores the
        cursor.
        """
        tty = self.is_tty()
        try:
            if tty:
                sys.stdout.write(HIDE_CURSOR + CLEAR_SCREEN)
                sys.stdout.flush()
            n = 0
            while True:
                frame = self.latest_frame()
                if tty:
                    sys.stdout.write(CLEAR_SCREEN + self.render(frame))
                else:
                    sys.stdout.write(self.render_one_line(frame) + "\n")
                sys.stdout.flush()
                n += 1
                if max_frames is not None and n >= max_frames:
                    return
                time.sleep(self.refresh_seconds)
        except KeyboardInterrupt:
            return
        finally:
            if tty:
                sys.stdout.write(SHOW_CURSOR + "\n")
                sys.stdout.flush()

    def render_one_line(self, f: Frame) -> str:
        return (
            f"step={f.step}/{f.total_steps or '-'}  loss="
            f"{f.loss if f.loss is not None else '-'}"
            f"  tput={f.throughput if f.throughput else '-'}  "
            f"eta={_fmt_duration(f.eta_seconds) if f.eta_seconds else '-'}"
        )


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


# ---------------------------------------------------------------------------
# Auto-detect a recent training log when no path is given
# ---------------------------------------------------------------------------

def _autodetect_log(start: Path = Path(".")) -> Path | None:
    candidates: list[tuple[float, Path]] = []
    for p in start.glob("**/train*.log"):
        try:
            candidates.append((p.stat().st_mtime, p))
        except OSError:
            continue
    for p in start.glob("**/*.log"):
        try:
            candidates.append((p.stat().st_mtime, p))
        except OSError:
            continue
    if not candidates:
        return None
    return max(candidates)[1]


# ---------------------------------------------------------------------------
# CLI entry point — installed as ``tvtop``
# ---------------------------------------------------------------------------

def cli_main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    log: Path | None = None
    color = True
    ascii_only = False
    refresh = 1.0
    if "--no-color" in args:
        color = False
        args.remove("--no-color")
    if "--ascii" in args:
        ascii_only = True
        args.remove("--ascii")
    if "--refresh" in args:
        i = args.index("--refresh")
        if i + 1 < len(args):
            refresh = float(args[i + 1])
            del args[i : i + 2]
    if "--log" in args:
        i = args.index("--log")
        if i + 1 < len(args):
            log = Path(args[i + 1])
            del args[i : i + 2]
    if "--help" in args or "-h" in args:
        print(
            "usage: tvtop [--log path] [--no-color] [--ascii] "
            "[--refresh SECONDS]\n"
            "Defaults: auto-detect newest *.log under cwd, refresh once "
            "per second, ANSI colour on a TTY.",
        )
        return 0
    if log is None:
        log = _autodetect_log()
    if log is None:
        print(
            "tvtop: no training log found.  Pass --log <path> or run "
            "from a directory containing *.log.",
            file=sys.stderr,
        )
        return 2
    print(f"[tvtop] tailing {log}")
    TVTop(log_path=log, color=color, ascii_only=ascii_only, refresh_seconds=refresh).run()
    return 0


__all__ = [
    "Frame",
    "LogTail",
    "TVTop",
    "cli_main",
    "sparkline",
]
