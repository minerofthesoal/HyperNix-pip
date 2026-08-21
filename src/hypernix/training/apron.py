"""apron — RNG state guard.

An apron protects what's underneath while you cook.  Here it
captures every random-number source hypernix or your script might
touch (Python's ``random``, NumPy if installed, PyTorch CPU + CUDA),
and restores it on exit.

Two ways to use it:

::

    # As a context manager — the cleanest path:
    from hypernix.apron import apron

    with apron(seed=0):
        # everything inside is deterministic; nothing leaks out.
        random.shuffle(my_list)
        torch.randn(10)

    # Object form — for finer control / saving across cells in a
    # Jupyter notebook:
    from hypernix.apron import Apron
    a = Apron.snapshot(seed=0)
    ...
    a.restore()

Use it any time a step in your pipeline wants to perturb the
global RNG (e.g. an evaluator that uses :func:`torch.randn` for
sampling) without leaking the perturbation back to the caller.
"""
from __future__ import annotations

import contextlib
import random
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import torch


@dataclass
class Apron:
    """Captured snapshot of every RNG state hypernix knows about.

    Construct via :meth:`Apron.snapshot` (or the :func:`apron`
    context manager, which also handles restore on exit).
    Restore via :meth:`Apron.restore`.

    Captures: ``random`` (Python), ``numpy.random`` (if installed),
    ``torch`` CPU RNG, every CUDA device's RNG when CUDA is
    available.
    """

    py_state: tuple = field(default_factory=tuple)
    numpy_state: Any = None
    torch_state: torch.Tensor | None = None
    cuda_states: list[torch.Tensor] = field(default_factory=list)

    @classmethod
    def snapshot(cls, *, seed: int | None = None) -> Apron:
        """Capture the current RNG state, *then* optionally seed.

        The snapshot is the **pre-seed** state, so :meth:`restore`
        (or the :func:`apron` context manager exit) puts the caller
        back to whatever they were doing before — not back to the
        seeded starting point.  This is what most callers want when
        they write ``with apron(seed=42):``.
        """
        py_state = random.getstate()
        torch_state = torch.get_rng_state()
        try:
            import numpy as np
            numpy_state = np.random.get_state()
        except ImportError:
            numpy_state = None
        cuda_states: list[torch.Tensor] = []
        if torch.cuda.is_available():
            cuda_states = [
                torch.cuda.get_rng_state(i)
                for i in range(torch.cuda.device_count())
            ]

        if seed is not None:
            random.seed(seed)
            torch.manual_seed(seed)
            try:
                import numpy as np
                np.random.seed(seed % (2 ** 32))
            except ImportError:
                pass
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(seed)

        return cls(
            py_state=py_state,
            numpy_state=numpy_state,
            torch_state=torch_state,
            cuda_states=cuda_states,
        )

    def restore(self) -> None:
        """Restore every captured RNG."""
        if self.py_state:
            random.setstate(self.py_state)
        if self.torch_state is not None:
            torch.set_rng_state(self.torch_state)
        if self.numpy_state is not None:
            try:
                import numpy as np
                np.random.set_state(self.numpy_state)
            except ImportError:
                pass
        if self.cuda_states and torch.cuda.is_available():
            for i, state in enumerate(self.cuda_states):
                torch.cuda.set_rng_state(state, i)


@contextlib.contextmanager
def apron(*, seed: int | None = None) -> Iterator[Apron]:
    """Context manager that snapshots every RNG, optionally seeds
    them, runs the body, and restores the original states on exit.

    Yields the :class:`Apron` for callers that want to read the
    captured states inside the block.
    """
    a = Apron.snapshot(seed=seed)
    try:
        yield a
    finally:
        a.restore()
