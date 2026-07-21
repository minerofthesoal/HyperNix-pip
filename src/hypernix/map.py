"""hypernix.map — a steampunk schematic TUI for the model you're training.

``hnx map`` draws your model as a little machine: parameter counts become
analog **dials**, layer connections become **pipes**, live token/activation
flow becomes animated **steam**, and the prompt/dataset inputs feeding the
network become **steam engines**. A dedicated throttle dial in the corner
visibly ticks over while training is actually running, so a glance across
the room tells you the loop is alive.

Config
------
Settings persist to ``~/.hypernix/map_config.json`` and are managed with
``hnx map config``::

    hnx map config poly <16|32|64|128>       schematic detail level —
                                              higher poly means finer dial
                                              needles, richer pipe joints,
                                              and more animated steam frames.
    hnx map config acc <N|Nk|Nm|Nb|Nt>       parameters represented by one
                                              full dial sweep, e.g. "1m" =
                                              a dial reads 0..1,000,000 params.
    hnx map config main use-gpu <true|false> show a GPU boiler-pressure
                                              readout (nvidia-smi).
    hnx map config main tps <1-30>           refresh rate, ticks per second.
    hnx map config main file model <1|2|3>   what the map reads from:
                                                1 = a single safetensors file
                                                    (needs -f "<path>")
                                                2 = ./checkpoints/train.log
                                                    (no path needed)
                                                3 = a full model folder
                                                    (needs -F "<path>")

Run
---
``hnx map`` launches the live TUI using the current stored config. Move
the mouse into the bottom-right corner to reveal the legend (falls back to
pressing ``?`` on terminals without mouse-motion reporting). Press ``q`` or
Ctrl-C to exit.
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Config subsystem — mirrors hypernix.config's load/save shape, but map.py
# owns its own file since its keys (poly/acc/tps/...) are a distinct domain.
# ---------------------------------------------------------------------------

_MAP_CONFIG_DIR = Path.home() / ".hypernix"
_MAP_CONFIG_FILE = _MAP_CONFIG_DIR / "map_config.json"

POLY_LEVELS: tuple[int, ...] = (16, 32, 64, 128)
FILE_MODES: tuple[int, ...] = (1, 2, 3)
_DEFAULT_TRAIN_LOG = Path("checkpoints") / "train.log"

_MAP_DEFAULTS: dict[str, Any] = {
    "poly": 32,
    "acc": "1m",
    "use_gpu": True,
    "tps": 8,
    "file_mode": 2,        # 1=safetensors file, 2=train.log, 3=model folder
    "file_path": None,     # required for modes 1 (-f) and 3 (-F)
}


class MapConfigError(ValueError):
    """Raised for invalid ``hnx map config`` input; message is user-facing."""


def _load_map_config() -> dict[str, Any]:
    if not _MAP_CONFIG_FILE.exists():
        return dict(_MAP_DEFAULTS)
    try:
        with open(_MAP_CONFIG_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        cfg = dict(_MAP_DEFAULTS)
        cfg.update(data)
        return cfg
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[map] Warning: could not read {_MAP_CONFIG_FILE}: {exc}", file=sys.stderr)
        return dict(_MAP_DEFAULTS)


def _save_map_config(cfg: dict[str, Any]) -> None:
    _MAP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(_MAP_CONFIG_FILE, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)


def get_map_config() -> dict[str, Any]:
    """Public API: the current persisted map config (with defaults filled in)."""
    return _load_map_config()


# ---------------------------------------------------------------------------
# acc — "N params per one full dial sweep", accepts 1 / 1k / 1m / 1b / 1t.
# ---------------------------------------------------------------------------

_ACC_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([kmbt]?)\s*$", re.IGNORECASE)
_ACC_SUFFIX = {"": 1.0, "k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}


def parse_acc(value: str) -> float:
    """Parse an ``acc`` string like ``"1"``/``"1k"``/``"2.5m"``/``"1t"``
    into the raw parameter count it represents. Raises :class:`MapConfigError`
    on anything that doesn't look like ``<number><k|m|b|t>``."""
    m = _ACC_RE.match(value)
    if not m:
        raise MapConfigError(
            f"invalid acc value {value!r} — expected a number optionally "
            "followed by k/m/b/t, e.g. '1', '1k', '2.5m', '1t'"
        )
    number, suffix = m.group(1), m.group(2).lower()
    result = float(number) * _ACC_SUFFIX[suffix]
    if result <= 0:
        raise MapConfigError(f"acc must be a positive value, got {value!r}")
    return result


def set_poly(value: str | int) -> int:
    try:
        poly = int(value)
    except (TypeError, ValueError) as exc:
        raise MapConfigError(f"poly must be an integer, got {value!r}") from exc
    if poly not in POLY_LEVELS:
        raise MapConfigError(
            f"poly must be one of {POLY_LEVELS}, got {poly}"
        )
    cfg = _load_map_config()
    cfg["poly"] = poly
    _save_map_config(cfg)
    return poly


def set_acc(value: str) -> str:
    parse_acc(value)  # validate; raises MapConfigError on bad input
    cfg = _load_map_config()
    cfg["acc"] = value
    _save_map_config(cfg)
    return value


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in ("true", "1", "yes", "on"):
        return True
    if lowered in ("false", "0", "no", "off"):
        return False
    raise MapConfigError(f"expected true/false, got {value!r}")


def set_use_gpu(value: str | bool) -> bool:
    parsed = _parse_bool(value)
    cfg = _load_map_config()
    cfg["use_gpu"] = parsed
    _save_map_config(cfg)
    return parsed


def set_tps(value: str | int) -> int:
    try:
        tps = int(value)
    except (TypeError, ValueError) as exc:
        raise MapConfigError(f"tps must be an integer, got {value!r}") from exc
    if not (1 <= tps <= 30):
        raise MapConfigError(f"tps must be between 1 and 30, got {tps}")
    cfg = _load_map_config()
    cfg["tps"] = tps
    _save_map_config(cfg)
    return tps


def set_file_mode(mode: str | int, path: str | None = None, *, flag: str | None = None) -> dict[str, Any]:
    try:
        mode_i = int(mode)
    except (TypeError, ValueError) as exc:
        raise MapConfigError(f"model must be 1, 2, or 3, got {mode!r}") from exc
    if mode_i not in FILE_MODES:
        raise MapConfigError(f"model must be 1, 2, or 3, got {mode_i}")
    if mode_i == 1:
        if not path:
            raise MapConfigError('model 1 (safetensors file) requires -f "<path>"')
        if flag == "-F":
            raise MapConfigError("model 1 (safetensors file) takes -f, not -F")
    if mode_i == 3:
        if not path:
            raise MapConfigError('model 3 (full model folder) requires -F "<path>"')
        if flag == "-f":
            raise MapConfigError("model 3 (full model folder) takes -F, not -f")
    if mode_i == 2 and path:
        raise MapConfigError(
            "model 2 (train.log) doesn't take a path — it always reads "
            f"./{_DEFAULT_TRAIN_LOG}"
        )
    cfg = _load_map_config()
    cfg["file_mode"] = mode_i
    cfg["file_path"] = path
    _save_map_config(cfg)
    return {"file_mode": mode_i, "file_path": path}


# ---------------------------------------------------------------------------
# Data model — turn a safetensors file (or a folder full of them) into a
# list of "nodes" (one per transformer layer, plus embed/norm/head) with
# parameter counts, which the schematic renders as a chain of dials.
# ---------------------------------------------------------------------------

# Matches the common "...layers.N...", "...h.N...", "...blocks.N..." naming
# schemes used across HF model families (llama/qwen/gpt-neox/gpt2/mpt/...).
_LAYER_RE = re.compile(r"\.(?:h|layer|layers|block|blocks)\.(\d+)\.")


def _bucket_for_tensor(name: str) -> tuple[str, str]:
    """Return ``(bucket_key, bucket_label)`` for a tensor name.

    Per-layer tensors bucket by their numeric layer index; everything
    else buckets into a small set of named pseudo-nodes. Keys are
    prefixed with a category rank (0=embed, 1=layer, 5=other, 8=norm,
    9=head) so a plain lexical sort of the keys reproduces the natural
    front-to-back flow of the model (embeddings, then layers in order,
    then the final norm and head) instead of e.g. "8:norm" sorting
    before "layer:..." just because '8' < 'l' in ASCII.
    """
    m = _LAYER_RE.search(name)
    if m:
        idx = int(m.group(1))
        return (f"1:{idx:06d}", f"L{idx}")
    lname = name.lower()
    if "embed" in lname:
        return ("0:0", "Embed")
    if "lm_head" in lname:
        return ("9:0", "LMHead")
    if "norm" in lname:
        return ("8:0", "Norm")
    return ("5:0", "Other")


@dataclass
class LayerNode:
    key: str
    label: str
    param_count: int = 0
    tensor_count: int = 0


@dataclass
class ModelSnapshot:
    source: str
    layers: list[LayerNode] = field(default_factory=list)
    total_params: int = 0
    dtype: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _numel(shape: list[int] | tuple[int, ...]) -> int:
    n = 1
    for d in shape:
        n *= int(d)
    return n


def _snapshot_from_tensor_iter(
    source: str, tensor_shapes: dict[str, tuple[list[int], str]],
) -> ModelSnapshot:
    """Build a :class:`ModelSnapshot` from ``{name: (shape, dtype)}``."""
    buckets: dict[str, LayerNode] = {}
    dtype: str | None = None
    total = 0
    for name, (shape, dt) in tensor_shapes.items():
        key, label = _bucket_for_tensor(name)
        node = buckets.setdefault(key, LayerNode(key=key, label=label))
        n = _numel(shape)
        node.param_count += n
        node.tensor_count += 1
        total += n
        dtype = dtype or dt
    layers = [buckets[k] for k in sorted(buckets)]
    return ModelSnapshot(source=source, layers=layers, total_params=total, dtype=dtype)


def _snapshot_from_safetensors_file(path: Path) -> ModelSnapshot:
    try:
        from safetensors import safe_open
    except ImportError:
        return ModelSnapshot(source=str(path), error="safetensors is not installed")
    if not path.exists():
        return ModelSnapshot(source=str(path), error=f"file not found: {path}")
    try:
        shapes: dict[str, tuple[list[int], str]] = {}
        with safe_open(str(path), framework="pt") as fh:
            for key in fh.keys():  # noqa: SIM118 - safetensors has no __iter__
                sl = fh.get_slice(key)
                shapes[key] = (list(sl.get_shape()), str(sl.get_dtype()))
        return _snapshot_from_tensor_iter(str(path), shapes)
    except Exception as exc:  # noqa: BLE001
        return ModelSnapshot(source=str(path), error=f"failed to read {path}: {exc}")


def _snapshot_from_folder(path: Path) -> ModelSnapshot:
    if not path.exists() or not path.is_dir():
        return ModelSnapshot(source=str(path), error=f"folder not found: {path}")

    # Prefer real weight files (single or sharded) -- exact param counts.
    single = path / "model.safetensors"
    shards = sorted(path.glob("*.safetensors"))
    files: list[Path] = []
    if single.exists():
        files = [single]
    elif shards:
        files = shards

    if files:
        try:
            from safetensors import safe_open
        except ImportError:
            return ModelSnapshot(source=str(path), error="safetensors is not installed")
        shapes: dict[str, tuple[list[int], str]] = {}
        try:
            for f in files:
                with safe_open(str(f), framework="pt") as fh:
                    for key in fh.keys():  # noqa: SIM118
                        sl = fh.get_slice(key)
                        shapes[key] = (list(sl.get_shape()), str(sl.get_dtype()))
            return _snapshot_from_tensor_iter(str(path), shapes)
        except Exception as exc:  # noqa: BLE001
            return ModelSnapshot(source=str(path), error=f"failed to read weights in {path}: {exc}")

    # No weight files -- fall back to an analytical estimate from config.json
    # so folders that only hold a config (e.g. a fresh `hnx train init`
    # scratch dir) still render something.
    cfg_path = path / "config.json"
    if not cfg_path.exists():
        return ModelSnapshot(
            source=str(path),
            error=f"no *.safetensors or config.json found in {path}",
        )
    try:
        with open(cfg_path, encoding="utf-8") as fh:
            hf_cfg = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        return ModelSnapshot(source=str(path), error=f"could not read config.json: {exc}")

    return _estimate_snapshot_from_hf_config(str(path), hf_cfg)


def _estimate_snapshot_from_hf_config(source: str, hf_cfg: dict[str, Any]) -> ModelSnapshot:
    """Standard dense-transformer parameter-count formula, used only when
    no real weight file is available to inspect directly."""
    try:
        vocab = int(hf_cfg.get("vocab_size", 0))
        hidden = int(hf_cfg.get("hidden_size", 0))
        inter = int(hf_cfg.get("intermediate_size", hidden * 4))
        n_layers = int(hf_cfg.get("num_hidden_layers", 0))
        tie_embeds = bool(hf_cfg.get("tie_word_embeddings", False))
    except (TypeError, ValueError) as exc:
        return ModelSnapshot(source=source, error=f"unrecognised config.json shape: {exc}")
    if hidden <= 0 or n_layers <= 0 or vocab <= 0:
        return ModelSnapshot(
            source=source,
            error="config.json is missing vocab_size/hidden_size/num_hidden_layers",
        )

    layers: list[LayerNode] = []
    embed_params = vocab * hidden
    layers.append(LayerNode(key="0:0", label="Embed", param_count=embed_params, tensor_count=1))

    # Attention (q/k/v/o, each hidden*hidden) + MLP (gate/up/down, each
    # hidden*inter) + two RMSNorms (negligible, ~2*hidden) per layer.
    per_layer = 4 * hidden * hidden + 3 * hidden * inter + 2 * hidden
    for i in range(n_layers):
        layers.append(LayerNode(key=f"1:{i:06d}", label=f"L{i}", param_count=per_layer, tensor_count=9))

    layers.append(LayerNode(key="8:0", label="Norm", param_count=hidden, tensor_count=1))
    if not tie_embeds:
        layers.append(LayerNode(key="9:0", label="LMHead", param_count=vocab * hidden, tensor_count=1))

    total = sum(n.param_count for n in layers)
    snap = ModelSnapshot(source=source, layers=layers, total_params=total, dtype="estimated")
    return snap


def build_snapshot(cfg: dict[str, Any] | None = None) -> ModelSnapshot:
    """Dispatch on ``cfg['file_mode']`` to build the current
    :class:`ModelSnapshot` the schematic should render."""
    cfg = cfg if cfg is not None else _load_map_config()
    mode = cfg.get("file_mode", 2)
    if mode == 1:
        path = cfg.get("file_path")
        if not path:
            return ModelSnapshot(source="(none)", error="no safetensors path configured — set one with -f")
        return _snapshot_from_safetensors_file(Path(path))
    if mode == 3:
        path = cfg.get("file_path")
        if not path:
            return ModelSnapshot(source="(none)", error="no model folder configured — set one with -F")
        return _snapshot_from_folder(Path(path))
    # mode == 2: train.log has no architecture info by itself -- the map
    # still needs *some* nodes to draw pipes between, so this mode is
    # normally paired with whatever the last-known snapshot was. Callers
    # that only have a train.log pass one in via a cached snapshot instead
    # of calling build_snapshot() fresh each tick; see HyperMap.
    return ModelSnapshot(source=str(_DEFAULT_TRAIN_LOG), error=None)


# ---------------------------------------------------------------------------
# Poly-tiered glyph sets — "poly" scales dial/pipe/steam/engine detail.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PolyGlyphs:
    pipe_h: str
    pipe_v: str
    tl: str
    tr: str
    bl: str
    br: str
    joint: str
    steam_frames: tuple[str, ...]
    track_width: int
    rim_l: str
    rim_r: str
    engine: tuple[str, ...]


_POLY_GLYPHS: dict[int, PolyGlyphs] = {
    16: PolyGlyphs(
        pipe_h="-", pipe_v="|", tl="+", tr="+", bl="+", br="+", joint="+",
        steam_frames=(".", "o"),
        track_width=5, rim_l="[", rim_r="]",
        engine=(" ___ ", "|SsS|", "|___|"),
    ),
    32: PolyGlyphs(
        pipe_h="\u2500", pipe_v="\u2502", tl="\u256d", tr="\u256e", bl="\u2570", br="\u256f", joint="\u253c",
        steam_frames=("\u02d9", "\u00b0", "o"),
        track_width=9, rim_l="(", rim_r=")",
        engine=(" \u256d\u2500\u2500\u256e ", "\u2500\u2524ss\u251c\u2500", " \u2570\u2500\u2500\u256f "),
    ),
    64: PolyGlyphs(
        pipe_h="\u2501", pipe_v="\u2503", tl="\u250f", tr="\u2513", bl="\u2517", br="\u251b", joint="\u254b",
        steam_frames=("\u02d9", "\u00b0", "o", "O"),
        track_width=13, rim_l="\u27e8", rim_r="\u27e9",
        engine=(" \u250f\u2501\u2501\u2513 ", "\u2501\u252b\u25c9\u25c9\u2523\u2501", " \u2517\u2501\u2501\u251b "),
    ),
    128: PolyGlyphs(
        pipe_h="\u2550", pipe_v="\u2551", tl="\u2554", tr="\u2557", bl="\u255a", br="\u255d", joint="\u256c",
        steam_frames=("\u02d9", "\u00b7", "\u00b0", "o", "O", "0", "Q", "@"),
        track_width=21, rim_l="\u300a", rim_r="\u300b",
        engine=(" \u2554\u2550\u2550\u2557 ", "\u2550\u2563\u25c8\u25c8\u2560\u2550", " \u255a\u2550\u2550\u255d "),
    ),
}


def glyphs_for_poly(poly: int) -> PolyGlyphs:
    return _POLY_GLYPHS.get(poly, _POLY_GLYPHS[32])


# ---------------------------------------------------------------------------
# Dial / pipe / steam / engine rendering
# ---------------------------------------------------------------------------

def dial_frac(param_count: int, acc_value: float) -> float:
    """0..1 needle position for a dial whose full sweep represents
    ``acc_value`` parameters, given a node holding ``param_count``."""
    if acc_value <= 0:
        return 0.0
    return max(0.0, min(1.0, param_count / acc_value))


def render_dial(label: str, frac: float, glyphs: PolyGlyphs) -> list[str]:
    """Render a labeled dial as ``[label row, needle-track row]``."""
    width = max(1, glyphs.track_width)
    pos = int(round(max(0.0, min(1.0, frac)) * (width - 1)))
    track = list(glyphs.pipe_h * width)
    track[pos] = "\u25cf"  # ●
    track_str = glyphs.rim_l + "".join(track) + glyphs.rim_r
    label_str = f"{label:^{len(track_str)}}"[: len(track_str)]
    return [label_str, track_str]


def throttle_frac(tick: int, active: bool, poly: int) -> float:
    """Triangle-wave sweep 0->1->0 while ``active``; parked at 0 when idle.

    The sweep period scales with ``poly`` so a higher detail level gives a
    slower, smoother-looking needle motion rather than a jerkier one.
    """
    if not active:
        return 0.0
    period = max(4, poly)
    pos = tick % period
    half = period / 2.0
    return pos / half if pos <= half else (period - pos) / half


def render_pipe_segment(glyphs: PolyGlyphs, length: int, tick: int, *, active: bool) -> str:
    """A horizontal pipe run with a traveling steam puff when ``active``."""
    if length <= 0:
        return ""
    base = glyphs.pipe_h * length
    if not active:
        return base
    frame = glyphs.steam_frames[tick % len(glyphs.steam_frames)]
    puff_pos = tick % length
    chars = list(base)
    chars[puff_pos] = frame
    return "".join(chars)


def render_engine(glyphs: PolyGlyphs, label: str, tick: int, *, active: bool) -> list[str]:
    """A small boiler icon with rising steam above its chimney."""
    width = len(glyphs.engine[0])
    puff = glyphs.steam_frames[tick % len(glyphs.steam_frames)] if active else " "
    top = f"{puff:^{width}}"
    bottom = f"{label:^{width}}"
    return [top, *glyphs.engine, bottom]


# ---------------------------------------------------------------------------
# Canvas — a small 2D character grid so widgets (dials, pipes, engines, the
# legend overlay) can be stamped at exact positions instead of being glued
# together with string concatenation.
# ---------------------------------------------------------------------------

class Canvas:
    def __init__(self, width: int, height: int, fill: str = " ") -> None:
        self.width = max(1, width)
        self.height = max(1, height)
        self.rows: list[list[str]] = [[fill] * self.width for _ in range(self.height)]

    def stamp(self, x: int, y: int, text: str) -> None:
        if y < 0 or y >= self.height:
            return
        row = self.rows[y]
        for i, ch in enumerate(text):
            cx = x + i
            if 0 <= cx < self.width:
                row[cx] = ch

    def stamp_lines(self, x: int, y: int, lines: list[str]) -> None:
        for i, line in enumerate(lines):
            self.stamp(x, y + i, line)

    def render(self) -> str:
        return "\n".join("".join(row) for row in self.rows)


def _layout_positions(n_items: int, cols_per_row: int) -> list[tuple[int, int]]:
    """Return ``(col, row)`` for each of ``n_items`` in boustrophedon
    (snake) reading order: row 0 goes left-to-right, row 1 goes
    right-to-left, row 2 left-to-right again, and so on. This keeps the
    connecting pipe between the last dial of one row and the first dial
    of the next a short straight drop in the same column, instead of a
    long diagonal run across the whole width.
    """
    cols_per_row = max(1, cols_per_row)
    positions: list[tuple[int, int]] = []
    for i in range(n_items):
        row = i // cols_per_row
        offset = i % cols_per_row
        col = offset if row % 2 == 0 else (cols_per_row - 1 - offset)
        positions.append((col, row))
    return positions


# ---------------------------------------------------------------------------
# HyperMap — top-level state + frame rendering.
#
# Architecture (dial layout) comes from ``file_mode``; live training
# telemetry (is a run active? how fast?) always comes from
# ``checkpoints/train.log`` regardless of mode, since the two questions
# ("what does the model look like" vs "is it training right now") are
# independent -- you might point the map at a snapshot .safetensors file
# while a completely separate training loop is what's actually running.
# ---------------------------------------------------------------------------

class HyperMap:
    def __init__(
        self,
        cfg: dict[str, Any] | None = None,
        *,
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        from .tv import LogTail as _LogTail

        self.cfg = cfg if cfg is not None else _load_map_config()
        self.poly = int(self.cfg.get("poly", 32))
        if self.poly not in POLY_LEVELS:
            self.poly = 32
        self.glyphs = glyphs_for_poly(self.poly)
        self.acc_label = str(self.cfg.get("acc", "1m"))
        try:
            self.acc_value = parse_acc(self.acc_label)
        except MapConfigError:
            self.acc_value = parse_acc("1m")
        self.use_gpu = bool(self.cfg.get("use_gpu", True))
        self.tps = int(self.cfg.get("tps", 8))
        self._console_width = width
        self._console_height = height

        self.tick = 0
        self.legend_visible = False
        self.mouse_pos: tuple[int, int] | None = None
        self.snapshot: ModelSnapshot = build_snapshot(self.cfg)
        self.log = _LogTail(path=Path(_DEFAULT_TRAIN_LOG))

    # -- polling -----------------------------------------------------

    def poll(self) -> None:
        self.log.poll()
        self.tick += 1

    @property
    def is_active(self) -> bool:
        return bool(self.log.has_training_data)

    def gpu_reading(self) -> dict[str, Any] | None:
        if not self.use_gpu:
            return None
        from .tv import _query_nvidia_smi_full
        return _query_nvidia_smi_full()

    # -- layout --------------------------------------------------------

    def _term_size(self) -> tuple[int, int]:
        if self._console_width and self._console_height:
            return self._console_width, self._console_height
        import shutil
        size = shutil.get_terminal_size((100, 30))
        return size.columns, size.lines

    def _nodes(self) -> list[LayerNode]:
        if self.snapshot.layers:
            return self.snapshot.layers
        # No architecture data (file mode 2, or a mode 1/3 read error) --
        # still show one placeholder node so the pipeline isn't empty,
        # driven by step count against the same acc scale.
        return [LayerNode(key="train", label="TRAIN", param_count=self.log.step or 0, tensor_count=0)]

    def render(self) -> str:
        width, height = self._term_size()
        height = max(16, height - 1)
        canvas = Canvas(width, height)
        g = self.glyphs
        active = self.is_active
        tick = self.tick

        # -- title bar ---------------------------------------------
        title = (
            f" \u25c6 HYPERNIX MAP \u25c6  {self.snapshot.source}  "
            f"poly={self.poly} acc={self.acc_label} tps={self.tps} "
        )
        canvas.stamp(0, 0, title[:width])
        canvas.stamp(0, 1, g.pipe_h * min(width, len(title)))

        # -- steam engines (prompt + dataset input) ------------------
        engine_prompt = render_engine(g, "PROMPT", tick, active=active)
        engine_data = render_engine(g, "DATA", tick, active=active)
        engine_w = len(g.engine[0])
        engine_y = 3
        canvas.stamp_lines(1, engine_y, engine_prompt)
        canvas.stamp_lines(1, engine_y + len(engine_prompt) + 1, engine_data)

        pipe_start_x = 1 + engine_w + 2
        trunk_y = engine_y + (len(engine_prompt) + 1 + len(engine_data)) // 2

        # -- dial chain (parameter nodes) -----------------------------
        nodes = self._nodes()
        dial_cell_w = g.track_width + 2  # + rim chars
        col_gap = 3
        cell_w = dial_cell_w + col_gap
        dial_area_x = pipe_start_x + col_gap
        available = max(cell_w, width - dial_area_x - 2)
        cols = max(1, available // cell_w)
        positions = _layout_positions(len(nodes), cols)
        dial_area_y = trunk_y + 2
        row_h = 3

        # Trunk pipe from the engines into the first dial.
        canvas.stamp(pipe_start_x, trunk_y, render_pipe_segment(g, col_gap, tick, active=active))
        if positions:
            first_row_y = dial_area_y + positions[0][1] * row_h + 1
            for y in range(min(trunk_y, first_row_y), max(trunk_y, first_row_y) + 1):
                canvas.stamp(pipe_start_x + col_gap - 1, y, g.pipe_v)

        for idx, (node, (col, row)) in enumerate(zip(nodes, positions, strict=False)):
            x = dial_area_x + col * cell_w
            y = dial_area_y + row * row_h
            frac = dial_frac(node.param_count, self.acc_value)
            canvas.stamp_lines(x, y, render_dial(node.label, frac, g))

            if idx + 1 >= len(nodes):
                continue
            ncol, nrow = positions[idx + 1]
            ny = dial_area_y + nrow * row_h
            if nrow == row:
                # horizontal connector to the next dial on the same row
                left_col, right_col = (col, ncol) if col < ncol else (ncol, col)
                gap_x = dial_area_x + left_col * cell_w + dial_cell_w
                canvas.stamp(gap_x, y + 1, render_pipe_segment(g, col_gap, tick, active=active))
            else:
                # vertical connector down to the next row (snake wrap) --
                # boustrophedon layout keeps col == ncol here.
                wrap_x = dial_area_x + col * cell_w + dial_cell_w // 2
                for wy in range(y + 2, ny + 1):
                    canvas.stamp(wrap_x, wy, g.pipe_v)

        # -- side panel: throttle dial + totals + GPU pressure --------
        panel_x = width - max(24, g.track_width + 6)
        panel_y = 3
        if panel_x > dial_area_x + cell_w:  # only draw if it won't overlap the pipeline
            t_frac = throttle_frac(tick, active, self.poly)
            canvas.stamp_lines(panel_x, panel_y, render_dial("THROTTLE", t_frac, g))

            total = self.snapshot.total_params
            total_label = _fmt_count(total) if total else "?"
            canvas.stamp(panel_x, panel_y + 3, f"\u03a3 params {total_label}")
            status = "RUNNING" if active else "idle"
            canvas.stamp(panel_x, panel_y + 4, f"status: {status}")

            gpu = self.gpu_reading()
            if gpu is not None:
                util = gpu.get("util_percent")
                gfrac = (util or 0.0) / 100.0
                canvas.stamp_lines(panel_x, panel_y + 6, render_dial("GPU PRESSURE", gfrac, g))
                if gpu.get("temp_c") is not None:
                    canvas.stamp(panel_x, panel_y + 9, f"{gpu['temp_c']:.0f}\u00b0C")

        # -- status line -----------------------------------------------
        status_line = (
            f" tick {tick}  \u00b7  mode {self.cfg.get('file_mode')}  \u00b7  "
            f"q quit  \u00b7  ? legend "
        )
        canvas.stamp(0, height - 1, status_line[:width])

        # -- legend overlay (bottom-right corner) ----------------------
        if self.legend_visible:
            _stamp_legend(canvas, g)

        return canvas.render()

    # -- run loop --------------------------------------------------------

    def run(self) -> None:
        reader = _MouseReader()
        reader.start()
        try:
            interval = 1.0 / max(1, self.tps)
            while True:
                self.poll()
                if reader.mouse_pos is not None:
                    width, height = self._term_size()
                    self.legend_visible = _is_bottom_right(reader.mouse_pos, width, height)
                if reader.legend_toggle_requested:
                    self.legend_visible = not self.legend_visible
                    reader.legend_toggle_requested = False
                if reader.quit_requested:
                    break
                sys.stdout.write("\x1b[2J\x1b[H")
                sys.stdout.write(self.render())
                sys.stdout.flush()
                time.sleep(interval)
        except KeyboardInterrupt:
            pass
        finally:
            reader.stop()


def _fmt_count(n: int) -> str:
    if n >= 1e12:
        return f"{n / 1e12:.2f}T"
    if n >= 1e9:
        return f"{n / 1e9:.2f}B"
    if n >= 1e6:
        return f"{n / 1e6:.2f}M"
    if n >= 1e3:
        return f"{n / 1e3:.2f}K"
    return str(n)


_LEGEND_LINES: tuple[str, ...] = (
    "\u2500\u2500 legend \u2500\u2500",
    "\u25cf dial  = param count / acc",
    "\u2500\u2500 pipe  = layer link",
    "\u02d9\u00b0oO   = steam (active)",
    "\u2632\u2632  engine = prompt/data in",
    "q quit  ? toggle legend",
)


def _stamp_legend(canvas: Canvas, glyphs: PolyGlyphs) -> None:
    body_w = max(len(f" {line}") for line in _LEGEND_LINES)
    box_w = body_w + 2
    box_h = len(_LEGEND_LINES) + 2
    x = max(0, canvas.width - box_w)
    y = max(0, canvas.height - box_h)
    canvas.stamp(x, y, glyphs.tl + glyphs.pipe_h * (box_w - 2) + glyphs.tr)
    for i, line in enumerate(_LEGEND_LINES):
        canvas.stamp(x, y + 1 + i, glyphs.pipe_v + f" {line}".ljust(body_w) + glyphs.pipe_v)
    canvas.stamp(x, y + box_h - 1, glyphs.bl + glyphs.pipe_h * (box_w - 2) + glyphs.br)


def _is_bottom_right(pos: tuple[int, int], width: int, height: int, margin: int = 12) -> bool:
    x, y = pos
    return x >= width - margin and y >= height - margin


# ---------------------------------------------------------------------------
# Mouse hover reveal — "move to the bottom-right corner for the legend".
#
# Uses raw xterm SGR mouse-motion reporting, which needs cbreak mode on a
# real TTY (POSIX only via termios/tty). Parsing is a pure function so it's
# testable without a live terminal; the reader thread itself degrades to a
# no-op (``available = False``) on anything else, e.g. Windows, a pipe, or
# a CI sandbox -- the ``?`` key still toggles the legend either way.
# ---------------------------------------------------------------------------

_SGR_MOUSE_RE = re.compile(r"\x1b\[<\d+;(\d+);(\d+)[Mm]")


def _parse_sgr_mouse(buf: str) -> tuple[int, int] | None:
    """Return the last complete ``(col, row)`` SGR mouse report in ``buf``,
    or ``None`` if it doesn't contain one yet. 1-indexed, as xterm reports."""
    matches = list(_SGR_MOUSE_RE.finditer(buf))
    if not matches:
        return None
    last = matches[-1]
    return (int(last.group(1)), int(last.group(2)))


class _MouseReader:
    """Background reader for mouse-motion + key events during ``hnx map``.

    ``mouse_pos`` / ``legend_toggle_requested`` / ``quit_requested`` are
    read by the render loop each tick; this class only ever writes them.
    """

    def __init__(self) -> None:
        self.mouse_pos: tuple[int, int] | None = None
        self.legend_toggle_requested = False
        self.quit_requested = False
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._old_settings: Any = None
        self.available = self._detect_available()

    @staticmethod
    def _detect_available() -> bool:
        try:
            import termios  # noqa: F401
            import tty  # noqa: F401
        except ImportError:
            return False
        try:
            return sys.stdin.isatty()
        except Exception:  # noqa: BLE001
            return False

    def start(self) -> None:
        if not self.available:
            return
        import termios
        import tty
        fd = sys.stdin.fileno()
        try:
            self._old_settings = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            sys.stdout.write("\x1b[?1003h\x1b[?1006h")
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            self.available = False
            return
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if not self.available:
            return
        try:
            sys.stdout.write("\x1b[?1003l\x1b[?1006l")
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass
        if self._old_settings is not None:
            import termios
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._old_settings)
            except Exception:  # noqa: BLE001
                pass

    def _read_loop(self) -> None:
        buf = ""
        while not self._stop.is_set():
            try:
                ch = sys.stdin.read(1)
            except Exception:  # noqa: BLE001
                return
            if not ch:
                continue
            if ch in ("q", "Q"):
                self.quit_requested = True
                continue
            if ch == "?":
                self.legend_toggle_requested = True
                continue
            buf += ch
            if len(buf) > 32:
                buf = buf[-32:]
            pos = _parse_sgr_mouse(buf)
            if pos is not None:
                self.mouse_pos = pos
                buf = ""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_USAGE = """\
Usage: hnx map [config <key> ...]

Draws your model as a schematic: dials for parameter counts, pipes for
layer connections, steam for live data flow, steam engines for prompt /
dataset input. Run with no arguments to launch the live TUI.

Config subcommands:
  poly <16|32|64|128>              schematic detail level.
  acc <N|Nk|Nm|Nb|Nt>               params represented by one full dial,
                                    e.g. "1m" -> a dial reads 0..1,000,000.
  main use-gpu <true|false>        show a GPU pressure readout.
  main tps <1-30>                  refresh rate, ticks per second.
  main file model <1|2|3> [-f PATH] [-F PATH]
                                    1 = safetensors file  (needs -f PATH)
                                    2 = ./checkpoints/train.log (no path)
                                    3 = full model folder (needs -F PATH)

Examples:
  hnx map config poly 64
  hnx map config acc 10m
  hnx map config main use-gpu false
  hnx map config main tps 12
  hnx map config main file model 1 -f ./model.safetensors
  hnx map config main file model 3 -F ./my-model-dir
  hnx map
"""


def _cli_config_main_file(rest: list[str]) -> int:
    if not rest or rest[0] != "model":
        print('[map] usage: hnx map config main file model <1|2|3> [-f PATH] [-F PATH]', file=sys.stderr)
        return 1
    rest = rest[1:]
    if not rest:
        print('[map] usage: hnx map config main file model <1|2|3> [-f PATH] [-F PATH]', file=sys.stderr)
        return 1
    mode = rest[0]
    path: str | None = None
    flag: str | None = None
    remaining = rest[1:]
    i = 0
    while i < len(remaining):
        tok = remaining[i]
        if tok in ("-f", "-F"):
            if i + 1 >= len(remaining):
                print(f"[map] {tok} requires a path argument", file=sys.stderr)
                return 1
            path = remaining[i + 1]
            flag = tok
            i += 2
        else:
            print(f"[map] unexpected argument: {tok!r}", file=sys.stderr)
            return 1
    try:
        result = set_file_mode(mode, path, flag=flag)
    except MapConfigError as exc:
        print(f"[map] {exc}", file=sys.stderr)
        return 1
    print(f"[map] file_mode = {result['file_mode']}, file_path = {result['file_path']}")
    return 0


def _cli_config_main(rest: list[str]) -> int:
    if not rest:
        print("[map] usage: hnx map config main <use-gpu|tps|file> ...", file=sys.stderr)
        return 1
    sub, *tail = rest
    try:
        if sub == "use-gpu":
            if not tail:
                raise MapConfigError("usage: hnx map config main use-gpu <true|false>")
            val = set_use_gpu(tail[0])
            print(f"[map] use_gpu = {val}")
            return 0
        if sub == "tps":
            if not tail:
                raise MapConfigError("usage: hnx map config main tps <1-30>")
            val = set_tps(tail[0])
            print(f"[map] tps = {val}")
            return 0
    except MapConfigError as exc:
        print(f"[map] {exc}", file=sys.stderr)
        return 1
    if sub == "file":
        return _cli_config_main_file(tail)
    print(f"[map] unknown 'main' key: {sub!r} (expected 'use-gpu', 'tps', or 'file')", file=sys.stderr)
    return 1


def _cli_config(rest: list[str]) -> int:
    if not rest or rest[0] in ("-h", "--help", "help"):
        print(_USAGE)
        return 0
    key, *tail = rest
    try:
        if key == "poly":
            if not tail:
                raise MapConfigError("usage: hnx map config poly <16|32|64|128>")
            val = set_poly(tail[0])
            print(f"[map] poly = {val}")
            return 0
        if key == "acc":
            if not tail:
                raise MapConfigError("usage: hnx map config acc <N|Nk|Nm|Nb|Nt>")
            val = set_acc(tail[0])
            print(f"[map] acc = {val}")
            return 0
    except MapConfigError as exc:
        print(f"[map] {exc}", file=sys.stderr)
        return 1
    if key == "main":
        return _cli_config_main(tail)
    print(f"[map] unknown config key: {key!r} (expected 'poly', 'acc', or 'main')", file=sys.stderr)
    return 1


def cli_main(argv: list[str] | None = None) -> int:
    """Entry point for ``hnx map`` / ``hypernix map``."""
    args = list(argv if argv is not None else sys.argv[1:])
    if args and args[0] in ("-h", "--help", "help"):
        print(_USAGE)
        return 0
    if args and args[0] == "config":
        return _cli_config(args[1:])
    if args:
        print(f"[map] Unknown argument: {args[0]!r}", file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        return 1

    app = HyperMap(_load_map_config())
    try:
        app.run()
    finally:
        sys.stdout.write("\x1b[2J\x1b[H")
        sys.stdout.flush()
    return 0


__all__ = [
    "Canvas",
    "HyperMap",
    "LayerNode",
    "MapConfigError",
    "ModelSnapshot",
    "PolyGlyphs",
    "build_snapshot",
    "cli_main",
    "dial_frac",
    "get_map_config",
    "glyphs_for_poly",
    "parse_acc",
    "render_dial",
    "render_engine",
    "render_pipe_segment",
    "set_acc",
    "set_file_mode",
    "set_poly",
    "set_tps",
    "set_use_gpu",
    "throttle_frac",
]
