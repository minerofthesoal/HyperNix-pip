"""optimizers.sixbit — 6-bit packing for Pressure Cooker momentum buffers.

Pressure Cooker already stores its momentum in int8. Six bits is the next
rung down, and it is the interesting one because six is not a machine
word: how the lanes are laid out across bytes decides whether the
pack/unpack cost eats the memory saving.

Three modes, from :data:`hypernix.quant.formats.SIX_BIT_MODES`:

===========  ==================  =============================================
``packed``   4 values / 3 bytes  Exactly 6.0 bits. Tightest, most shift work.
``aligned``  1 value / 1 byte    Wastes 25%, unpacks with a single mask.
``hybrid``   16 values / 12 B    6.0 bits with the scale amortised 4x wider.
===========  ==================  =============================================

``aligned`` is the right default on Pascal and the wrong one on a modern
card, which is exactly the sort of thing
:func:`hypernix.system.pascal.autotune` exists to decide.

The quantisation itself
-----------------------
Symmetric, per-group, absmax-scaled to the signed range [-31, 31]. Not
[-32, 31]: using the asymmetric low end of two's complement for a
symmetric quantiser makes zero un-representable at one end of the range,
and momentum spends most of its life near zero.

Everything here works on plain Python sequences as well as tensors, so
the round-trip properties are testable without torch — which matters,
because the failure mode of a wrong packing is a run that trains slightly
worse, and that is not something a smoke test catches.
"""
from __future__ import annotations

import math

__all__ = [
    "SIX_BIT_LEVELS",
    "pack",
    "unpack",
    "quantize_group",
    "dequantize_group",
    "estimate_bytes",
    "bits_per_value",
    "resolve_mode",
    "roundtrip",
    "DEFAULT_SCALE_GROUP",
]

#: Signed levels used. See the module docstring for why not -32.
SIX_BIT_MAX = 31
SIX_BIT_LEVELS = 63          # -31 … +31

_MODES = {
    "packed": (4, 3),
    "aligned": (1, 1),
    "hybrid": (16, 12),
}


def resolve_mode(mode: str) -> tuple[int, int]:
    """``(values_per_group, bytes_per_group)`` for a mode name."""
    key = (mode or "").strip().lower()
    if key not in _MODES:
        raise ValueError(
            f"Unknown 6-bit mode {mode!r}. Available: {', '.join(sorted(_MODES))}"
        )
    return _MODES[key]


def quantize_group(values: list[float]) -> tuple[list[int], float]:
    """Symmetric absmax quantisation of one group to 6-bit codes.

    Returns ``(codes, scale)`` where ``codes`` are in [-31, 31]. An
    all-zero group gets a scale of 1.0 rather than 0: dividing by the
    scale on the way back out must not produce NaN, and a group of zeros
    is common early in training.
    """
    absmax = max((abs(v) for v in values), default=0.0)
    if absmax == 0.0 or not math.isfinite(absmax):
        return [0] * len(values), 1.0
    scale = absmax / SIX_BIT_MAX
    codes = []
    for value in values:
        code = int(round(value / scale))
        codes.append(max(-SIX_BIT_MAX, min(SIX_BIT_MAX, code)))
    return codes, scale


def dequantize_group(codes: list[int], scale: float) -> list[float]:
    return [code * scale for code in codes]


def pack(codes: list[int], mode: str = "packed") -> bytes:
    """Pack signed 6-bit codes into bytes.

    Codes are biased by +31 into [0, 62] before packing, so the packed
    representation is unsigned and the shifts do not have to worry about
    sign extension — which is where a hand-rolled bit packer usually goes
    wrong.
    """
    per_group, bytes_per_group = resolve_mode(mode)
    biased = [max(0, min(SIX_BIT_LEVELS - 1, code + SIX_BIT_MAX)) for code in codes]

    if mode == "aligned":
        return bytes(biased)

    out = bytearray()
    for start in range(0, len(biased), per_group):
        group = biased[start : start + per_group]
        group += [SIX_BIT_MAX] * (per_group - len(group))     # pad with zero-valued codes
        # Four 6-bit values into three bytes, then repeated for hybrid's
        # sixteen. Little-endian lane order within each triple.
        for offset in range(0, per_group, 4):
            a, b, c, d = group[offset : offset + 4]
            out.append(a | ((b & 0x03) << 6))
            out.append((b >> 2) | ((c & 0x0F) << 4))
            out.append((c >> 4) | (d << 2))
    expected = (len(biased) + per_group - 1) // per_group * bytes_per_group
    if len(out) != expected:  # pragma: no cover - guards the arithmetic above
        raise RuntimeError(f"packed {len(out)} bytes, expected {expected}")
    return bytes(out)


def unpack(data: bytes, count: int, mode: str = "packed") -> list[int]:
    """Inverse of :func:`pack`. Returns *count* signed codes."""
    per_group, _ = resolve_mode(mode)
    if mode == "aligned":
        return [b - SIX_BIT_MAX for b in data[:count]]

    codes: list[int] = []
    for index in range(0, len(data), 3):
        chunk = data[index : index + 3]
        if len(chunk) < 3:
            break
        first, second, third = chunk
        codes.append(first & 0x3F)
        codes.append(((first >> 6) | ((second & 0x0F) << 2)) & 0x3F)
        codes.append(((second >> 4) | ((third & 0x03) << 4)) & 0x3F)
        codes.append((third >> 2) & 0x3F)
    return [code - SIX_BIT_MAX for code in codes[:count]]


#: Values sharing one absmax scale. Independent of the packing layout,
#: which is a separate concern: an earlier version tied them together and
#: made "aligned" cost 24 bits per value (8 packed + a 16-bit scale for
#: every single value), which is worse than the int8 it replaces. The
#: scale group is what k-quants call a block, and 32 is the size llama.cpp
#: settled on for the same reason — small enough to track local dynamic
#: range, large enough that the scale is nearly free.
DEFAULT_SCALE_GROUP = 32


def estimate_bytes(
    count: int,
    mode: str = "packed",
    *,
    scale_bits: int = 16,
    scale_group: int = DEFAULT_SCALE_GROUP,
) -> int:
    """Bytes for *count* values, including the per-block scale."""
    per_group, bytes_per_group = resolve_mode(mode)
    packing_groups = (count + per_group - 1) // per_group
    scale_groups = (count + scale_group - 1) // scale_group
    return packing_groups * bytes_per_group + scale_groups * (scale_bits // 8)


def bits_per_value(mode: str = "packed", *, scale_group: int = DEFAULT_SCALE_GROUP) -> float:
    """Effective bits per value at a realistic block size."""
    return estimate_bytes(4096, mode, scale_group=scale_group) * 8 / 4096


def roundtrip(
    values: list[float],
    mode: str = "packed",
    *,
    scale_group: int = DEFAULT_SCALE_GROUP,
) -> list[float]:
    """Quantise, pack, unpack, dequantise. The test path, and a demo.

    Scales are shared across ``scale_group`` values, independent of the
    packing layout — so ``aligned`` is not artificially exact by virtue
    of giving every value its own scale.
    """
    out: list[float] = []
    for start in range(0, len(values), scale_group):
        block = values[start : start + scale_group]
        codes, scale = quantize_group(block)
        restored = unpack(pack(codes, mode), len(block), mode)
        out.extend(dequantize_group(restored, scale))
    return out
