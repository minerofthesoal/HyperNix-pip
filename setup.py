"""Legacy setup.py shim.

All real configuration lives in ``pyproject.toml`` (PEP 621). This file
exists so ``python setup.py <cmd>`` and ``pip install .`` work with
older tooling and with integrators that still look for ``setup.py``
in the project root.
"""
import os
from setuptools import setup, Extension

# By default, do not build the C++ extension during standard wheel builds
# to ensure we produce a universal py3-none-any.whl for PyPI.
# Users installing from source or those who explicitly set BUILD_CCTVTOP=1
# will get the compiled C++ cctvtop dashboard.
build_cctvtop = os.environ.get("BUILD_CCTVTOP", "0") == "1"

ext_modules = []
if build_cctvtop:
    cctvtop_ext = Extension(
        "hypernix.cctvtop_ext",
        sources=["src/hypernix/cctvtop.cpp"],
        language="c++",
        extra_compile_args=["-std=c++17", "-O3"],
    )
    ext_modules.append(cctvtop_ext)

if __name__ == "__main__":
    setup(
        ext_modules=ext_modules,
    )
