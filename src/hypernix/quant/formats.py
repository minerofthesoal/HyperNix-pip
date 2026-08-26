"""hypernix.quant.formats — every quantisation format HyperNix knows about.

``quantize.py`` owns the GGUF types llama.cpp can produce. This module is
the wider registry: the weight formats that come from *other* toolchains
(bitsandbytes NF4/INT8, EXL2, AWQ, GPTQ) and the hardware numeric formats
(FP8, FP4) that a GPU either supports or does not.

One registry rather than four scattered lists, because the questions a
caller actually asks cut across families:

* "Can this GPU run this format?"  — :meth:`QuantFormat.supported_on`
* "How big will the weights be?"   — :meth:`QuantFormat.estimate_bytes`
* "What produces it?"              — :attr:`QuantFormat.toolchain`
* "Is it a training format or an inference format?" — :attr:`QuantFormat.stage`

That last one matters more than it looks. NF4 and INT8 are things you
*train* through (QLoRA, 8-bit optimisers); GGUF, EXL2, AWQ and GPTQ are
things you *ship*. Mixing them up produces the specific, common failure
of trying to fine-tune a GPTQ checkpoint and getting silence.

Hardware honesty
----------------
FP8 needs Hopper (sm_90) or Ada (sm_89); FP4 needs Blackwell (sm_100).
On a Pascal card these are not "slow", they are absent — there is no
instruction. :meth:`QuantFormat.supported_on` says so, and
:mod:`hypernix.system.pascal` uses it to keep the auto-tuner from
proposing a format the card cannot execute. A registry that claimed
otherwise would turn a clear "unsupported" into a CUDA error three hours
into a run.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "QuantFamily",
    "QuantStage",
    "QuantFormat",
    "FORMATS",
    "get_format",
    "list_formats",
    "formats_for",
    "SIX_BIT_MODES",
    "SixBitMode",
]


class QuantFamily(StrEnum):
    FLOAT = "float"          # fp32/bf16/fp16/fp8/fp4 — hardware numeric formats
    INT = "int"              # int8/int4 — integer quantisation
    NF = "nf"                # NormalFloat (bitsandbytes)
    GGUF = "gguf"            # llama.cpp k-quants and IQ quants
    EXL2 = "exl2"            # ExLlamaV2 mixed-bitrate
    AWQ = "awq"              # activation-aware weight quantisation
    GPTQ = "gptq"            # GPTQ / OPTQ


class QuantStage(StrEnum):
    """What the format is *for*. See the module docstring."""

    TRAIN = "train"          # you can backprop through it (QLoRA, 8-bit optim)
    INFERENCE = "inference"  # ship-only; fine-tuning needs a de-quant first
    BOTH = "both"


@dataclass(frozen=True)
class QuantFormat:
    """One quantisation format, and what is true about it."""

    name: str
    family: QuantFamily
    bits_per_weight: float
    stage: QuantStage
    toolchain: str
    summary: str
    #: Minimum CUDA compute capability, as ``(major, minor)``. ``None``
    #: means "no hardware requirement beyond running at all" — the format
    #: is software-defined and works anywhere, including CPU.
    min_compute: tuple[int, int] | None = None
    #: Extra bits per weight for group scales/zeros. Real, and the reason
    #: a "4-bit" model is never 0.5 bytes per parameter.
    overhead_bits: float = 0.0
    aliases: tuple[str, ...] = ()
    notes: str = ""

    @property
    def effective_bits(self) -> float:
        """Bits per weight including scale/zero overhead."""
        return self.bits_per_weight + self.overhead_bits

    def estimate_bytes(self, parameters: int) -> int:
        """Weight bytes for a model of *parameters* parameters.

        Weights only — no KV cache, no activations, no optimiser state.
        Callers sizing a GPU need all four; this is the one this registry
        can answer honestly.
        """
        if parameters < 0:
            raise ValueError(f"parameters must be >= 0, got {parameters}")
        return int(parameters * self.effective_bits / 8)

    def supported_on(self, compute_capability: tuple[int, int] | None) -> tuple[bool, str]:
        """``(ok, reason)`` for a GPU at *compute_capability*.

        ``None`` means CPU or unknown hardware, which is fine for every
        software-defined format and not fine for the ones that compile to
        a specific instruction.
        """
        if self.min_compute is None:
            return True, ""
        if compute_capability is None:
            return False, (
                f"{self.name} needs a CUDA GPU of compute capability "
                f"{self.min_compute[0]}.{self.min_compute[1]} or newer; no GPU was detected"
            )
        if compute_capability >= self.min_compute:
            return True, ""
        return False, (
            f"{self.name} needs compute capability {self.min_compute[0]}.{self.min_compute[1]}+, "
            f"this GPU is {compute_capability[0]}.{compute_capability[1]}. "
            "This is a missing instruction, not a slow path."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "family": self.family.value,
            "bits_per_weight": self.bits_per_weight,
            "effective_bits": self.effective_bits,
            "stage": self.stage.value,
            "toolchain": self.toolchain,
            "summary": self.summary,
            "min_compute": (
                f"{self.min_compute[0]}.{self.min_compute[1]}" if self.min_compute else None
            ),
            "aliases": list(self.aliases),
            "notes": self.notes,
        }


def _f(*args: Any, **kwargs: Any) -> QuantFormat:
    return QuantFormat(*args, **kwargs)


#: The registry. Ordered widest-to-narrowest within each family so that
#: listings read as a ladder rather than as an alphabet.
FORMATS: dict[str, QuantFormat] = {
    fmt.name: fmt
    for fmt in (
        # --- hardware float formats -------------------------------------
        _f("FP32", QuantFamily.FLOAT, 32.0, QuantStage.BOTH, "torch",
           "Full precision. The reference every other format is measured against.",
           aliases=("float32", "f32", "fp32")),
        _f("BF16", QuantFamily.FLOAT, 16.0, QuantStage.BOTH, "torch",
           "Brain float. FP32's exponent range at half the width — the safe default "
           "for training on Ampere and newer.",
           min_compute=(8, 0), aliases=("bfloat16", "bf16"),
           notes="Pre-Ampere cards emulate this in software; use FP16 there instead."),
        _f("FP16", QuantFamily.FLOAT, 16.0, QuantStage.BOTH, "torch",
           "Half precision. Fast everywhere since Pascal, but its narrow exponent "
           "range is the usual source of training NaNs.",
           min_compute=(5, 3), aliases=("float16", "f16", "half"),
           notes="See hypernix.system.pascal for the FP16 overflow guard on sm_61."),
        _f("FP8", QuantFamily.FLOAT, 8.0, QuantStage.BOTH, "transformer-engine",
           "8-bit float (E4M3/E5M2). Real throughput gains, real dynamic-range care.",
           min_compute=(8, 9), aliases=("float8", "f8", "e4m3", "e5m2"),
           notes="Ada (sm_89) and Hopper (sm_90) only. Absent on older silicon."),
        _f("FP4", QuantFamily.FLOAT, 4.0, QuantStage.INFERENCE, "transformer-engine",
           "4-bit float. Blackwell-class hardware; the narrowest native float.",
           min_compute=(10, 0), aliases=("float4", "f4", "nvfp4"),
           notes="Blackwell (sm_100) and newer."),
        # --- integer / NF -----------------------------------------------
        _f("INT8", QuantFamily.INT, 8.0, QuantStage.BOTH, "bitsandbytes",
           "8-bit integer with per-channel scales. LLM.int8() keeps outlier "
           "channels in FP16, which is why quality holds up.",
           overhead_bits=0.25, aliases=("int8", "i8", "llm.int8"),
           notes="Works on Pascal; the int8 tensor-core path needs sm_75+."),
        _f("NF4", QuantFamily.NF, 4.0, QuantStage.TRAIN, "bitsandbytes",
           "4-bit NormalFloat. Information-theoretically optimal for "
           "normally-distributed weights, which is what QLoRA fine-tunes through.",
           overhead_bits=0.5, aliases=("nf4", "qlora"),
           notes="Double quantisation drops the overhead to ~0.13 bits/weight."),
        _f("INT4", QuantFamily.INT, 4.0, QuantStage.INFERENCE, "bitsandbytes",
           "Plain 4-bit integer. NF4 beats it on the same budget for LLM weights.",
           overhead_bits=0.5, aliases=("int4", "i4", "fp4-bnb")),
        # --- GGUF --------------------------------------------------------
        _f("Q8_0", QuantFamily.GGUF, 8.0, QuantStage.INFERENCE, "llama.cpp",
           "8-bit GGUF. Effectively lossless; the honest baseline for GGUF quality.",
           overhead_bits=0.5, aliases=("q8_0", "q8")),
        _f("Q6_K", QuantFamily.GGUF, 6.0, QuantStage.INFERENCE, "llama.cpp",
           "6-bit k-quant. The last tier where quality loss is hard to measure.",
           overhead_bits=0.56, aliases=("q6_k", "q6k")),
        _f("Q5_K_M", QuantFamily.GGUF, 5.0, QuantStage.INFERENCE, "llama.cpp",
           "5-bit k-quant, medium. A good stop when Q4_K_M feels thin.",
           overhead_bits=0.67, aliases=("q5_k_m", "q5km")),
        _f("Q4_K_M", QuantFamily.GGUF, 4.0, QuantStage.INFERENCE, "llama.cpp",
           "4-bit k-quant, medium. The default nearly everyone should use.",
           overhead_bits=0.83, aliases=("q4_k_m", "q4km")),
        _f("Q3_K_L", QuantFamily.GGUF, 3.0, QuantStage.INFERENCE, "llama.cpp",
           "3-bit k-quant, large. Steamroller's staging tier on the way down.",
           overhead_bits=0.44, aliases=("q3_k_l", "q3kl", "q3l")),
        _f("IQ4_XS", QuantFamily.GGUF, 4.25, QuantStage.INFERENCE, "llama.cpp",
           "4-bit IQ, extra small. Better than Q4_K_M per byte, slower to run.",
           aliases=("iq4_xs",)),
        _f("IQ2_M", QuantFamily.GGUF, 2.7, QuantStage.INFERENCE, "llama.cpp",
           "2-bit IQ, medium. Needs an importance matrix to be worth anything.",
           aliases=("iq2_m",)),
        _f("IQ1_M", QuantFamily.GGUF, 1.75, QuantStage.INFERENCE, "llama.cpp",
           "1-bit IQ, medium. The narrowest upstream llama.cpp tier.",
           aliases=("iq1_m",),
           notes="Below ~2 bits an imatrix is not optional; without one output degrades sharply."),
        # --- other toolchains --------------------------------------------
        _f("EXL2", QuantFamily.EXL2, 4.0, QuantStage.INFERENCE, "exllamav2",
           "Mixed bitrate per layer, targeting an average. Fastest GPU inference "
           "at a given size; GPU-only, no CPU offload.",
           min_compute=(7, 5), aliases=("exl2",),
           notes="bits_per_weight is the requested average and is set per build (2.0-8.0)."),
        _f("AWQ", QuantFamily.AWQ, 4.0, QuantStage.INFERENCE, "autoawq",
           "Activation-aware. Protects the ~1% of channels that carry the "
           "outliers, then quantises the rest hard.",
           min_compute=(7, 5), overhead_bits=0.25, aliases=("awq",)),
        _f("GPTQ", QuantFamily.GPTQ, 4.0, QuantStage.INFERENCE, "gptqmodel",
           "One-shot second-order weight rounding. The oldest of the "
           "calibration-based 4-bit methods and still competitive.",
           min_compute=(6, 1), overhead_bits=0.25, aliases=("gptq",),
           notes="Runs on Pascal (sm_61) — one of the few 4-bit paths that does."),
    )
}

#: alias -> canonical name. Built once; lookups are exact.
_ALIASES: dict[str, str] = {}
for _fmt in FORMATS.values():
    _ALIASES[_fmt.name.lower()] = _fmt.name
    for _alias in _fmt.aliases:
        _ALIASES[_alias.lower()] = _fmt.name


def get_format(name: str) -> QuantFormat:
    """Look up a format by name or alias, case-insensitively."""
    key = (name or "").strip().lower()
    canonical = _ALIASES.get(key)
    if canonical is None:
        raise KeyError(
            f"Unknown quantisation format {name!r}. Known: {', '.join(sorted(FORMATS))}"
        )
    return FORMATS[canonical]


def list_formats(
    *,
    family: QuantFamily | str | None = None,
    stage: QuantStage | str | None = None,
    compute_capability: tuple[int, int] | None = None,
) -> list[QuantFormat]:
    """Every format matching the filters, in registry order.

    ``compute_capability`` filters to what the GPU can actually execute —
    the filter the auto-tuner uses so it never offers FP8 on a Pascal card.
    """
    out = list(FORMATS.values())
    if family is not None:
        want = QuantFamily(family)
        out = [f for f in out if f.family is want]
    if stage is not None:
        want_stage = QuantStage(stage)
        out = [
            f for f in out
            if f.stage is want_stage or f.stage is QuantStage.BOTH or want_stage is QuantStage.BOTH
        ]
    if compute_capability is not None:
        out = [f for f in out if f.supported_on(compute_capability)[0]]
    return out


def formats_for(toolchain: str) -> list[QuantFormat]:
    return [f for f in FORMATS.values() if f.toolchain == toolchain]


# ---------------------------------------------------------------------------
# Custom 6-bit modes (Pressure Cooker v5 / v5+ / v5s / v6)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SixBitMode:
    """A 6-bit packing scheme for optimiser state.

    Pressure Cooker already quantises its momentum buffer to int8. Six
    bits is the next rung down and the interesting one: it is not a
    machine word, so the packing choice — how the six-bit lanes are laid
    out across bytes — decides whether the pack/unpack cost eats the
    memory saving.

    Three schemes, and the trade is the same each time: tighter packing
    means less memory and more shift work per element.
    """

    name: str
    #: Values packed per group, and bytes used for that group.
    values_per_group: int
    bytes_per_group: int
    scale_bits: int
    summary: str
    symmetric: bool = True

    @property
    def bits_per_value(self) -> float:
        return self.bytes_per_group * 8 / self.values_per_group

    @property
    def bytes_per_value(self) -> float:
        return self.bytes_per_group / self.values_per_group

    def group_bytes(self, count: int) -> int:
        """Bytes needed to store *count* values, including partial groups."""
        groups = -(-count // self.values_per_group)      # ceil division
        return groups * self.bytes_per_group + groups * (self.scale_bits // 8)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "values_per_group": self.values_per_group,
            "bytes_per_group": self.bytes_per_group,
            "bits_per_value": self.bits_per_value,
            "scale_bits": self.scale_bits,
            "symmetric": self.symmetric,
            "summary": self.summary,
        }


#: The three 6-bit modes v5/v5+/v5s/v6 accept for their momentum buffers.
SIX_BIT_MODES: dict[str, SixBitMode] = {
    mode.name: mode
    for mode in (
        SixBitMode(
            "packed", values_per_group=4, bytes_per_group=3, scale_bits=16,
            summary=(
                "Four 6-bit values in three bytes — exactly 6.0 bits each, no waste. "
                "The tightest option and the most shift work per element."
            ),
        ),
        SixBitMode(
            "aligned", values_per_group=1, bytes_per_group=1, scale_bits=16,
            summary=(
                "One value per byte with the top two bits unused. Wastes 25% of the "
                "space to make unpacking a single mask — the right default when the "
                "optimiser step is compute-bound rather than memory-bound."
            ),
        ),
        SixBitMode(
            "hybrid", values_per_group=16, bytes_per_group=12, scale_bits=32,
            summary=(
                "Packed lanes in 16-value groups with a wider per-group scale. Same "
                "6.0 bits as 'packed' but amortises the scale over four times as many "
                "values, which matters for the row/column factors rather than the "
                "elementwise buffers."
            ),
            symmetric=False,
        ),
    )
}
