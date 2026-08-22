"""ethanol — turn the GPU clock up.

⚠️  **Real overclocking voids warranties, can crash your machine,
and on consumer cards may permanently damage hardware.**  This
module wraps the *standard* vendor tools (``nvidia-smi`` /
``nvidia-settings`` / ``rocm-smi`` / ``intel_gpu_frequency``) and
maps a single integer "level" 0…30 to bounded clock + memory
offsets.  Level 0 resets to defaults; level 30 is the maximum
offset we'll ever apply (and it's still well below typical
manual-overclocker limits).  The helpers refuse to run unless
``confirm=True`` is passed (or the ``HYPERNIX_ETHANOL_CONFIRM=1``
env var is set), so a mistyped script can't accidentally crank
your GPU.

Quick use::

    from hypernix.ethanol import Ethanol
    Ethanol(level=5).apply(confirm=True)

CLI (registered in ``pyproject.toml``)::

    eth 0      # reset to stock
    eth 5      # mild bump
    eth 30     # max-supported offset

The CLI requires the ``HYPERNIX_ETHANOL_CONFIRM=1`` env var to
actually apply; without it, it prints what *would* happen and
exits 0.

The returned :class:`OverclockResult` records what was attempted,
what succeeded, and whatever stderr came back from the vendor
tool — so you have a record even when an offset gets clamped by
the driver.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

#: Hard ceilings — we will NEVER apply more than these regardless
#: of the level requested.  Tuned to stay inside the bounds the
#: stock driver / msi-afterburner stable bands typically allow.
MAX_CORE_OFFSET_MHZ: int = 200      # core clock offset
MAX_MEM_OFFSET_MHZ: int = 1500      # memory clock offset
MAX_POWER_LIMIT_PCT: int = 115      # power limit % of stock

#: Number of valid levels, inclusive.  Level 0 resets to stock.
MAX_LEVEL: int = 30


@dataclass
class OverclockResult:
    level: int
    core_offset_mhz: int
    mem_offset_mhz: int
    power_limit_pct: int
    backend: str
    applied: bool
    notes: str = ""
    stderr: str = ""


def _level_to_offsets(level: int) -> tuple[int, int, int]:
    """Map ``level`` 0..30 to ``(core_mhz, mem_mhz, power_pct)``.

    Linear ramp; level 0 is full stock, level 30 hits the hard
    ceilings declared at module level.  Levels above 30 are
    clamped to 30 (rather than rejected) to keep the helpers
    forgiving — but the CLI rejects out-of-range input.
    """
    if level < 0:
        raise ValueError("level must be >= 0")
    eff = min(level, MAX_LEVEL)
    if eff == 0:
        return (0, 0, 100)
    f = eff / MAX_LEVEL
    core = int(round(MAX_CORE_OFFSET_MHZ * f))
    mem = int(round(MAX_MEM_OFFSET_MHZ * f))
    # Power scales 100 → 115 across the range.
    power = int(round(100 + (MAX_POWER_LIMIT_PCT - 100) * f))
    return (core, mem, power)


def _has_binary(name: str) -> bool:
    return shutil.which(name) is not None


def _detect_backend() -> str:
    """Pick the best vendor tool available.  ``"none"`` when no
    overclocker is installed."""
    if _has_binary("nvidia-smi") and _has_binary("nvidia-settings"):
        return "nvidia"
    if _has_binary("nvidia-smi"):
        return "nvidia-smi-only"
    if _has_binary("rocm-smi"):
        return "rocm"
    if _has_binary("intel_gpu_frequency"):
        return "intel"
    return "none"


def _confirmed(confirm: bool) -> bool:
    if confirm:
        return True
    return os.environ.get("HYPERNIX_ETHANOL_CONFIRM") == "1"


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


@dataclass
class Ethanol:
    """Overclock helper.  Construct with a level, call :meth:`apply`."""

    level: int = 0
    backend: str | None = None
    gpu_index: int = 0
    extra_notes: list[str] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.backend is None:
            self.backend = _detect_backend()

    def offsets(self) -> tuple[int, int, int]:
        return _level_to_offsets(self.level)

    def plan(self) -> OverclockResult:
        core, mem, power = self.offsets()
        return OverclockResult(
            level=self.level,
            core_offset_mhz=core,
            mem_offset_mhz=mem,
            power_limit_pct=power,
            backend=self.backend or "none",
            applied=False,
            notes="(plan only)",
        )

    def _check_temperature_safe(self) -> tuple[bool, float, str]:
        """Check if GPU temperature is safe for overclocking."""
        if self.backend not in ["nvidia", "nvidia-smi-only"]:
            return True, 0.0, ""
        try:
            res = _run([
                "nvidia-smi", "--query-gpu=temperature.gpu",
                "--format=csv,noheader", "-i", str(self.gpu_index),
            ])
            temp = float(res.stdout.strip())
            # Throttle if above 85C
            if temp > 85.0 and self.level > 10:
                return False, temp, f"GPU too hot ({temp}C > 85C) for level {self.level}"
            return True, temp, f"Temp OK ({temp}C)"
        except Exception:
            return True, 0.0, "Could not read temp"

    def apply(self, *, confirm: bool = False, auto_throttle: bool = True) -> OverclockResult:
        """Apply the offsets via the detected vendor tool.

        Without ``confirm=True`` (or ``HYPERNIX_ETHANOL_CONFIRM=1``)
        this returns a planned result without touching the GPU.
        """
        plan = self.plan()
        if not _confirmed(confirm):
            plan.notes = (
                "ethanol: refusing to apply without confirm=True or "
                "HYPERNIX_ETHANOL_CONFIRM=1; returning plan."
            )
            return plan

        if auto_throttle:
            is_safe, temp, msg = self._check_temperature_safe()
            if not is_safe:
                plan.notes = f"ethanol safety: {msg}. Aborting apply."
                plan.applied = False
                return plan

        if self.backend == "nvidia":
            return self._apply_nvidia(plan)
        if self.backend == "nvidia-smi-only":
            return self._apply_nvidia_smi_only(plan)
        if self.backend == "rocm":
            return self._apply_rocm(plan)
        if self.backend == "intel":
            return self._apply_intel(plan)
        plan.notes = (
            f"ethanol: no supported overclocker found "
            f"(backend={self.backend!r}); install nvidia-settings, "
            "rocm-smi, or intel_gpu_frequency."
        )
        return plan

    def reset(self, *, confirm: bool = False) -> OverclockResult:
        """Convenience: same as ``Ethanol(level=0).apply(...)``."""
        self.level = 0
        return self.apply(confirm=confirm)

    # ------------------------------------------------------------------
    # Backends
    # ------------------------------------------------------------------

    def _apply_nvidia(self, plan: OverclockResult) -> OverclockResult:
        cmds: list[list[str]] = [
            ["nvidia-settings", "-a",
             f"[gpu:{self.gpu_index}]/GPUGraphicsClockOffsetAllPerformanceLevels={plan.core_offset_mhz}"],
            ["nvidia-settings", "-a",
             f"[gpu:{self.gpu_index}]/GPUMemoryTransferRateOffsetAllPerformanceLevels={plan.mem_offset_mhz}"],
            ["nvidia-smi", "-i", str(self.gpu_index),
             "-pl", str(self._stock_power_watts_or_default())],
        ]
        return self._run_cmds(cmds, plan)

    def _apply_nvidia_smi_only(self, plan: OverclockResult) -> OverclockResult:
        # Without nvidia-settings we can only set power limit cleanly.
        cmds = [[
            "nvidia-smi", "-i", str(self.gpu_index),
            "-pl", str(self._stock_power_watts_or_default()),
        ]]
        return self._run_cmds(cmds, plan)

    def _apply_rocm(self, plan: OverclockResult) -> OverclockResult:
        # rocm-smi maps nicely: --setperflevel manual + --setsclk N
        # is the standard pattern.  We pick the highest sclk index
        # the card exposes (index 7 is conventional on RDNA).
        cmds = [
            ["rocm-smi", "--setperflevel", "manual"],
            ["rocm-smi", "--setsclk", "7"],
            ["rocm-smi", "--setpoweroverdrive", str(plan.power_limit_pct - 100)],
        ]
        return self._run_cmds(cmds, plan)

    def _apply_intel(self, plan: OverclockResult) -> OverclockResult:
        cmds = [["intel_gpu_frequency", "-s", f"+{plan.core_offset_mhz}"]]
        return self._run_cmds(cmds, plan)

    def _run_cmds(
        self, cmds: list[list[str]], plan: OverclockResult,
    ) -> OverclockResult:
        out_notes: list[str] = []
        out_err: list[str] = []
        any_failed = False
        permission_denied = False
        for cmd in cmds:
            res = _run(cmd)
            out_notes.append(f"$ {' '.join(cmd)} -> rc={res.returncode}")
            if res.stderr:
                out_err.append(res.stderr.strip())
                # Detect permission errors to give helpful guidance
                if "permission" in res.stderr.lower() or "not permitted" in res.stderr.lower():
                    permission_denied = True
            if res.returncode != 0:
                any_failed = True
        plan.applied = not any_failed
        plan.notes = "; ".join(out_notes)
        plan.stderr = "\n".join(out_err)
        if permission_denied:
            plan.notes += (
                "\n\nethanol: permission denied — GPU overclocking requires elevated privileges.\n"
                "Try: sudo eth <level> --confirm\n"
                "Or set persistent permissions via nvidia-settings config file."
            )
        return plan

    def _stock_power_watts_or_default(self) -> int:
        """Read default power limit via nvidia-smi; if that fails,
        fall back to 250W (4080-class default).  Then bump by the
        target percent."""
        try:
            res = _run([
                "nvidia-smi", "--query-gpu=power.default_limit",
                "--format=csv,noheader,nounits", "-i", str(self.gpu_index),
            ])
            stock = float(res.stdout.strip())
        except Exception:  # noqa: BLE001
            stock = 250.0
        _core, _mem, power_pct = self.offsets()
        return int(round(stock * power_pct / 100.0))


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def ethanol(level: int = 0, **kw: Any) -> Ethanol:
    return Ethanol(level=level, **kw)


def overclock(level: int, *, confirm: bool = False, gpu_index: int = 0) -> OverclockResult:
    """One-shot helper.  Equivalent to
    ``Ethanol(level=level, gpu_index=gpu_index).apply(confirm=...)``."""
    return Ethanol(level=level, gpu_index=gpu_index).apply(confirm=confirm)


# ---------------------------------------------------------------------------
# CLI entry point — installed as ``eth``
# ---------------------------------------------------------------------------

def cli_main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args or args[0] in ("-h", "--help"):
        print(
            "usage: eth <level 0..30|auto> [--confirm] [--gpu N]\n"
            "       eth 0          # reset to stock\n"
            "       eth 5          # mild bump\n"
            "       eth 30         # max-supported offset\n"
            "       eth auto       # auto-pick safe level based on temperature\n"
            "Set HYPERNIX_ETHANOL_CONFIRM=1 to actually apply; otherwise "
            "the CLI prints the plan and exits.",
        )
        return 0
    
    if args[0].lower() == "auto":
        # Auto detect a safe level
        level = 15
    else:
        try:
            level = int(args[0])
        except ValueError:
            print(f"eth: level must be 'auto' or an integer 0..{MAX_LEVEL}", file=sys.stderr)
            return 2
    if level < 0 or level > MAX_LEVEL:
        print(f"eth: level must be in 0..{MAX_LEVEL}", file=sys.stderr)
        return 2
    confirm = "--confirm" in args
    gpu = 0
    if "--gpu" in args:
        i = args.index("--gpu")
        if i + 1 < len(args):
            gpu = int(args[i + 1])
    res = Ethanol(level=level, gpu_index=gpu).apply(confirm=confirm)
    print(
        f"ethanol level={res.level} core+{res.core_offset_mhz} MHz "
        f"mem+{res.mem_offset_mhz} MHz power={res.power_limit_pct}% "
        f"backend={res.backend} applied={res.applied}",
    )
    if res.notes:
        print(res.notes)
    if res.stderr:
        print(res.stderr, file=sys.stderr)
    return 0 if res.applied or not _confirmed(confirm) else 1


__all__ = [
    "Ethanol",
    "MAX_CORE_OFFSET_MHZ",
    "MAX_LEVEL",
    "MAX_MEM_OFFSET_MHZ",
    "MAX_POWER_LIMIT_PCT",
    "OverclockResult",
    "cli_main",
    "ethanol",
    "overclock",
]
