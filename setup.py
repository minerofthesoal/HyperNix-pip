"""Legacy setup.py shim.

All real configuration lives in ``pyproject.toml`` (PEP 621). This file
exists so ``python setup.py <cmd>`` and ``pip install .`` work with
older tooling and with integrators that still look for ``setup.py``
in the project root.
"""
from setuptools import setup

if __name__ == "__main__":
    setup()
