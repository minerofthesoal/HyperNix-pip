# Training Dashboards — `tv`, `tvtop_plus_plus`, and the `tvtop*` console scripts

Three live btop++-style terminal dashboards for watching a training run:
the original `tv` (`TVTop`), the "premium" `tvtop_plus_plus`
(`TVTopPlusPlus`), and a C++-accelerated `cctvtop` requiring an optional
compiled extension. All three tail a training log, parse `step N/M
loss=X` -style lines, and render CPU/RAM/GPU vitals alongside training
progress.

**⚠️ Console script mapping does not match the README / package
docstrings.** The README states "Console script `tvtop` now launches
the premium `tvtop_plus_plus` dashboard by default; use `tvtop-old` for
the classic view." The actual `pyproject.toml` entry points (as of this
writing) are:

| Script | Actually runs |
|---|---|
| `tvtop` | `hypernix.cctvtop:cli_main` — the **C++-accelerated** dashboard |
| `cctvtop` | same as `tvtop` |
| `tvtop-old` | `hypernix.tvtop_plus_plus:cli_main` — the **premium** dashboard (not "classic"!) |
| `tvtop-older` | `hypernix.tv:cli_main` — the actual original/classic dashboard |
| `tvtop-plus-plus` / `tvtoppp` | `hypernix.tvtop_plus_plus:cli_main` |

Practically: `cctvtop` (and therefore the bare `tvtop` command) requires
the optional `cctvtop_ext` C++ extension, **not built by default** — if
it's missing, running `tvtop` prints `cctvtop_ext C++ module not found`
and exits with status 1. If you just `pip install hypernix` and run
`tvtop` expecting a dashboard, you'll likely hit this. Use `tvtop-old`
(premium Rich dashboard) or `tvtop-older` (original) directly, or build
the extension per `cctvtop --help`'s instructions
(`pip install -e .` with `BUILD_CCTVTOP=1`, or `python setup.py
build_ext --inplace`).

---

## `hypernix.tv` — the original dashboard (`TVTop`)

Zero hard dependencies — pure stdlib + ANSI escapes, no `curses`. Uses
`rich.live.Live` for a flicker-free display when `rich` is installed and
stdout is a TTY, otherwise falls back to a classic ANSI cursor-home
loop; on a non-TTY (CI, redirected output) degrades to one plain line
per frame.

```bash
tvtop-older                     # auto-detect a hypernix training log
tvtop-older --log path/to.log   # explicit log path
tvtop-older --no-color
tvtop-older --ascii             # ASCII bars + sparkline, no Unicode
tvtop-older -s                  # compact/small mode
```

```python
from hypernix.tv import TVTop
TVTop(log_path="train.log").run()   # blocks until Ctrl-C
```

### What it shows

- Current step/total/percent with a progress bar
- Loss + LR + throughput, plus an inline sparkline of recent loss values
- Elapsed wall time + ETA
- CPU% / RAM% / GPU util% / VRAM (via `nvidia-smi` when available,
  throttled to once every 3s so a 1-second refresh doesn't shell out 60×/min)
- Last 8 log lines, sanitized (non-printable bytes replaced with `?`)

When the log has no parsable training lines yet, it renders a clean
"waiting for training data…" state instead of misleading zeros.

### `LogTail` — the log parser

```python
from hypernix.tv import LogTail
tail = LogTail(Path("train.log"), history_size=8)
new_lines = tail.poll()   # call repeatedly; tracks file offset, handles rotation/truncation
```

`.poll()` reads only newly-appended bytes since the last call (tracks
`_last_size`; resets to 0 if the file shrank, handling log
rotation/truncation). Parsing is two-tiered:
1. **Legacy format** — a single combined regex (`_STEP_RE`) matching the
   canonical `step N/M loss=X lr=Y tput=Z` shape.
2. **Resilient iterative matching** — if the legacy regex doesn't match,
   independently searches the line for loss (`loss[:=]...` or
   `inf`/`nan`), step/total (`step=N/M`, `epoch=N/M`, `[N/M]`, or a bare
   `step N`), a percent value (used to back-derive `step` if
   `total_steps` is already known), learning rate (`lr[:=]...`), and
   throughput (`tput`/`throughput[:=]...` or a value followed by
   `it/s`/`steps/s`/`samples/s`/etc.) — each independently, so a line
   with just `loss=1.2` still registers as training data even without a
   step number.

Exposes `.step`, `.total_steps`, `.loss`, `.lr`, `.throughput`,
`.has_training_data`, `.losses` (rolling `deque(maxlen=120)`), and
`.tail` (rolling `deque(maxlen=history_size)` of recent raw lines).

### Auto-detection (`_autodetect_log`)

Globs `**/train*.log`, `**/*training*.log`, then `**/*.log` under the
cwd, ranks candidates: prefers files that actually contain a `step ...
loss=...` match in their first 16 KiB (`_looks_like_training_log`), then
falls back to filename containing `"train"`, then just the newest `.log`
file overall. This ordering exists specifically to stop the dashboard
from latching onto a stray Konsole/browser/system log.

### `Frame` and `sparkline()`

`Frame` (dataclass) is the per-tick snapshot passed to `.render()` —
carries every parsed/measured field (`step`, `loss`, `cpu_percent`,
`gpu_util_percent`, rolling histories, etc.) so rendering logic never
touches `TVTop`'s or `LogTail`'s internal state directly.

`sparkline(values, *, ascii_only=False)` — renders an iterable of floats
as a compact Unicode block-character (or ASCII, if requested) sparkline
string.

### CLI (`cli_main`, registered as `tvtop-older`)

```
usage: tvtop-older [--log path] [--no-color] [--ascii] [--refresh SECONDS] [-s|--small]
```

Auto-detects the newest shaped `*.log` under cwd if `--log` isn't given;
prints a warning (not a hard failure) if the resolved log doesn't yet
contain any `step N/M loss=X` lines.

### Required modules

Standard library only for the core dashboard — `re`, `shutil`,
`subprocess` (for `nvidia-smi`), `sys`, `time`, `collections`,
`collections.abc`, `dataclasses`, `pathlib`, `typing`. `rich` and
`psutil` are optional — `rich` powers the flicker-free live mode
(falls back to classic ANSI otherwise), `psutil` improves CPU/per-core
readings (falls back to parsing `/proc/stat`/`/proc/meminfo` directly
on Linux if absent).

---

## `hypernix.tvtop_plus_plus` — the premium dashboard (`TVTopPlusPlus`)

A more heavily-styled variant reusing most of `tv.py`'s internals
(`Frame`, `LogTail`, `_autodetect_log`, the hardware-probing helpers,
`multi_row_graph`) but with its own Rich layout: `DOUBLE`/`ROUNDED` box
styles, animated spinner characters (`SPINNERS`), a live process list
(top-5 by CPU%, via `psutil`), CPU/RAM/GPU block-history bars, and
asymptotic loss-curve extrapolation. **Requires `rich`** — unlike `tv`,
there's no ANSI-fallback path; `TVTopPlusPlus.run()` always goes through
`rich.live.Live`.

```bash
tvtop-old                      # despite the name, this is the PREMIUM dashboard, not the classic one
tvtop-old --log train.log
tvtop-plus-plus                # same script, alternate name
tvtoppp                        # same script, shortest alias
```

Gauge colors intentionally match the original `tv` dashboard's
convention: CPU = green, RAM = magenta, GPU = red.

Constructor fields mirror `TVTop`'s: `log_path`, `refresh_seconds=1.0`,
`color=True`, `ascii_only=False`, `width=None`, `small_mode=False`.

### CLI (`cli_main`)

```
usage: tvtop++ [--log path] [--no-color] [--ascii] [--refresh SECONDS] [-s|--small]
```

Same flag set as `tv.cli_main`, but unlike `tv`'s CLI, if no log file is
found or specified, it doesn't error out — it prints `"No log file
specified - displaying live system metrics only"` and runs anyway with
a blank training panel.

### Required modules

- `rich` (`rich.box`, `rich.console`, `rich.layout`, `rich.live`,
  `rich.panel`, `rich.table`, `rich.text`) — **hard** dependency (no
  fallback path, unlike `tv`)
- `hypernix.tv` (internal — reuses `Frame`, `LogTail`, `_autodetect_log`,
  and several private rendering/probing helpers)
- `psutil` — used for the process-list panel; degrades gracefully
  (empty list) if unavailable or a process disappears mid-scan
  (`psutil.NoSuchProcess`/`AccessDenied` caught)
- Standard library: `sys`, `time`, `collections`, `dataclasses`, `pathlib`, `typing`

---

## `hypernix.cctvtop` — the C++-accelerated dashboard

```bash
cctvtop --help
```

A thin Python wrapper (`cli_main`) that imports a compiled
`hypernix.cctvtop_ext` C++ extension module and, if present, tails the
most recently modified `*.log` under the cwd through it. If the
extension isn't importable, prints `cctvtop_ext C++ module not found.
Did you compile the package?` and exits with status `1` — this is the
module actually mapped to the plain `tvtop` command, so a fresh install
without the compiled extension will hit this every time `tvtop` is run
bare.

### Required modules

`hypernix.cctvtop_ext` — a compiled C++ extension, **not built by
default**. Build via `pip install -e .` with `BUILD_CCTVTOP=1` set, or
`python setup.py build_ext --inplace`.

---

## See also

- [Kitchen](Kitchen.md) — general training subsystem overview
- `hypernix.pressure_cooker` / `hypernix.optimizer_framework` — the optimizers whose training loop typically writes the `*.log` file these dashboards tail
- [Freezer](Freezer.md) — VRAM/hardware presets, a related but distinct hardware-awareness concern from these dashboards' live vitals display
