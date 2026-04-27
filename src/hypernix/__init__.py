"""hypernix — end-to-end toolkit for HyperNix-family PyTorch models.

The package grew out of a one-shot ``ray0rf1re/hyper-nix.1`` → GGUF
converter and now covers the whole lifecycle from a blank directory
to a trained, quantized, uploaded HuggingFace snapshot:

* :mod:`hypernix.download` / :func:`download_model` — pull snapshots
  from the Hub; :data:`KNOWN_MODELS` resolves short names like
  ``"nano-mini"``, ``"qwen3.5-4b"``, ``"gemma-4-e4b"``, ``"nix2.5"``.
* :mod:`hypernix.train` — :class:`HyperNixConfig`, :class:`HyperNixModel`,
  :func:`init_from_scratch`, :func:`expand_checkpoint`, :func:`train`.
  Non-HyperNix architectures (Gemma, Phi, DeepSeek, GLM, GPT-OSS,
  Qwen3/3.5/3.6, Gemma 4, …) route through a thin
  ``transformers.AutoModelForCausalLM`` wrapper.
* :mod:`hypernix.old_oven` — :class:`CodeOven`, :func:`preheat`,
  :func:`new_oven`, plus the :data:`ARCH_PRESETS` seed registry for
  fresh-init models across the Llama / Qwen / Gemma / Phi / GLM /
  DeepSeek / Nemotron / GPT-OSS / Nix families.
* :mod:`hypernix.old_fridge`, :mod:`hypernix.mediocre_fridge`,
  :mod:`hypernix.new_fridge` — memory housekeeping
  (freeze / unfreeze / parameter_stats), judge-training dataset
  generation, and training-curve plotting.
* :mod:`hypernix.new_range`, :mod:`hypernix.old_range`,
  :mod:`hypernix.industrial_range` — labeling rubrics that drop in as
  ``label_rule=...`` for :func:`mediocre_fridge.collect_responses_from`.
  ``new_range`` is a zero-dep first-fail rubric, ``old_range`` is a
  weighted-mean scored rubric with explainability, and
  ``industrial_range`` is the LLM-as-judge wrapper.
* :mod:`hypernix.freezer` — :class:`OldFreezer` (8-10 GB) /
  :class:`NewFreezer` (11 GB+) / :class:`FlashFreezer` (OOM-safe retry
  wrapper) + Pascal (sm_61 / CUDA 6.1) helpers:
  :func:`pascal_safe_dtype`, :func:`is_pascal`, :func:`pascal_mode_hints`.
* :mod:`hypernix.convert` / :mod:`hypernix.quantize` /
  :mod:`hypernix.upload` — the original GGUF pipeline, still intact.

See :doc:`/README.md` for the headline quickstart and
``wiki/`` in the source tree for deep-dive topic guides.
"""
from __future__ import annotations

from . import (
    apron,
    bell,
    blender,
    cake_pan,
    coffee_maker,
    cookbook,
    countertop,
    cutting_board,
    deep_fryer,
    espresso_maker,
    flour,
    food_processor,
    freezer,
    industrial_range,
    instant_pot,
    lunchbox,
    mediocre_fridge,
    menu,
    microwave,
    new_fridge,
    new_range,
    old_fridge,
    old_oven,
    old_range,
    pans,
    pepper_shaker,
    pressure_cooker,
    recipe_book,
    salt_shaker,
    sink,
    smoke_alarm,
    smoker,
    table,
    toaster,
    torch_compat,
    whisk,
)
from .convert import convert_to_gguf
from .download import (
    KNOWN_MODELS,
    ModelInfo,
    download_model,
    resolve_model_info,
    resolve_repo_id,
    verify_snapshot,
)
from .fetcher import fetch_llama_quantize
from .freezer import (
    CPU_PRESETS,
    GPU_PRESETS,
    CPUPreset,
    GPUPreset,
    cpu_preset,
    gpu_preset,
)
from .generate import generate_text
from .old_oven import (
    ARCH_PRESETS,
    CodeOven,
    bake_code,
    fill_middle,
    load_pt,
    new_oven,
    preheat,
)
from .quantize import QUANT_TYPES, quantize_gguf
from .train import (
    HyperNixConfig,
    HyperNixModel,
    expand_checkpoint,
    init_from_scratch,
    load_snapshot,
    save_snapshot,
    train,
)
from .upload import upload_gguf

__all__ = [
    "ARCH_PRESETS",
    "CPU_PRESETS",
    "CPUPreset",
    "CodeOven",
    "GPU_PRESETS",
    "GPUPreset",
    "HyperNixConfig",
    "HyperNixModel",
    "KNOWN_MODELS",
    "ModelInfo",
    "QUANT_TYPES",
    "apron",
    "bake_code",
    "bell",
    "blender",
    "cake_pan",
    "coffee_maker",
    "cookbook",
    "countertop",
    "cutting_board",
    "deep_fryer",
    "convert_to_gguf",
    "cpu_preset",
    "download_model",
    "espresso_maker",
    "expand_checkpoint",
    "fetch_llama_quantize",
    "fill_middle",
    "flour",
    "food_processor",
    "freezer",
    "generate_text",
    "gpu_preset",
    "industrial_range",
    "init_from_scratch",
    "instant_pot",
    "load_pt",
    "load_snapshot",
    "lunchbox",
    "mediocre_fridge",
    "menu",
    "microwave",
    "new_fridge",
    "new_oven",
    "new_range",
    "old_fridge",
    "old_oven",
    "old_range",
    "pans",
    "pepper_shaker",
    "pressure_cooker",
    "preheat",
    "quantize_gguf",
    "recipe_book",
    "resolve_model_info",
    "resolve_repo_id",
    "salt_shaker",
    "save_snapshot",
    "sink",
    "smoke_alarm",
    "smoker",
    "table",
    "toaster",
    "torch_compat",
    "train",
    "upload_gguf",
    "verify_snapshot",
    "whisk",
]

__version__ = "0.51.1"
DEFAULT_REPO_ID = "ray0rf1re/hyper-Nix.2"
