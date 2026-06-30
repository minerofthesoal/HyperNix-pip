"""recipe_book — saved configs for instant_pot, smoker, and friends.

A recipe book is the registry of named configurations.  Instead of
typing the same 12-key dict every time you brew, save it once with
a name and refer back by name forever.

Example::

    from hypernix.recipe_book import RecipeBook

    book = RecipeBook()
    book.add(
        "evaluator-quick",
        {
            "repo_id": "nix2.5",
            "dataset": "judge.txt",
            "out_dir": "./trained",
            "steps": 500,
            "batch_size": 1,
            "context_length": 1024,
            "device": "cuda",
            "dtype": "float16",
        },
    )
    book.save("recipes.json")

    # later, in a different process:
    book = RecipeBook.load("recipes.json")
    book.cook("evaluator-quick")     # routes through instant_pot.brew

The default :data:`HYPERNIX_RECIPES` dict ships with a handful of
ready-to-use recipes covering the common cases: a quick evaluator
smoke run, a Pascal-friendly fine-tune, an iterative cold-brew
nightly job.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Built-in recipes
# ---------------------------------------------------------------------------

#: A handful of recipes that work out of the box for the common
#: hypernix workflows.  Edit / extend at your own pace by calling
#: ``RecipeBook.from_builtins().add(...)``.
HYPERNIX_RECIPES: dict[str, dict[str, Any]] = {
    # ---- Quick evaluator smoke test ----
    "evaluator-quick": {
        "kind": "instant_pot",
        "repo_id": "nix2.5",
        "dataset": "judge.txt",
        "out_dir": "./trained-quick",
        "steps": 200,
        "batch_size": 1,
        "context_length": 512,
        "log_every": 25,
        "save_every": 0,
        "device": None,                # auto: cuda if available
        "dtype": "float32",
        "quiet": True,
    },
    # ---- Pascal-friendly HyperNix 1.5 fine-tune ----
    "ftune-pascal": {
        "kind": "instant_pot",
        "repo_id": "ray0rf1re/hyper-nix.1",
        "dataset": "corpus.txt",
        "out_dir": "./trained-pascal",
        "steps": 2000,
        "batch_size": 1,
        "context_length": 1024,
        "lr": 3e-4,
        "log_every": 50,
        "save_every": 500,
        "device": "cuda",
        "dtype": "float16",
        "freeze_embed": True,
        "quiet": False,
    },
    # ---- Iterative nightly cold-brew refinement ----
    "nightly-coldbrew": {
        "kind": "cold_brew",
        "phases": 7,
        "checkpoint_path": "./nightly/state.json",
        "phase_interval_seconds": 86400,
    },
    # ---- Eval-only with the espresso maker ----
    "espresso-eval": {
        "kind": "espresso",
        "tier": "double-shot",
        "max_new_tokens": 64,
        "temperature": 0.2,
    },
}


@dataclass
class RecipeBook:
    """Named-config registry."""

    recipes: dict[str, dict[str, Any]] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(self, name: str, recipe: dict[str, Any]) -> None:
        if not isinstance(recipe, dict):
            raise TypeError("recipe must be a dict")
        self.recipes[name] = copy.deepcopy(recipe)

    def get(self, name: str) -> dict[str, Any]:
        if name not in self.recipes:
            raise KeyError(
                f"unknown recipe {name!r}; known: {sorted(self.recipes)}",
            )
        return copy.deepcopy(self.recipes[name])

    def remove(self, name: str) -> None:
        del self.recipes[name]

    def __contains__(self, name: str) -> bool:
        return name in self.recipes

    def __len__(self) -> int:
        return len(self.recipes)

    def names(self) -> list[str]:
        return sorted(self.recipes)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: Path | str) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(self.recipes, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return p

    @classmethod
    def load(cls, path: Path | str) -> RecipeBook:
        p = Path(path)
        return cls(recipes=json.loads(p.read_text(encoding="utf-8")))

    @classmethod
    def from_builtins(cls) -> RecipeBook:
        """Return a book preloaded with :data:`HYPERNIX_RECIPES`."""
        return cls(recipes=copy.deepcopy(HYPERNIX_RECIPES))

    # ------------------------------------------------------------------
    # Cooking
    # ------------------------------------------------------------------

    def cook(self, name: str, **overrides: Any) -> Any:
        """Look up ``name``, apply ``overrides`` on top, dispatch to
        the right runner based on the recipe's ``kind`` key.

        Recognised kinds:

        * ``"instant_pot"``  — :func:`hypernix.instant_pot.brew`
        * ``"cold_brew"``    — caller supplies the brew_fn via
                               ``overrides["brew_fn"]``
        * ``"espresso"``     — caller supplies the oven via
                               ``overrides["oven"]``

        Anything else passes through with a ``ValueError``.
        """
        recipe = self.get(name)
        recipe.update(overrides)
        kind = recipe.pop("kind", "instant_pot")

        if kind == "instant_pot":
            from . import instant_pot
            return instant_pot.brew(recipe)
        if kind == "cold_brew":
            from . import coffee_maker
            brew_fn = recipe.pop("brew_fn", None)
            if brew_fn is None:
                raise ValueError(
                    "cold_brew recipe needs brew_fn= override",
                )
            return coffee_maker.cold_brew(brew_fn, **recipe).brew()
        if kind == "espresso":
            from . import espresso_maker
            oven = recipe.pop("oven", None)
            tier = recipe.pop("tier", "single-shot")
            prompts = recipe.pop("prompts", None)
            if oven is None or prompts is None:
                raise ValueError(
                    "espresso recipe needs oven= and prompts= overrides",
                )
            maker = espresso_maker.espresso_maker(tier, oven=oven, **recipe)
            return maker.pull(prompts)
        raise ValueError(
            f"unknown recipe kind {kind!r} in recipe {name!r}",
        )


def recipe_book(*, builtins: bool = False) -> RecipeBook:
    """Construct a fresh book, optionally preloaded with
    :data:`HYPERNIX_RECIPES`."""
    if builtins:
        return RecipeBook.from_builtins()
    return RecipeBook()
