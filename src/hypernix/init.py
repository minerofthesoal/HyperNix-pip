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
  :func:`new_oven`, plus the :data:`ARCH_PRESETS` seed-init models
  across the Llama / Qwen / Gemma / Phi / GLM / DeepSeek / Nemotron /
  GPT-OSS / Nix families.
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

Import speed
------------
Nothing below is imported eagerly. ``import hypernix`` only runs this
file, which does no submodule work at all — it just registers where
each public name *would* come from. The first time you touch
``hypernix.<something>`` (attribute access), :func:`__getattr__`
below imports the one submodule that defines it and caches the result
on the package, so every later access is a plain attribute lookup with
no import overhead. Submodules never touched are never imported, so
running e.g. the ``tvtop`` dashboard or ``hyped`` chat CLI never pays
for importing torch/transformers/gguf/huggingface_hub just because
``hypernix/__init__.py`` happened to run first (every submodule import
runs the parent package's ``__init__.py`` before it runs the submodule
itself). This replaces the previous ``sys.argv[0]``-sniffing fast path,
which only covered a handful of hardcoded entry-point names and did
nothing for library use (``import hypernix`` from a REPL or a user's
own script).
"""
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

__version__ = "0.70.6-2"
DEFAULT_REPO_ID = "ray0rf1re/hyper-Nix.2"
DEFAULT_MODEL = "qwen3.5-4b"  # New default model

__all__ = [
    "ARCH_PRESETS",
    "Abbicus",
    "AbbicusConfig",
    "Agedcookerv4",
    "Agedcookerv5",
    "CardboardBox",
    "CookerLite",
    "TurboAbbicus",
    "TurboAbbicusConfig",
    "QAProcessor",
    "STML",
    "calculate_vram_context",
    "CPU_PRESETS",
    "CPUPreset",
    "CodeOven",
    "ComputeArch",
    "ComputeFramework",
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
    "PressureCookerV4",
    "PressureCookerV5",
    "PressureCookerV5Plus",
    "QUANT_CATALOG",
    "QUANT_TYPES",
    "QuantConfig",
    "QuantDtype",
    "QuantJob",
    "QuantSpec",
    "RoundPlan",
    "StovetopV3Cooker",
    "StovetopV3CookerPlus",
    "StovetopV4Cooker",
    "StovetopV4CookerPlus",
    "Tupperware",
    "TupperwareConfig",
    "ULTRAagedcookerv4",
    "ULTRAagedcookerv5",
    "Ultracookerv4",
    "abbicus",
    "apron",
    "cardboard_box",
    "qa",
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
    "optimizer_framework",
    "outage",
    "pans",
    "pepper_shaker",
    "plasma",
    "pressure_cooker",
    "pressure_cooker_v3",
    "pressure_cooker_v4",
    "pressure_cooker_v5",
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
    "stml",
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
    "tvtop_plus_plus",
    "ups",
    "upload_gguf",
    "verify_snapshot",
    "whisk",
    "workshop",
    "fizzle",
    "spinner",
    "hyper_log",
]

# Every public name hypernix exposes, mapped to the one submodule that
# actually defines it (and, if it's a re-exported member rather than the
# submodule itself, the attribute name to pull off of it once imported).
# Generated from the import statements this file used to run eagerly at
# module load time — see scripts/regen_lazy_attrs.py to rebuild it if the
# public API changes.
_LAZY_ATTRS: dict[str, tuple[str, str | None]] = {
    'ARCH_PRESETS': ('old_oven', 'ARCH_PRESETS'),
    'Abbicus': ('abbicus', 'Abbicus'),
    'AbbicusConfig': ('abbicus', 'AbbicusConfig'),
    'Agedcookerv4': ('pressure_cooker_v4', 'Agedcookerv4'),
    'Agedcookerv5': ('pressure_cooker_v5', 'Agedcookerv5'),
    'CPUPreset': ('freezer', 'CPUPreset'),
    'CPU_PRESETS': ('freezer', 'CPU_PRESETS'),
    'CardboardBox': ('cardboard_box', 'CardboardBox'),
    'CodeOven': ('old_oven', 'CodeOven'),
    'ComputeArch': ('compute_framework', 'ComputeArch'),
    'ComputeFramework': ('compute_framework', 'ComputeFramework'),
    'CookerLite': ('pressure_cooker_v4', 'CookerLite'),
    'GPUPreset': ('freezer', 'GPUPreset'),
    'GPU_PRESETS': ('freezer', 'GPU_PRESETS'),
    'HealthReport': ('utils', 'HealthReport'),
    'HyperNixConfig': ('train', 'HyperNixConfig'),
    'HyperNixModel': ('train', 'HyperNixModel'),
    'HyperNixQuantizer': ('quantize', 'HyperNixQuantizer'),
    'KNOWN_MODELS': ('download', 'KNOWN_MODELS'),
    'LazySusan': ('lazy_suzan', 'LazySusan'),
    'LazySusanConfig': ('lazy_suzan', 'LazySusanConfig'),
    'ModelInfo': ('download', 'ModelInfo'),
    'PressureCookerV3': ('pressure_cooker_v3', 'PressureCookerV3'),
    'PressureCookerV3Plus': ('pressure_cooker_v3', 'PressureCookerV3Plus'),
    'PressureCookerV4': ('pressure_cooker_v4', 'PressureCookerV4'),
    'PressureCookerV5': ('pressure_cooker_v5', 'PressureCookerV5'),
    'PressureCookerV5Plus': ('pressure_cooker_v5', 'PressureCookerV5Plus'),
    'QAProcessor': ('qa', 'QAProcessor'),
    'QUANT_CATALOG': ('quantize', 'CATALOG'),
    'QUANT_TYPES': ('quantize', 'QUANT_TYPES'),
    'QuantConfig': ('pressure_cooker_v3', 'QuantConfig'),
    'QuantDtype': ('pressure_cooker_v3', 'QuantDtype'),
    'QuantJob': ('quantize', 'QuantJob'),
    'QuantSpec': ('quantize', 'QuantSpec'),
    'RoundPlan': ('tupperware', 'RoundPlan'),
    'STML': ('stml', 'STML'),
    'StovetopV3Cooker': ('pressure_cooker_v3', 'StovetopV3Cooker'),
    'StovetopV3CookerPlus': ('pressure_cooker_v3', 'StovetopV3CookerPlus'),
    'StovetopV4Cooker': ('pressure_cooker_v4', 'StovetopV4Cooker'),
    'StovetopV4CookerPlus': ('pressure_cooker_v4', 'StovetopV4CookerPlus'),
    'Tupperware': ('tupperware', 'Tupperware'),
    'TupperwareConfig': ('tupperware', 'TupperwareConfig'),
    'TurboAbbicus': ('abbicus', 'TurboAbbicus'),
    'TurboAbbicusConfig': ('abbicus', 'TurboAbbicusConfig'),
    'ULTRAagedcookerv4': ('pressure_cooker_v4', 'ULTRAagedcookerv4'),
    'ULTRAagedcookerv5': ('pressure_cooker_v5', 'ULTRAagedcookerv5'),
    'Ultracookerv4': ('pressure_cooker_v4', 'Ultracookerv4'),
    'abbicus': ('abbicus', None),
    'apron': ('apron', None),
    'assistant': ('assistant', None),
    'bake_code': ('old_oven', 'bake_code'),
    'bell': ('bell', None),
    'blender': ('blender', None),
    'cake_pan': ('cake_pan', None),
    'calculate_vram_context': ('stml', 'calculate_vram_context'),
    'cardboard_box': ('cardboard_box', None),
    'coffee_maker': ('coffee_maker', None),
    'compactor': ('compactor', None),
    'compute_framework': ('compute_framework', None),
    'convert': ('convert', None),
    'convert_to_gguf': ('convert', 'convert_to_gguf'),
    'cookbook': ('cookbook', None),
    'countertop': ('countertop', None),
    'cpu_preset': ('freezer', 'cpu_preset'),
    'cutting_board': ('cutting_board', None),
    'deep_fryer': ('deep_fryer', None),
    'diagnostic_info': ('utils', 'diagnostic_info'),
    'dishwasher': ('dishwasher', None),
    'download': ('download', None),
    'download_model': ('download', 'download_model'),
    'espresso_maker': ('espresso_maker', None),
    'ethanol': ('ethanol', None),
    'expand_checkpoint': ('train', 'expand_checkpoint'),
    'fetch_llama_quantize': ('fetcher', 'fetch_llama_quantize'),
    'fetcher': ('fetcher', None),
    'fill_middle': ('old_oven', 'fill_middle'),
    'fizzle': ('fizzle', None),
    'flour': ('flour', None),
    'food_processor': ('food_processor', None),
    'freezer': ('freezer', None),
    'generate': ('generate', None),
    'generate_text': ('generate', 'generate_text'),
    'gpu_preset': ('freezer', 'gpu_preset'),
    'healthcheck': ('utils', 'healthcheck'),
    'hyped': ('hyped', None),
    'hyper_log': ('hyper_log', None),
    'industrial_range': ('industrial_range', None),
    'init_from_scratch': ('train', 'init_from_scratch'),
    'injection': ('injection', None),
    'instant_pot': ('instant_pot', None),
    'lazy_suzan': ('lazy_suzan', None),
    'list_models': ('utils', 'list_models'),
    'load_pt': ('old_oven', 'load_pt'),
    'load_snapshot': ('train', 'load_snapshot'),
    'lunchbox': ('lunchbox', None),
    'mediocre_fridge': ('mediocre_fridge', None),
    'menu': ('menu', None),
    'microwave': ('microwave', None),
    'new_fridge': ('new_fridge', None),
    'new_oven': ('old_oven', 'new_oven'),
    'new_range': ('new_range', None),
    'old_fridge': ('old_fridge', None),
    'old_oven': ('old_oven', None),
    'old_range': ('old_range', None),
    'optimizer_framework': ('optimizer_framework', None),
    'outage': ('outage', None),
    'pans': ('pans', None),
    'pepper_shaker': ('pepper_shaker', None),
    'plasma': ('plasma', None),
    'preheat': ('old_oven', 'preheat'),
    'pressure_cooker': ('pressure_cooker', None),
    'pressure_cooker_v3': ('pressure_cooker_v3', None),
    'pressure_cooker_v4': ('pressure_cooker_v4', None),
    'pressure_cooker_v5': ('pressure_cooker_v5', None),
    'print_models': ('utils', 'print_models'),
    'qa': ('qa', None),
    'quant_batch': ('quantize', 'batch_quantize'),
    'quant_by_category': ('quantize', 'by_category'),
    'quant_estimate_size': ('quantize', 'estimate_size'),
    'quant_for_size': ('quantize', 'for_size'),
    'quant_list_types': ('quantize', 'list_types'),
    'quant_recommend_profile': ('quantize', 'recommend_profile'),
    'quant_recommended': ('quantize', 'recommended'),
    'quant_resolve_spec': ('quantize', 'resolve_spec'),
    'quantize': ('quantize', None),
    'quantize_gguf': ('quantize', 'quantize_gguf'),
    'recipe_book': ('recipe_book', None),
    'resolve_model_info': ('download', 'resolve_model_info'),
    'resolve_repo_id': ('download', 'resolve_repo_id'),
    'salt_shaker': ('salt_shaker', None),
    'save_snapshot': ('train', 'save_snapshot'),
    'session_dir': ('utils', 'session_dir'),
    'sink': ('sink', None),
    'smoke_alarm': ('smoke_alarm', None),
    'smoker': ('smoker', None),
    'spinner': ('spinner', None),
    'stml': ('stml', None),
    'strainer': ('strainer', None),
    'table': ('table', None),
    'thermometer': ('thermometer', None),
    'timer': ('timer', None),
    'toaster': ('toaster', None),
    'torch_compat': ('torch_compat', None),
    'train': ('train', 'train'),
    'tupperware': ('tupperware', None),
    'tv': ('tv', None),
    'tvtop': ('tvtop', None),
    'tvtop_plus_plus': ('tvtop_plus_plus', None),
    'upload': ('upload', None),
    'upload_gguf': ('upload', 'upload_gguf'),
    'ups': ('ups', None),
    'utils': ('utils', None),
    'verify_snapshot': ('download', 'verify_snapshot'),
    'whisk': ('whisk', None),
    'workshop': ('workshop', None),
}


def __getattr__(name: str) -> Any:
    """PEP 562 lazy attribute loader.

    Only ever imports the single submodule that defines ``name``, the
    first time it's actually asked for, then caches the result directly
    on the package so subsequent lookups are a normal attribute access
    (no repeated importlib overhead, no re-running this function).
    """
    try:
        submodule, attr = _LAZY_ATTRS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    module = importlib.import_module(f".{submodule}", __name__)
    value = module if attr is None else getattr(module, attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_ATTRS))


if TYPE_CHECKING:
    # Not executed at runtime (TYPE_CHECKING is always False), so this
    # costs nothing at import time — it exists purely so IDEs/type
    # checkers still see real symbols instead of "Any" for every
    # hypernix.* access. Keep this in sync with _LAZY_ATTRS above.
    from . import (
        abbicus,
        apron,
        assistant,
        bell,
        blender,
        cake_pan,
        cardboard_box,
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
        fizzle,
        flour,
        food_processor,
        freezer,
        hyped,
        hyper_log,
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
        optimizer_framework,
        outage,
        pans,
        pepper_shaker,
        plasma,
        pressure_cooker,
        pressure_cooker_v3,
        pressure_cooker_v4,
        pressure_cooker_v5,
        qa,
        recipe_book,
        salt_shaker,
        sink,
        smoke_alarm,
        smoker,
        spinner,
        stml,
        strainer,
        table,
        thermometer,
        timer,
        toaster,
        torch_compat,
        tupperware,
        tv,
        tvtop,
        tvtop_plus_plus,
        ups,
        whisk,
        workshop,
    )
    from .abbicus import Abbicus, AbbicusConfig, TurboAbbicus, TurboAbbicusConfig
    from .cardboard_box import CardboardBox
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
        PressureCookerV3,
        PressureCookerV3Plus,
        QuantConfig,
        QuantDtype,
        StovetopV3Cooker,
        StovetopV3CookerPlus,
    )
    from .pressure_cooker_v4 import (
        Agedcookerv4,
        CookerLite,
        PressureCookerV4,
        StovetopV4Cooker,
        StovetopV4CookerPlus,
        ULTRAagedcookerv4,
        Ultracookerv4,
    )
    from .pressure_cooker_v5 import (
        Agedcookerv5,
        PressureCookerV5,
        PressureCookerV5Plus,
        ULTRAagedcookerv5,
    )
    from .qa import QAProcessor
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
    from .stml import STML, calculate_vram_context
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
