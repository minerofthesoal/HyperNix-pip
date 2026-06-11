"""torch_compat — shims for running hypernix on older PyTorch.

Main use case: **old Intel Macs**.  The last PyTorch line that
shipped Intel-mac wheels is 2.2; before that, 1.13 is the natural
floor because it's the last 1.x release and the last version that
installs cleanly on macOS 11 / 10.15 / older Xcode stacks.

The main package pins ``torch>=2.7`` because that's where
``nn.RMSNorm`` stabilised.  This module provides portable
fallbacks so a carefully-set-up legacy environment can still run
the training / inference paths that matter on an old laptop.

Provides (all version-gated at import time):

* :class:`RMSNorm`                — equivalent to ``torch.nn.RMSNorm``
                                     when that exists; a hand-rolled
                                     fallback otherwise.
* :func:`scaled_dot_product_attention` — uses
                                     ``torch.nn.functional.scaled_dot_product_attention``
                                     on torch ≥ 2.0; falls back to
                                     explicit softmax(QKᵀ/√d) on 1.x.
* :data:`TORCH_VERSION` / :func:`is_legacy_torch`  — the gate used by
                                     every shim.

On torch ≥ 2.7 these are all thin pass-throughs, so there is no
runtime cost in the happy path.

See ``scripts/install_macos_legacy.sh`` for the companion installer
that pins torch 1.13 on an old Intel Mac and patches the dep
resolution.
"""
from __future__ import annotations

import math

import torch
import torch.nn as nn

TORCH_VERSION: tuple[int, int] = tuple(  # type: ignore[assignment]
    int(p) for p in torch.__version__.split("+")[0].split(".")[:2]
)


def is_legacy_torch() -> bool:
    """True for torch < 2.0 (the "old Intel Mac / torch 1.13" path)."""
    return TORCH_VERSION < (2, 0)


def has_native_rmsnorm() -> bool:
    """True for torch ≥ 2.4 where ``torch.nn.RMSNorm`` is available."""
    return TORCH_VERSION >= (2, 4) and hasattr(nn, "RMSNorm")


# ---------------------------------------------------------------------------
# RMSNorm
# ---------------------------------------------------------------------------

if has_native_rmsnorm():
    RMSNorm = nn.RMSNorm  # type: ignore[attr-defined, misc, assignment]
else:
    class RMSNorm(nn.Module):  # type: ignore[no-redef]
        """Fallback RMSNorm for torch < 2.4.

        Matches the semantics of ``torch.nn.RMSNorm``: normalises by
        the root-mean-square over the last dimension and scales by a
        learned ``weight`` vector.  No bias by design.
        """

        def __init__(
            self, normalized_shape: int | tuple[int, ...],
            eps: float = 1e-6, elementwise_affine: bool = True,
        ) -> None:
            super().__init__()
            if isinstance(normalized_shape, int):
                shape: tuple[int, ...] = (normalized_shape,)
            else:
                shape = tuple(normalized_shape)
            self.normalized_shape = shape
            self.eps = eps
            self.elementwise_affine = elementwise_affine
            if elementwise_affine:
                self.weight = nn.Parameter(torch.ones(shape))
            else:
                self.register_parameter("weight", None)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            # Normalise over the trailing dims matching normalized_shape.
            dims = tuple(range(-len(self.normalized_shape), 0))
            var = x.pow(2).mean(dim=dims, keepdim=True)
            y = x * torch.rsqrt(var + self.eps)
            if self.weight is not None:
                y = y * self.weight
            return y

        def extra_repr(self) -> str:
            return (
                f"normalized_shape={self.normalized_shape}, eps={self.eps}, "
                f"elementwise_affine={self.elementwise_affine}"
            )


# ---------------------------------------------------------------------------
# scaled_dot_product_attention
# ---------------------------------------------------------------------------

def scaled_dot_product_attention(
    q: torch.Tensor,
    k: torch.Tensor,
    v: torch.Tensor,
    *,
    attn_mask: torch.Tensor | None = None,
    dropout_p: float = 0.0,
    is_causal: bool = False,
) -> torch.Tensor:
    """Portable attention.  On torch ≥ 2.0 dispatches to the native
    fused kernel; on torch 1.x falls back to explicit softmax(QKᵀ/√d).

    Accepts the same (q, k, v) shapes as the torch 2.x built-in:
    ``(..., seq, head_dim)`` where ``...`` is any number of leading
    batch / head dims.
    """
    if not is_legacy_torch():
        import torch.nn.functional as F
        return F.scaled_dot_product_attention(
            q, k, v, attn_mask=attn_mask, dropout_p=dropout_p,
            is_causal=is_causal,
        )

    # Fallback path — torch 1.x.
    head_dim = q.size(-1)
    scale = 1.0 / math.sqrt(head_dim)
    scores = torch.matmul(q, k.transpose(-1, -2)) * scale
    if is_causal:
        seq = scores.size(-1)
        mask = torch.ones(seq, seq, dtype=torch.bool, device=scores.device)
        mask = torch.triu(mask, diagonal=1)
        scores = scores.masked_fill(mask, float("-inf"))
    if attn_mask is not None:
        if attn_mask.dtype == torch.bool:
            scores = scores.masked_fill(~attn_mask, float("-inf"))
        else:
            scores = scores + attn_mask
    attn = torch.softmax(scores, dim=-1)
    if dropout_p > 0.0:
        attn = torch.nn.functional.dropout(attn, p=dropout_p)
    return torch.matmul(attn, v)


def describe() -> dict[str, object]:
    """Return a one-shot summary of the active torch compat state."""
    return {
        "torch_version": torch.__version__,
        "torch_version_tuple": TORCH_VERSION,
        "is_legacy_torch": is_legacy_torch(),
        "has_native_rmsnorm": has_native_rmsnorm(),
    }
