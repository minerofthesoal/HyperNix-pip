"""tvtop++ — The ultimate live training dashboard (btop++ style).

A premium, highly-styled console training monitor with a box layout, custom
spinners, process list, CPU/RAM/GPU block histories, and asymptotic loss curve extrapolation.

Run with:
    tvtop++
    tvtop++ --log train.log
"""
from __future__ import annotations

import re
import shutil
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .tv import (
    CLEAR_LINE,
    CLEAR_SCREEN,
    CSI,
    CURSOR_HOME,
    HIDE_CURSOR,
    SHOW_CURSOR,
    Frame,
    LogTail,
    _autodetect_log,
    _bar_str,
    _block_history_bar,
    _bold,
    _color,
    _fmt_duration,
    _gauge_line,
    _query_nvidia_smi_full,
    _read_memory_breakdown,
    _read_proc_stat_cpu,
    _read_proc_stat_per_core,
    _safe_psutil_per_core,
    _safe_psutil_percent,
    multi_row_graph,
)

# Premium spinner characters for micro-animations
SPINNERS = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _box_chars(double: bool = False) -> dict[str, str]:
    if double:
        return {
            "tl": "╔", "tr": "╗", "bl": "╚", "br": "╝",
            "h": "═", "v": "║",
        }
    return {
        "tl": "╭", "tr": "╮", "bl": "╰", "br": "╯",
        "h": "─", "v": "│",
    }


def _strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", s)


def _visible_len(s: str) -> int:
    return len(_strip_ansi(s))


def _pad(s: str, width: int) -> str:
    vis = _visible_len(s)
    if vis == width:
        return s
    if vis < width:
        return s + " " * (width - vis)
    plain = _strip_ansi(s)
    return plain[: max(0, width - 1)] + ("…" if width > 0 else "")


def _frame_panel(
    title: str,
    body: list[str],
    *,
    width: int,
    ascii_only: bool,
    color_enabled: bool,
    title_color: int = 36,
    double_border: bool = False,
) -> list[str]:
    """Frame contents with double or rounded box-drawing characters."""
    if ascii_only:
        ch = {"tl": "+", "tr": "+", "bl": "+", "br": "+", "h": "-", "v": "|"}
    else:
        ch = _box_chars(double=double_border)
        
    inner_w = max(1, width - 2)
    title_text = f" {title} "
    title_render = _color(title_color, _bold(title_text, enabled=color_enabled), enabled=color_enabled)
    title_vis = len(title_text)
    fill_after = max(0, inner_w - 2 - title_vis)
    
    top = ch["tl"] + ch["h"] + title_render + ch["h"] * fill_after + ch["tr"]
    bot = ch["bl"] + ch["h"] * inner_w + ch["br"]
    
    rows = [top]
    for ln in body:
        rows.append(ch["v"] + _pad(ln, inner_w) + ch["v"])
    rows.append(bot)
    return rows


def _hcat(left: list[str], right: list[str], *, gap: int = 1) -> list[str]:
    n = max(len(left), len(right))
    while len(left) < n:
        left.append("")
    while len(right) < n:
        right.append("")
    return [a + " " * gap + b for a, b in zip(left, right, strict=False)]


def _get_active_processes() -> list[dict[str, Any]]:
    """Fetch active hypernix or python training processes."""
    processes = []
    try:
        import psutil
        for proc in psutil.process_iter(['pid', 'username', 'cpu_percent', 'memory_percent', 'cmdline']):
            try:
                cmdline = ' '.join(proc.info['cmdline'] or []) if proc.info['cmdline'] else ''
                cmd_lower = cmdline.lower()
                if 'hypernix' in cmd_lower or 'python' in cmd_lower or 'train' in cmd_lower:
                    # Filter out helper scripts like lsof or self if desired, but keep training
                    if 'tvtop' in cmd_lower or 'psutil' in cmd_lower:
                        continue
                    processes.append({
                        'pid': proc.info['pid'],
                        'user': proc.info['username'] or 'unknown',
                        'cpu': round(proc.info['cpu_percent'] or 0.0, 1),
                        'mem': round(proc.info['memory_percent'] or 0.0, 1),
                        'cmd': cmdline[:50]
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    # Sort by CPU usage desc
    return sorted(processes, key=lambda p: p['cpu'], reverse=True)[:5]


@dataclass
class TVTopPlusPlus:
    log_path: Path | str | None = None
    refresh_seconds: float = 1.0
    color: bool = True
    ascii_only: bool = False
    width: int | None = None
    small_mode: bool = False
    started_at: float = field(default_factory=time.time)
    log_tail: LogTail | None = field(default=None, init=False)
    _prev_render: str = field(default="", init=False, repr=False)
    tick: int = field(default=0, init=False)
    
    # Histories
    _cpu_history: deque[float] = field(default_factory=lambda: deque(maxlen=120), init=False, repr=False)
    _ram_history: deque[float] = field(default_factory=lambda: deque(maxlen=120), init=False, repr=False)
    _gpu_util_history: deque[float] = field(default_factory=lambda: deque(maxlen=120), init=False, repr=False)

    def __post_init__(self) -> None:
        if self.log_path is not None:
            self.log_tail = LogTail(Path(self.log_path), history_size=8)

    def latest_frame(self) -> Frame:
        f = Frame()
        if self.log_tail is not None:
            self.log_tail.poll()
            if self.log_tail.has_training_data:
                f.has_training_data = True
                f.step = self.log_tail.step or 0
                f.total_steps = self.log_tail.total_steps
                f.loss = self.log_tail.loss
                f.lr = self.log_tail.lr
                f.throughput = self.log_tail.throughput
            elif self.log_tail.latest_match is not None:
                m = self.log_tail.latest_match
                f.has_training_data = True
                f.step = int(m.group("step"))
                if m.group("total"):
                    f.total_steps = int(m.group("total"))
                if m.group("loss"):
                    f.loss = float(m.group("loss"))
                if m.group("lr"):
                    f.lr = float(m.group("lr"))
                if m.group("tput"):
                    f.throughput = float(m.group("tput"))
            f.recent_losses = list(self.log_tail.losses)
            f.log_tail = list(self.log_tail.tail)
        f.elapsed_seconds = time.time() - self.started_at
        if f.has_training_data and f.throughput is None and f.step > 0 and f.elapsed_seconds > 0:
            f.throughput = f.step / f.elapsed_seconds
        if f.has_training_data and f.total_steps and f.throughput and f.throughput > 0:
            f.eta_seconds = max(0.0, (f.total_steps - f.step) / f.throughput)
            
        # CPU
        cpu, ram = _safe_psutil_percent()
        if cpu is None:
            cpu = _read_proc_stat_cpu()
        per_core = _safe_psutil_per_core() or _read_proc_stat_per_core() or []
        f.cpu_per_core = list(per_core)
        
        # Memory
        mem = _read_memory_breakdown() or {}
        f.memory = mem
        if ram is None and mem.get("percent") is not None:
            ram = float(mem["percent"])
        f.cpu_percent = cpu
        f.ram_percent = ram
        
        # GPU
        gpu = _query_nvidia_smi_full()
        f.gpu_mem_used_mib = gpu["mem_used_mib"]
        f.gpu_mem_total_mib = gpu["mem_total_mib"]
        f.gpu_util_percent = gpu["util_percent"]
        f.gpu_temp_c = gpu["temp_c"]
        f.gpu_power_w = gpu["power_w"]
        f.gpu_power_limit_w = gpu["power_limit_w"]
        f.gpu_name = gpu["name"]
        
        # History buffers
        if cpu is not None:
            self._cpu_history.append(cpu)
        if ram is not None:
            self._ram_history.append(ram)
        if gpu["util_percent"] is not None:
            self._gpu_util_history.append(gpu["util_percent"])
            
        f.cpu_history = list(self._cpu_history)
        f.ram_history = list(self._ram_history)
        f.gpu_util_history = list(self._gpu_util_history)
        return f

    def render(self, f: Frame) -> str:
        self.tick += 1
        w = max(72, self.width or self._term_width())
        c = self.color and not self.ascii_only
        aa = self.ascii_only
        
        # Header banner (btop++ style)
        spinner_char = SPINNERS[self.tick % len(SPINNERS)] if not aa else "*"
        spinner_colored = _color(96, spinner_char, enabled=c)
        title_str = _bold(" ✦ HYPERNIX TVTOP++ ✦ ", enabled=c)
        title_rendered = _color(94, title_str, enabled=c)
        time_str = time.strftime(" %Y-%m-%d %H:%M:%S ")
        header_text = f" {spinner_colored} {title_rendered} {CSI}90m{time_str}{CSI}0m"
        banner_w = _visible_len(header_text)
        header_line = header_text + " " * max(0, w - banner_w)
        
        # Main top row columns: Training (Left) & Hardware Vitals (Right)
        left_w = max(36, int(w * 0.48))
        right_w = w - left_w - 1
        if right_w < 34:
            right_w = 34
            left_w = max(36, w - right_w - 1)
            
        training_panel = self._build_training_panel(f, left_w, aa, c)
        hardware_panel = self._build_hardware_panel(f, right_w, aa, c)
        top_row = _hcat(training_panel, hardware_panel, gap=1)
        
        # Middle row: Process Monitor (Left) & GPU Details (Right)
        process_panel = self._build_process_panel(left_w, aa, c)
        gpu_panel = self._build_gpu_panel(f, right_w, aa, c)
        middle_row = _hcat(process_panel, gpu_panel, gap=1)
        
        # Bottom Loss Curve
        loss_panel = self._build_loss_panel(f, w, aa, c)
        
        # Log Tail panel
        log_panel = self._build_log_panel(f, w, aa, c)
        
        # Footer
        footer = _color(
            90,
            f" ⎋ Ctrl-C to exit · refresh {self.refresh_seconds:.1f}s · "
            f"width={w} · cores={len(f.cpu_per_core)} · log={self.log_path or 'auto'}",
            enabled=c,
        )
        
        if self.small_mode:
            # Stack layout for small terminals
            return "\n".join([header_line, *training_panel, *hardware_panel, *log_panel, footer])
            
        return "\n".join([header_line, *top_row, *middle_row, *loss_panel, *log_panel, footer])

    def _build_training_panel(self, f: Frame, width: int, aa: bool, c: bool) -> list[str]:
        inner = max(10, width - 2)
        body: list[str] = []
        if f.has_training_data:
            # Step and Progress bar
            prog_w = max(6, inner - 26)
            pct = f.progress * 100.0
            step_text = f"Step {f.step:>6}"
            if f.total_steps:
                step_text += f"/{f.total_steps}"
            pbar = _bar_str(f.progress, prog_w, ascii_only=aa, color_enabled=c)
            body.append(_color(36, f"{step_text:<16} {pbar} {pct:>5.1f}%", enabled=c))
            body.append("")
            
            # Metrics
            loss_val = f"{f.loss:.4f}" if f.loss is not None else "—"
            lr_val = f"{f.lr:.2e}" if f.lr is not None else "—"
            tput_val = f"{f.throughput:.2f}/s" if f.throughput is not None else "—"
            body.append(f" Loss       {_color(33, loss_val, enabled=c)}")
            body.append(f" LearnRate  {_color(32, lr_val, enabled=c)}")
            body.append(f" Speed      {_color(35, tput_val, enabled=c)}")
            
            # Duration and ETA
            elapsed = _fmt_duration(f.elapsed_seconds)
            eta = _fmt_duration(f.eta_seconds) if f.eta_seconds is not None else "—"
            body.append(f" Time       {elapsed:<9}  ETA: {eta}")
        else:
            body.append(_color(33, " ⏳ Waiting for training log data...", enabled=c))
            body.append("")
            body.append(f" File: {self.log_path or 'not specified'}")
            body.append(" Ensure your training scripts output logs containing")
            body.append(" steps, loss=, and throughput values.")
            while len(body) < 7:
                body.append("")
        return _frame_panel("Training Vitals", body, width=width, ascii_only=aa, color_enabled=c, title_color=36, double_border=True)

    def _build_hardware_panel(self, f: Frame, width: int, aa: bool, c: bool) -> list[str]:
        inner = max(10, width - 2)
        body: list[str] = []
        bar_w = max(6, inner - 18)
        
        # Gauges
        body.append(_gauge_line("CPU", f.cpu_percent, bar_w, ascii_only=aa, color_enabled=c))
        body.append(_gauge_line("RAM", f.ram_percent, bar_w, ascii_only=aa, color_enabled=c))
        
        # GPU gauge
        gpu_pct = f.gpu_util_percent
        body.append(_gauge_line("GPU", gpu_pct, bar_w, ascii_only=aa, color_enabled=c))
        body.append("")
        
        # Block style history
        if f.cpu_history:
            cpu_hist = _block_history_bar(f.cpu_history, max(1, inner - 12), c)
            body.append(f"CPU History [{cpu_hist}]")
        if f.ram_history:
            ram_hist = _block_history_bar(f.ram_history, max(1, inner - 12), c)
            body.append(f"RAM History [{ram_hist}]")
        if f.gpu_util_history:
            gpu_hist = _block_history_bar(f.gpu_util_history, max(1, inner - 12), c)
            body.append(f"GPU History [{gpu_hist}]")
            
        while len(body) < 7:
            body.append("")
        return _frame_panel("Hardware Vitals", body, width=width, ascii_only=aa, color_enabled=c, title_color=32)

    def _build_process_panel(self, width: int, aa: bool, c: bool) -> list[str]:
        inner = max(10, width - 2)
        body: list[str] = []
        body.append(f"{'PID':<6} {'USER':<8} {'CPU%':<6} {'MEM%':<6} {'COMMAND':<18}")
        
        procs = _get_active_processes()
        if procs:
            for p in procs:
                body.append(
                    f"{p['pid']:<6} {p['user'][:8]:<8} {p['cpu']:>5.1f}% {p['mem']:>5.1f}% {p['cmd'][:inner-30]:<18}"
                )
        else:
            body.append("(no active python/training processes)")
            
        while len(body) < 6:
            body.append("")
        return _frame_panel("Process Monitor", body, width=width, ascii_only=aa, color_enabled=c, title_color=34)

    def _build_gpu_panel(self, f: Frame, width: int, aa: bool, c: bool) -> list[str]:
        inner = max(10, width - 2)
        body: list[str] = []
        if f.gpu_util_percent is None and f.gpu_mem_total_mib is None:
            body.append("(no GPU detected or nvidia-smi missing)")
            while len(body) < 6:
                body.append("")
            return _frame_panel("GPU Details", body, width=width, ascii_only=aa, color_enabled=c, title_color=35)
            
        if f.gpu_name:
            body.append(_color(96, f.gpu_name[:inner], enabled=c))
        
        # VRAM breakdown
        if f.gpu_mem_used_mib is not None and f.gpu_mem_total_mib:
            mem_pct = 100.0 * f.gpu_mem_used_mib / f.gpu_mem_total_mib
            bar = _bar_str(mem_pct / 100.0, max(6, inner - 24), ascii_only=aa, color_enabled=c)
            body.append(f"VRAM  {bar} {f.gpu_mem_used_mib:>5}/{f.gpu_mem_total_mib:<5} MiB")
            
        if f.gpu_temp_c is not None:
            temp_norm = max(0.0, min(1.0, (f.gpu_temp_c - 30) / 70.0))
            bar = _bar_str(temp_norm, max(6, inner - 24), ascii_only=aa, color_enabled=c)
            body.append(f"Temp  {bar} {f.gpu_temp_c:>5.1f}°C")
            
        if f.gpu_power_w is not None and f.gpu_power_limit_w:
            pwr_pct = 100.0 * f.gpu_power_w / f.gpu_power_limit_w
            bar = _bar_str(pwr_pct / 100.0, max(6, inner - 24), ascii_only=aa, color_enabled=c)
            body.append(f"Power {bar} {f.gpu_power_w:>5.1f}/{f.gpu_power_limit_w:<5.0f} W")
            
        while len(body) < 6:
            body.append("")
        return _frame_panel("GPU Details", body, width=width, ascii_only=aa, color_enabled=c, title_color=35)

    def _build_loss_panel(self, f: Frame, width: int, aa: bool, c: bool) -> list[str]:
        inner = max(10, width - 2)
        loss_title = "Loss Curve"
        
        if f.recent_losses:
            # Exponential decay dampening projection
            if len(f.recent_losses) >= 5:
                recent_ma = sum(f.recent_losses[-3:]) / 3.0
                prev_ma = sum(f.recent_losses[-6:-3]) / 3.0 if len(f.recent_losses) >= 6 else f.recent_losses[0]
                slope = (recent_ma - prev_ma) / 3.0
                
                future_losses = []
                cur = f.recent_losses[-1]
                temp_slope = slope
                for _ in range(15):
                    cur += temp_slope
                    cur = max(0.0, cur)
                    future_losses.append(cur)
                    temp_slope *= 0.85 # exponential decay dampening
                    
                combined = f.recent_losses + future_losses
                est_val = future_losses[-1]
                loss_title = (
                    f"Loss Curve (min: {min(f.recent_losses):.4f} · max: {max(f.recent_losses):.4f} · "
                    f"current: {f.loss:.4f} · est: {est_val:.4f})"
                )
            else:
                combined = f.recent_losses
                curr_val = f.loss if f.loss is not None else f.recent_losses[-1]
                loss_title = f"Loss Curve (min: {min(f.recent_losses):.4f} · max: {max(f.recent_losses):.4f} · current: {curr_val:.4f})"
                
            graph_rows = multi_row_graph(combined, width=inner, height=5, ascii_only=aa)
            if c:
                colored_rows = []
                for r in graph_rows:
                    if len(combined) > 15:
                        pred_chars = int((15 / len(combined)) * inner)
                        real_chars = max(0, inner - pred_chars)
                        real_str = r[:real_chars]
                        pred_str = r[real_chars:]
                        colored_rows.append(_color(36, real_str, enabled=c) + _color(35, pred_str, enabled=c))
                    else:
                        colored_rows.append(_color(36, r, enabled=c))
                graph_rows = colored_rows
        else:
            graph_rows = ["(no loss values yet — tailing train.log...)"]
            graph_rows += [""] * 4
            
        return _frame_panel(loss_title, graph_rows, width=width, ascii_only=aa, color_enabled=c, title_color=33)

    def _build_log_panel(self, f: Frame, width: int, aa: bool, c: bool) -> list[str]:
        inner = max(10, width - 2)
        log_lines = (f.log_tail or [])[-6:]
        body = [raw[:inner] for raw in log_lines]
        while len(body) < 6:
            body.append("")
        return _frame_panel("Recent Log Tail", body, width=width, ascii_only=aa, color_enabled=c, title_color=37)

    def _term_width(self) -> int:
        try:
            cols = shutil.get_terminal_size((100, 24)).columns
            # Cap width to prevent excessive rendering in CI/remote environments
            # that report bogus terminal sizes
            return min(cols, 200)
        except Exception:
            return 100

    def run(self, *, max_frames: int | None = None) -> None:
        tty = bool(getattr(sys.stdout, "isatty", lambda: False)())
        try:
            if tty:
                sys.stdout.write(HIDE_CURSOR + CLEAR_SCREEN)
                sys.stdout.flush()
            n = 0
            while True:
                frame = self.latest_frame()
                if tty:
                    body = self.render(frame)
                    if body != self._prev_render:
                        out = CURSOR_HOME
                        for line in body.splitlines():
                            out += line + CLEAR_LINE + "\n"
                        prev_count = len(self._prev_render.splitlines())
                        cur_count = len(body.splitlines())
                        for _ in range(max(0, prev_count - cur_count)):
                            out += CLEAR_LINE + "\n"
                        sys.stdout.write(out)
                        sys.stdout.flush()
                        self._prev_render = body
                else:
                    # Degradation for pipe/CI
                    if frame.has_training_data:
                        sys.stdout.write(
                            f"step={frame.step}/{frame.total_steps or '-'} "
                            f"loss={frame.loss if frame.loss is not None else '-'} "
                            f"lr={frame.lr if frame.lr is not None else '-'} "
                            f"tput={frame.throughput if frame.throughput else '-'}\n"
                        )
                    else:
                        sys.stdout.write("waiting for training data...\n")
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


def cli_main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    log: Path | None = None
    color = True
    ascii_only = False
    refresh = 1.0
    small_mode = False
    
    if "--no-color" in args:
        color = False
        args.remove("--no-color")
    if "--ascii" in args:
        ascii_only = True
        args.remove("--ascii")
    if "-s" in args or "--small" in args:
        small_mode = True
        args = [a for a in args if a not in ("-s", "--small")]
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
            "usage: tvtop++ [--log path] [--no-color] [--ascii] "
            "[--refresh SECONDS] [-s|--small]\n"
            "An advanced btop++ styled training dashboard with moving spinner,\n"
            "process list, block history and improved decay curve estimations.\n"
            "  -s, --small   compact mode for smaller terminals\n"
            "\n"
            "If no --log is specified, tvtop++ will search for *.log files in the\n"
            "current directory. If none are found, it will display a blank dashboard\n"
            "waiting for training data.",
        )
        return 0
        
    if log is None:
        log = _autodetect_log()
    
    # Don't exit if no log found - just show blank dashboard waiting for data
    if log is not None:
        print(f"[tvtop++] Tailing {log}...", file=sys.stderr)
    else:
        print("[tvtop++] No log file specified - displaying live system metrics only", file=sys.stderr)
    TVTopPlusPlus(
        log_path=log,
        color=color,
        ascii_only=ascii_only,
        refresh_seconds=refresh,
        small_mode=small_mode,
    ).run()
    return 0


__all__ = [
    "TVTopPlusPlus",
    "cli_main",
]
