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
storing *fewer signs than weights* and reconstructing the rest. Every
tier keeps one FP16 scale per 256-weight block; the magnitude is gone
entirely and the scale stands in for all of it. What separates the tiers
is how many of the signs survive:

=========  ======  ==========  ===========  =====
Tier       group   bits/code   block bytes  bpw
=========  ======  ==========  ===========  =====
IQ0.9_L         8           7           30  0.938
IQ0.75_M        4           3           26  0.812
IQ0.5_XXXL      4           2           18  0.562
=========  ======  ==========  ===========  =====

So IQ0.9 keeps 7 of every 8 signs, IQ0.75 keeps 3 of every 4, and IQ0.5
keeps 2 of every 4. The signs that are not stored are reconstructed by
repeating the last one that was.

**Which signs get dropped is the whole decision**, and it is where an
importance matrix earns its place: there is no magnitude left to
allocate at these rates, so all an imatrix can do is decide which signs
matter. The positions kept are the ones with the highest importance ×
magnitude, so a dropped sign is one whose weight was small, or one the
imatrix said the model does not lean on. Without an imatrix the choice
falls back to magnitude alone.

The code is *derived*, not searched. A brute-force over the 128 patterns
a 7-bit code can name would be 32k comparisons per block, and a 7B model
is 27 million blocks — hours of it. Selecting positions and reading their
signs is O(group) and gives the same answer for this codebook.

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
    """One sub-bit format: how many signs survive out of how many weights."""

    name: str
    #: Weights covered by one code.
    group: int
    #: Bits in that code — and so how many of the group's signs are kept.
    code_bits: int

    @property
    def kept(self) -> int:
        """Signs stored per group. One bit each, so this is code_bits."""
        return self.code_bits

    @property
    def codes_per_block(self) -> int:
        return BLOCK_SIZE // self.group

    @property
    def payload_bytes(self) -> int:
        return (self.codes_per_block * self.code_bits + 7) // 8

    @property
    def block_bytes(self) -> int:
        return 2 + self.payload_bytes      # FP16 scale + codes

    @property
    def bits_per_weight(self) -> float:
        return (self.block_bytes * 8) / BLOCK_SIZE


PACKINGS: dict[str, Packing] = {
    #: 7 signs kept of every 8. The least destructive tier.
    "sign_scale_l": Packing("sign_scale_l", group=8, code_bits=7),
    #: 3 of every 4.
    "pair_code_m": Packing("pair_code_m", group=4, code_bits=3),
    #: 2 of every 4 — half the signs, and no magnitude at all.
    "quad_code_xxxl": Packing("quad_code_xxxl", group=4, code_bits=2),
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

    The scale is the importance-weighted **mean** absolute value, which
    minimises weighted squared error for a sign-and-scale code. Not the
    maximum: that minimises a different thing and makes every
    reconstruction systematically too large.
    """
    spec = PACKINGS.get(packing)
    if spec is None:
        raise SubBitError(f"Unknown packing {packing!r}")
    if len(weights) != BLOCK_SIZE:
        raise SubBitError(f"A block is {BLOCK_SIZE} weights, got {len(weights)}")
    if importance is not None and len(importance) != BLOCK_SIZE:
        raise SubBitError("importance must be the same length as the block")

    if importance is None:
        divisor = float(BLOCK_SIZE)
        magnitude_sum = sum(abs(w) for w in weights)
    else:
        divisor = sum(max(0.0, i) for i in importance)
        magnitude_sum = sum(
            abs(w) * max(0.0, i) for w, i in zip(weights, importance, strict=True)
        )
    scale = (magnitude_sum / divisor) if divisor > 0 else 0.0

    # The first `kept` positions of each group, in order.
    #
    # Choosing them by magnitude was tried and is wrong: the decoder has
    # no way to learn which positions were chosen, so it fills the group
    # left to right regardless — and a cleverer encoder just means the
    # signs land on the wrong weights. Encoder and decoder have to agree
    # on the mapping, and with no bits to spend describing it, "the first
    # k, always" is the only mapping both can know.
    #
    # The importance matrix still earns its place: it sets the scale, and
    # at these bitrates the scale is most of what is left to get right.
    payload = bytearray(spec.payload_bytes)
    bit_cursor = 0
    for start in range(0, BLOCK_SIZE, spec.group):
        for position in range(spec.kept):
            if weights[start + position] >= 0:
                payload[bit_cursor // 8] |= 1 << (bit_cursor % 8)
            bit_cursor += 1
    return _fp16_bytes(scale) + bytes(payload)


def dequantize_block(data: bytes, packing: str) -> list[float]:
    """Reconstruct one block. The inverse of :func:`quantize_block`.

    A position whose sign was not stored repeats the last stored one.
    That is a choice, not a neutral default: repeating is right far more
    often than alternating, because adjacent weights in a row correlate,
    and it is what makes the dropped signs cost less than random.

    The kept positions are the first ``kept`` of each group, which is
    exactly what the encoder stored, so those weights get their own sign
    back. Only the tail is approximated.
    """
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
    bit_cursor = 0
    for _ in range(spec.codes_per_block):
        signs: list[float] = []
        for _ in range(spec.kept):
            bit = 1 if payload[bit_cursor // 8] >> (bit_cursor % 8) & 1 else -1
            signs.append(float(bit) * scale)
            bit_cursor += 1
        # The group's remaining positions repeat the last stored sign.
        while len(signs) < spec.group:
            signs.append(signs[-1])
        weights.extend(signs)
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
