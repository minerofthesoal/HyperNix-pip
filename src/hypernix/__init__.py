"""hypernix — end-to-end toolkit for HyperNix-family PyTorch models.

The package grew out of a one-shot ``ray0rf1re/hyper-nix.1`` → GGUF
converter (v1 is still fully supported) and now covers the whole
lifecycle for the chat-tuned ``ray0rf1re/hyper-Nix.2`` (current
default) and every related model — from a blank directory to a
trained, quantized, uploaded HuggingFace snapshot:

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

import sys

# Fast-path for tvtop: skip heavy imports to boot instantly
_is_tvtop = sys.argv and sys.argv[0].endswith("tvtop")

if not _is_tvtop:
    from . import (
        abbicus,
        apron,
        assistant,
        bell,
        blender,
        cake_pan,
        coffee_maker,
        compactor,
        compute_framework,
        cookbook,
        countertop,
        cutting_board,
        deep_fryer,
        dishwasher,
        espresso_maker,
        ethanol,
        flour,
        food_processor,
        freezer,
        hyped,
        industrial_range,
        injection,
        instant_pot,
        lazy_suzan,
        lunchbox,
        mediocre_fridge,
        menu,
        microwave,
        new_fridge,
        new_range,
        old_fridge,
        old_oven,
        old_range,
        outage,
        pans,
        pepper_shaker,
        plasma,
        pressure_cooker,
        pressure_cooker_v3,
        recipe_book,
        salt_shaker,
        sink,
        smoke_alarm,
        smoker,
        strainer,
        table,
        thermometer,
        timer,
        toaster,
        torch_compat,
        tupperware,
        tv,
        tvtop,
        ups,
        whisk,
        workshop,
    )
    from .abbicus import Abbicus, AbbicusConfig
    from .compute_framework import ComputeArch, ComputeFramework
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
    from .lazy_suzan import LazySusan, LazySusanConfig
    from .old_oven import (
        ARCH_PRESETS,
        CodeOven,
        bake_code,
        fill_middle,
        load_pt,
        new_oven,
        preheat,
    )
    from .pressure_cooker_v3 import (
        CookerLite,
        PressureCookerV3,
        PressureCookerV3Plus,
        QuantConfig,
        QuantDtype,
        StovetopV3Cooker,
        StovetopV3CookerPlus,
    )
    from .quantize import CATALOG as QUANT_CATALOG  # noqa: I001
    from .quantize import QUANT_TYPES, HyperNixQuantizer, QuantJob, QuantSpec, quantize_gguf
    from .quantize import batch_quantize as quant_batch
    from .quantize import by_category as quant_by_category
    from .quantize import estimate_size as quant_estimate_size
    from .quantize import for_size as quant_for_size
    from .quantize import list_types as quant_list_types
    from .quantize import recommend_profile as quant_recommend_profile
    from .quantize import recommended as quant_recommended
    from .quantize import resolve_spec as quant_resolve_spec
    from .train import (
        HyperNixConfig,
        HyperNixModel,
        expand_checkpoint,
        init_from_scratch,
        load_snapshot,
        save_snapshot,
        train,
    )
    from .tupperware import RoundPlan, Tupperware, TupperwareConfig
    from .upload import upload_gguf
    from .utils import (
        HealthReport,
        diagnostic_info,
        healthcheck,
        list_models,
        print_models,
        session_dir,
    )

    __all__ = [
        "ARCH_PRESETS",
        "Abbicus",
        "AbbicusConfig",
        "CPU_PRESETS",
        "CPUPreset",
        "CodeOven",
        "ComputeArch",
        "ComputeFramework",
        "CookerLite",
        "GPU_PRESETS",
        "GPUPreset",
        "HyperNixConfig",
        "HealthReport",
        "HyperNixModel",
        "HyperNixQuantizer",
        "KNOWN_MODELS",
        "LazySusan",
        "LazySusanConfig",
        "ModelInfo",
        "PressureCookerV3",
        "PressureCookerV3Plus",
        "QUANT_CATALOG",
        "QUANT_TYPES",
        "QuantConfig",
        "QuantDtype",
        "QuantJob",
        "QuantSpec",
        "RoundPlan",
        "StovetopV3Cooker",
        "StovetopV3CookerPlus",
        "Tupperware",
        "TupperwareConfig",
        "abbicus",
        "apron",
        "assistant",
        "bake_code",
        "bell",
        "blender",
        "cake_pan",
        "coffee_maker",
        "compactor",
        "compute_framework",
        "cookbook",
        "countertop",
        "cutting_board",
        "deep_fryer",
        "diagnostic_info",
        "dishwasher",
        "ethanol",
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
        "healthcheck",
        "hyped",
        "industrial_range",
        "init_from_scratch",
        "injection",
        "instant_pot",
        "lazy_suzan",
        "list_models",
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
        "outage",
        "pans",
        "pepper_shaker",
        "plasma",
        "pressure_cooker",
        "pressure_cooker_v3",
        "preheat",
        "print_models",
        "quant_batch",
        "quant_by_category",
        "quant_estimate_size",
        "quant_for_size",
        "quant_list_types",
        "quant_recommend_profile",
        "quant_recommended",
        "quant_resolve_spec",
        "quantize_gguf",
        "recipe_book",
        "resolve_model_info",
        "resolve_repo_id",
        "salt_shaker",
        "save_snapshot",
        "session_dir",
        "sink",
        "smoke_alarm",
        "smoker",
        "strainer",
        "table",
        "thermometer",
        "timer",
        "toaster",
        "torch_compat",
        "train",
        "tupperware",
        "tv",
        "tvtop",
        "ups",
        "upload_gguf",
        "verify_snapshot",
        "whisk",
        "workshop",
    ]
else:
    from . import tv, tvtop
    __all__ = ["tv", "tvtop"]

__version__ = "0.70.3"
DEFAULT_REPO_ID = "ray0rf1re/hyper-Nix.2"
