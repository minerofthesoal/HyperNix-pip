"""hypernix.pressure_cooker_v6v — Pressure Cooker V6V: GPU-native V6.

``PressureCookerV6V`` is :class:`~hypernix.pressure_cooker_v6.PressureCookerV6`
with two additive, CUDA-only mechanisms layered on top — it does not change
the SSTM update rule itself (see ``pressure_cooker_v6.py`` for that math),
it changes *how the update gets onto the GPU*:

1. **CUDA graph capture / replay.** V6's step is already a handful of fused
   multi-tensor kernel launches instead of AdamW's per-tensor sequence, but
   "a handful" is still dozens of separate kernel launches for a real model
   with hundreds of parameter tensors, and each launch has fixed CPU-side
   overhead that dominates for small/medium models. ``warmup_graph(step_fn)``
   / ``replay_graph()`` record that whole sequence once with
   ``torch.cuda.CUDAGraph`` and replay it with a single launch thereafter —
   the same mechanism :class:`hypernix.pressure_cooker.ProCooker` already
   uses (same method names, same contract: fixed shapes, no dynamic control
   flow, call ``warmup_graph`` once with a representative step).
2. **Optional `torch.compile`.** When available (torch ≥ 2.0) and
   ``compile=True`` (the default), the internal ``_sstm_step`` is wrapped
   with ``torch.compile`` so its multi-tensor ops get kernel-fused by
   TorchInductor/Triton instead of running as separate launches. This is
   independent of CUDA graph capture — you can use either, both, or
   neither. If compilation fails or ``torch.compile`` isn't available, V6V
   warns once and falls back to the eager V6 path; it never raises for this.

Honesty note on verification: this module's CUDA-only paths (graph
capture/replay, compiled execution on an actual CUDA device) were written
against the same, already-shipped ``ProCooker.warmup_graph``/
``replay_graph`` implementation in ``pressure_cooker.py`` and exercised in
this package's test suite on CPU wherever a code path doesn't strictly
require CUDA (constructor validation, the `torch.compile` fallback-on-
failure branch). The authoring environment for this file had no CUDA
device available, so the graph-capture and on-GPU-compiled-execution paths
themselves were not run against real hardware here — they reuse
``ProCooker``'s proven pattern rather than inventing a new one, but treat
that as "written to the same contract," not "benchmarked on a GPU."
``scripts/benchmark_v6.py`` runs on CUDA when it's available and reports
real, measured numbers for whatever hardware you run it on — it does not
print a canned speedup figure.

Requires CUDA parameters at construction time (raises ``RuntimeError``
otherwise, same pattern as torch's own ``fused=True`` requiring sm_70+)
because CUDA graph capture and the primary reason to reach for this class
over plain :class:`PressureCookerV6` are both CUDA-specific. Use
``PressureCookerV6`` directly for CPU or portable training.

v0.71.4-4 — initial release, alongside V6 (unreleased at time of writing; see wiki/Changelog.md).
"""
from __future__ import annotations

import warnings
from collections.abc import Callable, Iterable
from typing import Any

import torch

from .pressure_cooker_v3 import _flatten_optimizer_params, _iter_optimizer_tensors
from .pressure_cooker_v6 import PressureCookerV6

__all__ = ["PressureCookerV6V"]


def _has_cuda_param(materialized_params: Iterable[Any]) -> bool:
    for p in _iter_optimizer_tensors(materialized_params):
        device = getattr(p, "device", None)
        if isinstance(device, torch.device) and device.type == "cuda":
            return True
    return False


class PressureCookerV6V(PressureCookerV6):
    """PressureCookerV6, wired for CUDA graph capture and optional ``torch.compile``.

    Args:
        params: Iterable of CUDA parameters or param-group dicts (at least
            one parameter must already be on a CUDA device).
        compile: Wrap the internal fused step with ``torch.compile`` when
            available. Falls back to eager execution (with a warning) if
            ``torch.compile`` is unavailable or compilation fails for any
            reason — never raises for this.
        **kwargs: Forwarded to :class:`PressureCookerV6`.
    """

    _graph: Any = None
    _graph_step: Any = None

    def __init__(
        self,
        params: Iterable[torch.nn.Parameter] | Iterable[dict],
        *,
        compile: bool = True,
        **kwargs: Any,
    ) -> None:
        materialized_params = _flatten_optimizer_params(params)
        if not _has_cuda_param(materialized_params):
            raise RuntimeError(
                "PressureCookerV6V requires at least one CUDA parameter -- "
                "move the model to a CUDA device first (`model.to('cuda')`), "
                "or use PressureCookerV6 for CPU / portable training."
            )
        super().__init__(materialized_params, **kwargs)
        self._compiled_sstm_step = None
        if compile:
            self._try_compile()

    # -- torch.compile --------------------------------------------------

    def _try_compile(self) -> None:
        if not hasattr(torch, "compile"):
            warnings.warn(
                "torch.compile is unavailable on this torch build "
                f"(torch {torch.__version__}); PressureCookerV6V will run "
                "the eager foreach path instead of a compiled one.",
                stacklevel=2,
            )
            return
        try:
            self._compiled_sstm_step = torch.compile(self._sstm_step)
        except Exception as exc:  # pragma: no cover - depends on local torch/triton install
            warnings.warn(
                f"torch.compile failed to wrap the V6V step ({exc!r}); "
                "falling back to eager execution.",
                stacklevel=2,
            )
            self._compiled_sstm_step = None

    def _apply_update(self) -> None:
        """Overrides :meth:`PressureCookerV6._apply_update` to route
        through the compiled step when available, instead of duplicating
        :meth:`PressureCookerV6.step`'s grad-accumulation / GradScaler /
        grad-clip handling here too. Falls back to the eager fused path on
        first failure and stays there for the rest of the run rather than
        re-attempting (and re-warning on) a compile that already failed."""
        if self._compiled_sstm_step is not None:
            try:
                self._compiled_sstm_step()
                return
            except Exception as exc:  # pragma: no cover - depends on local torch/triton install
                warnings.warn(
                    f"Compiled V6V step raised at runtime ({exc!r}); "
                    "disabling the compiled path for the rest of this run "
                    "and falling back to eager execution.",
                    stacklevel=2,
                )
                self._compiled_sstm_step = None
        self._sstm_step()

    # -- CUDA graph capture (identical API/contract to ProCooker) -------

    def warmup_graph(self, step_fn: Callable[[], Any]) -> None:
        """Record a CUDA graph from a representative training step.

        Same contract as
        :meth:`hypernix.pressure_cooker.ProCooker.warmup_graph`: call once
        with a closure that runs a full forward/backward/``step()`` on a
        representative, fixed-shape batch; use :meth:`replay_graph` for
        subsequent iterations. Skip this for dynamic batch shapes or
        models with data-dependent control flow.

        **Important, not a hypothetical caveat:** CUDA graph capture bakes
        in whatever Python-level *branch* ran during warmup, permanently —
        replay always re-executes the same recorded kernels regardless of
        what new data looks like. If ``grad_accum_steps > 1``,
        ``grad_scaler`` is set, or ``skip_on_nonfinite=True``, the
        accumulation counter / non-finite check / skip-vs-apply decision
        inside :meth:`PressureCookerV6.step` only gets evaluated *once*,
        at capture time — whichever branch it took then (normally "batch
        is finite, apply the update") is what every single ``replay_graph``
        call will do afterwards, even if a later batch actually is
        non-finite or accumulation should have skipped that step. This
        isn't a bug in this class, it's what CUDA graphs fundamentally are
        — but it means those three features and graph capture don't
        combine safely. If you need dynamic non-finite skipping or
        accumulation gating, don't call ``warmup_graph`` (use the eager or
        compiled-but-ungraphed path instead), or capture only after
        confirming those branches won't need to change during the run.
        """
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA graphs require a CUDA device")
        if self.grad_accum_steps > 1 or self.grad_scaler is not None or self.skip_on_nonfinite:
            warnings.warn(
                "warmup_graph() is being called with grad_accum_steps>1, "
                "a grad_scaler, or skip_on_nonfinite=True set -- CUDA graph "
                "replay will always take whatever branch those took during "
                "this warmup call, forever, regardless of future batches. "
                "See the warmup_graph docstring before relying on this.",
                stacklevel=2,
            )
        for _ in range(3):
            step_fn()
        torch.cuda.synchronize()
        self._graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(self._graph):
            self._graph_step = step_fn()

    def replay_graph(self):
        """Replay the captured graph. Returns whatever ``step_fn`` returned
        (typically the loss tensor, still live on device)."""
        if self._graph is None:
            raise RuntimeError("call warmup_graph(step_fn) first")
        self._graph.replay()
        return self._graph_step

    def describe(self) -> dict[str, Any]:
        base = super().describe()
        base["compiled"] = self._compiled_sstm_step is not None
        base["cuda_graph_captured"] = self._graph is not None
        return base
