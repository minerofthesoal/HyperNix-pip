"""hypernix.quant.hyprslug — quantise a GGUF without llama.cpp.

Also answers to **doomslug**, **doomslugthedestroyer** and **dstd**.

Everything that quantised in this package used to shell out to
``llama-quantize``. That has two problems. The small one is that a
machine which has not built llama.cpp cannot quantise at all. The large
one is that the sub-bit tiers — ``IQ0.9_L``, ``IQ0.75_M``,
``IQ0.5_XXXL`` — are HyperNix types that ``llama-quantize`` has never
heard of, so for those it was never going to be the answer, and what
:mod:`hypernix.quant.steamroller` actually did was copy the staging file
and write a sidecar claiming a tier it had not applied.

hyprslug is the quantiser those tiers needed. It reads a GGUF with
:mod:`hypernix.quant.gguf`, packs each eligible tensor with
:mod:`hypernix.quant.subbit`, and writes a real GGUF whose tensors are
genuinely at the advertised bitrate. No binary, no build, no llama.cpp
on the machine at any point.

What it will and will not touch
-------------------------------
Not every tensor should be crushed. Normalisation weights, biases and
anything one-dimensional are a rounding error of the file size and a
large fraction of the damage, so they are copied at source precision —
the same call every serious quantiser makes, for the same reason.
Token embeddings and the output head are configurable because the right
answer depends on the model: on a small model they dominate the file, on
a large one they do not.

Honesty
-------
A tensor whose element count does not divide into 256 cannot be packed
and is copied instead, and the result says how many were copied. A run
that quietly left half a model at F16 while reporting "IQ0.5" would be
the same failure this module exists to fix.
"""
from __future__ import annotations

import logging
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .gguf import GGMLType, GGUFError, GGUFFile, GGUFTensor, GGUFWriter
from .subbit import BLOCK_SIZE, PACKINGS, SubBitError, quantize_tensor

logger = logging.getLogger(__name__)

__all__ = [
    "HyprslugError",
    "TIER_TYPES",
    "QuantizeReport",
    "quantize_gguf",
    "tier_for_packing",
    "ALIASES",
]

#: The names this tool answers to. doomslug is the original; the longer
#: forms are kept because people type them.
ALIASES = ("hyprslug", "doomslug", "doomslugthedestroyer", "dstd")


class HyprslugError(Exception):
    """Quantisation could not proceed."""


#: Steamroller tier -> (GGML type id, subbit packing name).
TIER_TYPES: dict[str, tuple[int, str]] = {
    "IQ0.9_L": (int(GGMLType.HNX_IQ0_9), "sign_scale_l"),
    "IQ0.75_M": (int(GGMLType.HNX_IQ0_75), "pair_code_m"),
    "IQ0.5_XXXL": (int(GGMLType.HNX_IQ0_5), "quad_code_xxxl"),
}

#: Source types this can read element-wise. A quantised source would need
#: a decoder per K-quant format; refusing is better than half-supporting.
_READABLE = {
    int(GGMLType.F32): ("<f", 4),
    int(GGMLType.F16): ("<e", 2),
    int(GGMLType.BF16): (None, 2),
}


def tier_for_packing(packing: str) -> str:
    """The tier name a packing belongs to."""
    for tier, (_, name) in TIER_TYPES.items():
        if name == packing:
            return tier
    raise HyprslugError(f"No tier uses packing {packing!r}")


def _decode_floats(data: bytes, ggml_type: int) -> list[float]:
    """Tensor bytes to a list of floats."""
    spec = _READABLE.get(int(ggml_type))
    if spec is None:
        raise HyprslugError(
            f"hyprslug reads F32, F16 and BF16 sources; this tensor is type "
            f"{ggml_type}. Quantise from the unquantised model, not from an "
            f"already-quantised one."
        )
    fmt, width = spec
    count = len(data) // width
    if fmt is None:
        # BF16 is the top 16 bits of an F32, so widening is a shift, not
        # a conversion — and unlike F16 it cannot overflow doing it.
        return [
            struct.unpack("<f", b"\x00\x00" + data[i * 2:i * 2 + 2])[0]
            for i in range(count)
        ]
    return list(struct.unpack(f"<{count}{fmt[1]}", data[: count * width]))


def _should_quantize(
    tensor: GGUFTensor,
    *,
    quantize_embeddings: bool,
    quantize_output: bool,
) -> tuple[bool, str]:
    """Whether to pack *tensor*, and why not when not."""
    if len(tensor.shape) < 2:
        return False, "1-D (norm or bias): all of the damage, none of the size"
    if int(tensor.ggml_type) not in _READABLE:
        return False, f"source type {tensor.ggml_type} is already quantised"
    if tensor.elements % BLOCK_SIZE:
        return False, f"{tensor.elements} elements do not divide into {BLOCK_SIZE}"
    name = tensor.name.lower()
    if not quantize_embeddings and ("token_embd" in name or "tok_embeddings" in name):
        return False, "token embeddings (pass quantize_embeddings=True to include)"
    if not quantize_output and (name.startswith("output.") or name == "output.weight"):
        return False, "output head (pass quantize_output=True to include)"
    return True, ""


@dataclass
class QuantizeReport:
    """What a run actually did — including what it declined to do."""

    tier: str = ""
    packing: str = ""
    source_bytes: int = 0
    output_bytes: int = 0
    tensors_total: int = 0
    tensors_quantized: int = 0
    tensors_copied: int = 0
    elements_quantized: int = 0
    elements_copied: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def compression(self) -> float:
        return (self.source_bytes / self.output_bytes) if self.output_bytes else 0.0

    @property
    def quantized_fraction(self) -> float:
        total = self.elements_quantized + self.elements_copied
        return (self.elements_quantized / total) if total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "packing": self.packing,
            "source_bytes": self.source_bytes,
            "output_bytes": self.output_bytes,
            "compression": round(self.compression, 3),
            "tensors_total": self.tensors_total,
            "tensors_quantized": self.tensors_quantized,
            "tensors_copied": self.tensors_copied,
            "quantized_fraction": round(self.quantized_fraction, 4),
            "skipped": [{"tensor": n, "reason": r} for n, r in self.skipped],
            "seconds": round(self.seconds, 2),
        }

    def describe(self) -> str:
        lines = [
            f"{self.tier}  ({self.packing})",
            f"  {self.source_bytes / 1e6:.1f} MB -> {self.output_bytes / 1e6:.1f} MB "
            f"({self.compression:.1f}x)",
            f"  {self.tensors_quantized}/{self.tensors_total} tensors packed, "
            f"{self.quantized_fraction * 100:.1f}% of weights",
        ]
        if self.tensors_copied:
            lines.append(f"  {self.tensors_copied} copied at source precision:")
            for name, reason in self.skipped[:5]:
                lines.append(f"    {name}: {reason}")
            if len(self.skipped) > 5:
                lines.append(f"    ... and {len(self.skipped) - 5} more")
        return "\n".join(lines)


def load_imatrix(path: str | Path) -> dict[str, list[float]]:
    """Read an importance matrix, keyed by tensor name.

    Accepts the simple JSON shape ``{"tensor.name": [floats]}``. The
    llama.cpp binary imatrix format is not read here; converting it is a
    separate concern and pretending to support it would mean silently
    ignoring one.
    """
    import json

    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HyprslugError(f"Could not read imatrix {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise HyprslugError(f"{path} is not a mapping of tensor name to weights.")
    return {str(k): [float(x) for x in v] for k, v in raw.items()}


def quantize_gguf(
    source: str | Path,
    destination: str | Path,
    tier: str,
    *,
    imatrix: str | Path | dict[str, list[float]] | None = None,
    quantize_embeddings: bool = False,
    quantize_output: bool = False,
    progress: Callable[[dict], None] | None = None,
) -> QuantizeReport:
    """Quantise *source* to *tier*, writing *destination*.

    Returns a :class:`QuantizeReport` describing what was packed and what
    was not. Nothing here invokes llama.cpp.
    """
    source_path = Path(source)
    destination_path = Path(destination)
    if tier not in TIER_TYPES:
        raise HyprslugError(
            f"Unknown tier {tier!r}. hyprslug packs: {', '.join(TIER_TYPES)}"
        )
    ggml_type, packing = TIER_TYPES[tier]
    if packing not in PACKINGS:
        raise HyprslugError(f"Tier {tier} names packing {packing!r}, which does not exist.")
    if not source_path.exists():
        raise HyprslugError(f"No such model: {source_path}")

    weights_by_tensor: dict[str, list[float]] = {}
    if isinstance(imatrix, dict):
        weights_by_tensor = imatrix
    elif imatrix is not None:
        weights_by_tensor = load_imatrix(imatrix)

    started = time.time()
    try:
        model = GGUFFile.read(source_path)
    except GGUFError as exc:
        raise HyprslugError(f"{source_path}: {exc}") from exc

    report = QuantizeReport(
        tier=tier,
        packing=packing,
        source_bytes=source_path.stat().st_size,
        tensors_total=len(model.tensors),
    )

    writer = GGUFWriter(destination_path, alignment=model.alignment)
    writer.copy_metadata_from(model)
    # Recorded in the file itself, not a sidecar. A sidecar can be lost in
    # a copy, and then nothing about the model says what was done to it.
    writer.set_metadata("hypernix.quantiser", "hyprslug")
    writer.set_metadata("hypernix.tier", tier)
    writer.set_metadata("hypernix.packing", packing)
    writer.set_metadata("hypernix.sub_bit", True)
    writer.set_metadata("hypernix.imatrix", bool(weights_by_tensor))
    writer.set_metadata(
        "general.file_type_description",
        f"HyperNix {tier} ({PACKINGS[packing].bits_per_weight:.3f} bpw)",
    )

    plan: list[tuple[GGUFTensor, GGUFTensor, bool]] = []
    for tensor in model.tensors:
        do_it, reason = _should_quantize(
            tensor,
            quantize_embeddings=quantize_embeddings,
            quantize_output=quantize_output,
        )
        target_type = ggml_type if do_it else tensor.ggml_type
        declared = writer.add_tensor(tensor.name, tensor.shape, target_type)
        plan.append((tensor, declared, do_it))
        if do_it:
            report.tensors_quantized += 1
            report.elements_quantized += tensor.elements
        else:
            report.tensors_copied += 1
            report.elements_copied += tensor.elements
            report.skipped.append((tensor.name, reason))

    by_name = {declared.name: (original, do_it) for original, declared, do_it in plan}
    done = 0

    def _data_for(declared: GGUFTensor) -> bytes:
        nonlocal done
        original, do_it = by_name[declared.name]
        raw = model.tensor_bytes(original)
        done += 1
        if progress is not None:
            try:
                progress({
                    "event": "tensor",
                    "name": declared.name,
                    "index": done,
                    "total": len(plan),
                    "quantized": do_it,
                })
            except Exception:  # noqa: BLE001 - a listener must not fail the run
                logger.debug("hyprslug: progress callback raised", exc_info=True)
        if not do_it:
            return raw
        values = _decode_floats(raw, original.ggml_type)
        importance = weights_by_tensor.get(declared.name)
        if importance is not None and len(importance) != len(values):
            # A mismatched imatrix is a different model's, and applying it
            # would weight the wrong positions. Ignore it for this tensor
            # and say so, rather than silently misweighting.
            logger.warning(
                "hyprslug: imatrix for %s has %d entries, tensor has %d; ignoring it",
                declared.name, len(importance), len(values),
            )
            importance = None
        try:
            return quantize_tensor(values, packing, importance)
        except SubBitError as exc:
            raise HyprslugError(f"{declared.name}: {exc}") from exc

    try:
        writer.write(_data_for)
    except (GGUFError, OSError) as exc:
        raise HyprslugError(f"Could not write {destination_path}: {exc}") from exc

    report.output_bytes = destination_path.stat().st_size
    report.seconds = time.time() - started
    if progress is not None:
        try:
            progress({"event": "done", **report.to_dict()})
        except Exception:  # noqa: BLE001
            logger.debug("hyprslug: progress callback raised", exc_info=True)
    return report
