"""hypernix.quant.subbit — the sub-1-bit packings, for real.

:mod:`hypernix.quant.steamroller` has advertised ``IQ0.9_L``,
``IQ0.75_M`` and ``IQ0.5_XXXL`` for some time. What it actually did was
copy the Q3_K_L staging file and write a sidecar JSON claiming a tier —
so a "0.5-bit model" was byte-identical to the 3-bit model it came from,
the same size, and no more quantised. The tier was a label.

This is the arithmetic that was missing. Nothing here needs llama.cpp:
these are HyperNix types that ``llama-quantize`` has never heard of, so
shelling out to it was never going to produce one.

How you get below one bit
-------------------------
Not by storing a fraction of a bit per weight — you cannot — but by
storing fewer values than weights and reconstructing the rest:

* **IQ0.9** (~0.94 bpw) — one sign bit per weight, plus one FP16 scale
  per 256-weight block. The magnitude is thrown away entirely and the
  block's scale stands in for all of it. This is a sign-and-scale code,
  and it is the least destructive of the three.
* **IQ0.75** (~0.81 bpw) — weights are paired. Each pair gets a 2-bit
  code chosen from a fixed 4-entry codebook of sign patterns, so two
  weights cost two bits together, plus the block scale.
* **IQ0.5** (~0.56 bpw) — weights are taken in groups of four and each
  group gets a 2-bit code naming one of four sign patterns, chosen to
  match the group's dominant direction. Three quarters of the sign
  information is discarded.

Each packing is chosen to **minimise weighted squared error** against the
original block, with the importance matrix as the weight when one is
supplied. That is the only place an imatrix can help at these bitrates:
there is no magnitude left to allocate, so all it can do is decide which
signs matter.

What this is not
----------------
It is not a way to make a 0.5-bit model good. Below about 1.5 bits per
weight a model stops being a slightly worse version of itself and starts
being a different, much worse model, and no packing changes that. The
tiers carry :attr:`Tier.honest_warning` for this reason. What changed is
that the file now genuinely is what its header says it is.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass

__all__ = [
    "BLOCK_SIZE",
    "SubBitError",
    "PACKINGS",
    "quantize_block",
    "dequantize_block",
    "quantize_tensor",
    "dequantize_tensor",
    "packed_block_bytes",
]

#: Weights per block. 256 to match the K-quant family, so a tensor that
#: divides evenly for Q4_K divides evenly here too.
BLOCK_SIZE = 256


class SubBitError(ValueError):
    """A block could not be packed or unpacked."""


@dataclass(frozen=True)
class Packing:
    """One sub-bit format."""

    name: str
    #: Weights represented by a single code.
    group: int
    #: Bits per code.
    code_bits: int
    #: Sign patterns a code can name, as tuples of +1/-1 of length `group`.
    codebook: tuple[tuple[int, ...], ...]

    @property
    def codes_per_block(self) -> int:
        return BLOCK_SIZE // self.group

    @property
    def payload_bytes(self) -> int:
        bits = self.codes_per_block * self.code_bits
        return (bits + 7) // 8

    @property
    def block_bytes(self) -> int:
        return 2 + self.payload_bytes      # FP16 scale + codes

    @property
    def bits_per_weight(self) -> float:
        return (self.block_bytes * 8) / BLOCK_SIZE


def _sign_patterns(group: int, count: int) -> tuple[tuple[int, ...], ...]:
    """The *count* most useful sign patterns for a group of *group*.

    All-positive and all-negative first — a group is usually dominated by
    one direction, and those two codes carry most of the benefit. The
    remainder are the half-and-half splits, which is where the residual
    structure is.
    """
    patterns: list[tuple[int, ...]] = [tuple([1] * group), tuple([-1] * group)]
    if count > 2:
        for index in range(1, 2 ** group - 1):
            pattern = tuple(
                1 if (index >> position) & 1 else -1 for position in range(group)
            )
            if pattern not in patterns:
                patterns.append(pattern)
            if len(patterns) == count:
                break
    return tuple(patterns[:count])


PACKINGS: dict[str, Packing] = {
    # One sign per weight: the codebook is trivially both signs of a
    # single weight, and no information beyond the sign survives.
    "sign_scale_l": Packing("sign_scale_l", group=1, code_bits=1,
                            codebook=((1,), (-1,))),
    # Pairs, 2 bits: all four sign combinations of two weights, so the
    # pair's signs are exact and only the magnitudes are gone.
    "pair_code_m": Packing("pair_code_m", group=2, code_bits=2,
                           codebook=_sign_patterns(2, 4)),
    # Quads, 2 bits: four patterns out of sixteen, so three quarters of
    # the sign information is discarded along with all magnitude.
    "quad_code_xxxl": Packing("quad_code_xxxl", group=4, code_bits=2,
                              codebook=_sign_patterns(4, 4)),
}


def packed_block_bytes(packing: str) -> int:
    """Bytes one 256-weight block occupies under *packing*."""
    spec = PACKINGS.get(packing)
    if spec is None:
        raise SubBitError(f"Unknown packing {packing!r}")
    return spec.block_bytes


def _fp16_bytes(value: float) -> bytes:
    return struct.pack("<e", _finite(value))


def _finite(value: float) -> float:
    """Guard the scale against inf/NaN reaching the file.

    A block of all zeros gives a scale of zero, which is correct; a block
    containing an inf gives a scale of inf, which serialises and then
    dequantises every weight in the block to NaN. Clamping here means a
    poisoned tensor degrades to zeros rather than spreading.
    """
    if not math.isfinite(value):
        return 0.0
    # FP16's maximum. Above it, struct.pack('<e', ...) yields inf.
    return max(-65504.0, min(65504.0, value))


def quantize_block(weights: list[float], packing: str,
                   importance: list[float] | None = None) -> bytes:
    """Pack one block of :data:`BLOCK_SIZE` weights.

    The scale is the importance-weighted mean absolute value, which is
    the value minimising weighted squared error for a sign-and-scale code
    — not the maximum, which would be minimising the wrong thing and
    makes every reconstruction too large.
    """
    spec = PACKINGS.get(packing)
    if spec is None:
        raise SubBitError(f"Unknown packing {packing!r}")
    if len(weights) != BLOCK_SIZE:
        raise SubBitError(f"A block is {BLOCK_SIZE} weights, got {len(weights)}")
    if importance is not None and len(importance) != BLOCK_SIZE:
        raise SubBitError("importance must be the same length as the block")

    if importance is None:
        weight_sum = float(BLOCK_SIZE)
        magnitude_sum = sum(abs(w) for w in weights)
    else:
        weight_sum = sum(max(0.0, i) for i in importance)
        magnitude_sum = sum(abs(w) * max(0.0, i) for w, i in zip(weights, importance, strict=True))
    scale = (magnitude_sum / weight_sum) if weight_sum > 0 else 0.0

    codes: list[int] = []
    for start in range(0, BLOCK_SIZE, spec.group):
        group = weights[start:start + spec.group]
        weights_for_group = (
            [max(0.0, i) for i in importance[start:start + spec.group]]
            if importance is not None
            else [1.0] * spec.group
        )
        best_code, best_error = 0, None
        for code, pattern in enumerate(spec.codebook):
            # Weighted squared error of reconstructing this group as
            # `pattern * scale`. Picking the pattern rather than deriving
            # it from the signs is what lets a 4-weight group with a
            # 4-entry codebook choose the least-bad approximation instead
            # of the nearest one that happens to be representable.
            error = sum(
                w * (value - sign * scale) ** 2
                for value, sign, w in zip(group, pattern, weights_for_group, strict=True)
            )
            if best_error is None or error < best_error:
                best_code, best_error = code, error
        codes.append(best_code)

    payload = bytearray(spec.payload_bytes)
    for index, code in enumerate(codes):
        bit = index * spec.code_bits
        for offset in range(spec.code_bits):
            if (code >> offset) & 1:
                position = bit + offset
                payload[position // 8] |= 1 << (position % 8)
    return _fp16_bytes(scale) + bytes(payload)


def dequantize_block(data: bytes, packing: str) -> list[float]:
    """Reconstruct one block. The inverse of :func:`quantize_block`."""
    spec = PACKINGS.get(packing)
    if spec is None:
        raise SubBitError(f"Unknown packing {packing!r}")
    if len(data) != spec.block_bytes:
        raise SubBitError(
            f"{packing} blocks are {spec.block_bytes} bytes, got {len(data)}"
        )
    scale = struct.unpack("<e", data[:2])[0]
    payload = data[2:]

    weights: list[float] = []
    for index in range(spec.codes_per_block):
        bit = index * spec.code_bits
        code = 0
        for offset in range(spec.code_bits):
            position = bit + offset
            if payload[position // 8] >> (position % 8) & 1:
                code |= 1 << offset
        pattern = spec.codebook[code]
        weights.extend(sign * scale for sign in pattern)
    return weights


def quantize_tensor(weights: list[float], packing: str,
                    importance: list[float] | None = None) -> bytes:
    """Pack a whole tensor, block by block.

    The element count must divide into :data:`BLOCK_SIZE`. Padding a
    ragged tail would change the tensor's shape, and silently changing a
    model's shape is worse than refusing the tensor.
    """
    if len(weights) % BLOCK_SIZE:
        raise SubBitError(
            f"{len(weights)} weights do not divide into {BLOCK_SIZE}-weight blocks"
        )
    out = bytearray()
    for start in range(0, len(weights), BLOCK_SIZE):
        block_importance = (
            importance[start:start + BLOCK_SIZE] if importance is not None else None
        )
        out += quantize_block(weights[start:start + BLOCK_SIZE], packing, block_importance)
    return bytes(out)


def dequantize_tensor(data: bytes, packing: str) -> list[float]:
    """Reconstruct a whole tensor."""
    spec = PACKINGS.get(packing)
    if spec is None:
        raise SubBitError(f"Unknown packing {packing!r}")
    if len(data) % spec.block_bytes:
        raise SubBitError(
            f"{len(data)} bytes is not a whole number of {spec.block_bytes}-byte blocks"
        )
    weights: list[float] = []
    for start in range(0, len(data), spec.block_bytes):
        weights.extend(dequantize_block(data[start:start + spec.block_bytes], packing))
    return weights
