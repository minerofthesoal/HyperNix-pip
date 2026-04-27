# Changelog

Full per-release notes for `hypernix`. The top-level `wiki/Home.md`
keeps a running "recent highlights" list; this page is the canonical
history. Semver-ish: minor bumps add features, patch bumps are bug
fixes and UX papercuts. Dates are `YYYY-MM-DD` for PyPI-published
releases; in-branch commits between releases are grouped under the
next release header.

## Legend

- ✨ new feature
- 🐛 bug fix
- 🛡️ UX / error-message polish
- 📚 documentation
- 🔧 internal / plumbing

---

## 0.52.5

🐛 **`smoke_alarm` is forgiving about kwargs.**  Reported by a
downstream ``chat_hypernix2.py`` script running on an i7 7th-gen
Surface Pro:

    TypeError: GasAlarm.__init__() got an unexpected keyword
    argument 'cpu_preset'

…and after the script's own ``except`` fell through to
``RadsAlarm``:

    TypeError: Alarm.__init__() got an unexpected keyword
    argument 'max_steps'

Real users type the kwargs they intuitively expect.  ``cpu_preset``
is the *function name* for resolving CPU presets in
``hypernix.freezer``, so reaching for ``GasAlarm(cpu_preset=…)``
is the natural call.  Same for ``max_steps`` as a hard cap on
``recommended_steps()``.

Fix:

* **Base `Alarm` dataclass** gains three forgiving kwargs:
  ``max_steps: int | None``, ``cpu_preset: str | CPUPreset``,
  ``gpu_preset: str | GPUPreset``.  Every subclass
  (`RadsAlarm` / `GasAlarm` / `ModernAlarm`) inherits them, so
  none of them raise ``TypeError`` anymore on those kwargs.
* **`Alarm.recommended_steps()`** now caps the natural
  recommendation at ``self.max_steps`` when set (a CAP, not a
  target — recommendations below ``max_steps`` are unaffected).
* **`GasAlarm.__post_init__`** resolves a ``cpu_preset`` string
  into ``self.cpu`` via ``hypernix.freezer.cpu_preset``, and a
  ``gpu_preset`` string into ``self.gpu``.  An explicit
  ``cpu=`` / ``gpu=`` object takes precedence.  Pre-built
  ``CPUPreset`` / ``GPUPreset`` objects passed via the alias
  also work.
* **`AutoAlarm`** mirrors the same kwargs and forwards
  ``max_steps`` through ``_common_kwargs`` so the picked tier
  honours the cap.

🌶️ **Generational CPU aliases in `hypernix.freezer.cpu_preset`.**
``"i7_7th_gen"`` (the user's exact string) used to return
``None``.  Added a generation-family map so the natural-feeling
aliases resolve to a representative SKU:

* ``i7_7th_gen`` → ``i7-7700hq``
* ``i7-12th-gen`` → ``i7-12700h``
* ``i9-12th-gen`` → ``i9-12900k``
* ``i9-14th-gen`` → ``i9-14900k``
* ``ultra-7`` / ``core-ultra`` → ``core-ultra-7-155h``
* ``ultra-9`` → ``core-ultra-9-185h``
* …plus full coverage of i5 / i7 / i9 11th – 14th gen, Core
  Ultra Series 1 + 2.

Direct SKU lookups (``"i7-7700hq"``) still take the fast path —
the alias map is only consulted on a primary miss.

🛡️ **27 new regression tests** in ``tests/test_v052_5.py``
covering both lines from the user's repro, ``max_steps`` cap
semantics (no-op when natural rec is below the cap, ignores 0 /
None, hard-caps when smaller), explicit ``cpu_preset`` / 
``gpu_preset`` resolution, explicit-``cpu=`` precedence, every
generational alias, ``AutoAlarm`` forwarding, and kwarg
acceptance on every tier.

---

## 0.52.4

🐛 **`CodeOven.chat` no longer crashes with ``ValueError: too many
dimensions 'str'``.**  Reported on a downstream notebook running
the published wheel: a chat turn died deep inside
``torch.tensor([input_ids], dtype=torch.long, ...)`` because the
tokenizer's ``apply_chat_template`` returned a plain rendered
string instead of token IDs (some tokenizers ignore
``tokenize=True``).  ``list("hello world")`` produced
``['h', 'e', 'l', ...]``, and torch quite reasonably refused to
build a long tensor out of single-character strings.

The fix lives in two places:

* **New :meth:`CodeOven._coerce_token_ids` helper.**  Accepts
  every legal shape ``apply_chat_template`` is allowed to return
  and normalises into a flat ``list[int]``:

    * a plain ``str`` → re-encoded through ``self._encode``,
    * a 1-D / 2-D ``torch.Tensor`` → flattened then ``int(x)``-cast,
    * a ``BatchEncoding``-like object exposing ``.input_ids`` →
      recurses into the input-ids field,
    * ``list[int]`` / ``tuple[int, ...]`` → passthrough,
    * batched ``list[list[int]]`` → take the first batch,
    * ``list[str]`` (the buggy shape) → return ``None`` so the
      caller falls through to the cookbook / plain transcript
      path instead of crashing.

  The ``apply_chat_template`` call is also wrapped in a try /
  except so a tokenizer that simply raises is treated identically
  to a tokenizer that returns garbage — both fall through to the
  cookbook path.

* **Defensive guard in :meth:`CodeOven._run`.**  Coerces ``str``
  / ``torch.Tensor`` / generic-iterable inputs the same way as
  ``_coerce_token_ids`` and raises a clear ``TypeError("_run
  expected list[int] for input_ids; got …")`` if anything still
  slips through, instead of bubbling up the cryptic torch error.

🛡️ **19 new regression tests** in ``tests/test_v051_4.py``:

* The headline bug — chat does not raise ``too many dimensions
  'str'`` when the tokenizer's ``apply_chat_template`` returns a
  string.
* 1-D tensor return / 2-D batched tensor return /
  ``BatchEncoding``-like return / ``list[str]`` fallback.
* ``_coerce_token_ids`` unit coverage for str / list[int] /
  tuple[int] / 1-D Tensor / 2-D Tensor / empty Tensor / empty
  list / batched list / BatchEncoding-like / list[str] /
  unrecognised object.
* ``_run`` defensive guard accepts string and tensor inputs via
  coercion and raises ``TypeError`` with a useful message on a
  truly unrecoverable input.

---

## 0.52.3

🔧 Auto version bump from CI (no code changes vs 0.51.3).

---

## 0.51.3

✨ **`hypernix.quantize` rewrite — full llama.cpp catalog.**

The 6-type alias dict from 0.51.2 grew into a structured 30-entry
``QUANT_CATALOG`` of frozen ``QuantSpec`` dataclasses, one per
distinct llama-quantize target type, with bits-per-weight,
category, size factor (relative to fp16), human-readable notes,
and a ``recommended`` flag for the curated short-list.

* **Floats:** ``F32``, ``F16``, ``BF16``.
* **Legacy quants:** ``Q4_0``, ``Q4_1``, ``Q5_0``, ``Q5_1``,
  ``Q8_0``.
* **K-quants:** ``Q2_K``, ``Q2_K_S``, ``Q3_K_S``, ``Q3_K_M``,
  ``Q3_K_L``, ``Q4_K_S``, ``Q4_K_M``, ``Q5_K_S``, ``Q5_K_M``,
  ``Q6_K``.
* **IQ-quants (newer, importance-matrix friendly):** ``IQ1_S``,
  ``IQ1_M``, ``IQ2_XXS``, ``IQ2_XS``, ``IQ2_S``, ``IQ2_M``,
  ``IQ3_XXS``, ``IQ3_XS``, ``IQ3_S``, ``IQ3_M``, ``IQ4_NL``,
  ``IQ4_XS``.

49 aliases (incl. the original ``q4km`` / ``q5km`` shortcuts and
the dash-form ``q4-k-m``) all resolve through the catalog.  The
old ``QUANT_TYPES`` dict is preserved unchanged at the alias
layer — pre-0.51.3 callers keep working.

New helper API:

* ``quant_recommended()`` — curated short-list (F16, Q8_0,
  Q6_K, Q5_K_M, Q4_K_M).
* ``quant_by_category("float" | "legacy" | "k" | "iq")`` — every
  spec in a category, sorted ascending by bpw.
* ``quant_for_size(target_size_bytes, fp16_size_bytes)`` —
  picks the largest non-float spec that fits the byte budget;
  falls back to the smallest IQ tier if nothing fits.
* ``quant_estimate_size(quant_type, fp16_size_bytes)`` —
  pure-arithmetic size estimate (no llama-quantize required).
* ``quant_resolve_spec(alias)`` — alias → ``QuantSpec`` lookup
  with case-insensitive matching and dash/underscore normalisation.
* ``quant_list_types()`` — sorted list of every canonical name
  in the catalog.

``QuantSpec``, ``QUANT_CATALOG``, and all six helpers are
re-exported at the top level (``hypernix.QuantSpec``,
``hypernix.QUANT_CATALOG``, ``hypernix.quant_recommended``,
etc.).

🛡️ **37 new tests** in ``tests/test_v051_3.py`` covering:

* Catalog completeness (≥ 30 specs, every alias resolves, every
  spec has a positive bpw / known category / non-empty notes).
* ``QuantSpec`` is a frozen dataclass.
* ``recommended()`` short-list contents.
* ``by_category()`` sorted-by-bpw ordering and unknown-category
  empty return.
* ``for_size()`` happy path, tiny-target fallback, zero-fp16
  rejection.
* ``estimate_size()`` math against expected ranges.
* ``resolve_spec()`` canonical / short-alias / dash-alias /
  case-insensitive / unknown-raises paths.
* Backward-compat: every pre-0.51.3 alias still resolves,
  ``quantize_gguf`` still raises ``ValueError`` on unknown
  targets.
* Top-level re-exports present and identity-equal to the
  underlying objects.

📚 **README + wiki refreshed.**  README's quant-aliases table and
the ``hypernix.quantize`` row now describe the new catalog.
``wiki/Quantization.md`` opens with a v0.51.3 callout, the type
table covers every recommended bpw tier, and a new "Catalog
helpers" section shows ``quant_recommended`` /
``quant_by_category`` / ``quant_for_size`` /
``quant_estimate_size`` / ``quant_resolve_spec`` in action.
README also broadens the headline tagline to mention both the
chat-tuned ``ray0rf1re/hyper-Nix.2`` (current default) **and**
the original ``ray0rf1re/hyper-nix.1`` (still fully supported).

---

## 0.51.2.1

🐛 **PyPI logo broken-image fix (carried over from 0.51.1.2).**  The 0.51.1 / 0.51.1.1
README pointed at
``https://raw.githubusercontent.com/minerofthesoal/hypernix-pip/main/assets/logo.png``
but that path returns 404 — the logo file is on the
``claude/pytorch-quantization-package-cJMQp`` working branch
and hasn't been merged to ``main`` yet, so the PyPI project page
showed the alt text + a broken-image placeholder.  Fixed by
pinning the URL to commit ``2d5eb37`` (the upload commit), which
is permanent regardless of branch lifecycle.  PyPI renders the
logo from this release onward.  Once the branch lands on
``main`` we can switch back to the pretty
``main/assets/logo.png`` URL.

---

## 0.51.1.1

🎨 **Logo file landed.**  ``assets/logo.png`` (1408 × 768 RGBA,
670 KB) and the transparent-background variant
``assets/logo1.png`` are now in the repo, so the raw-GitHub
``<img>`` tag at the top of the README renders on the PyPI
project page from this release onward.  Originals also kept
under ``assets/logo/`` for archival.  No code changes vs
0.51.1.

---

## 0.51.1

🐛 **Five bug-fix patches across three review passes** — one
by-hand source-read pass and two hand-driven testing passes,
including a memory-leak / Pascal-GPU / CPU-leak audit.

* **`bell.Bell._iter_from_ids` — stop-marker leak.**  The
  stop-sequence check ran *after* yielding the offending token,
  so consumers wired up via ``iter_chat`` / ``iter_complete``
  saw ``"<|im_end|>"`` (or whatever the stop string was) appear
  in their stream before generation halted.  Fix: check the
  *candidate* decoded text BEFORE yielding the token.

* **`countertop.Countertop._trim` — wipes the just-added user
  turn.**  Aggressive trimming with a small ``max_history_tokens``
  could ``del self.history[:2]`` when ``len(history) == 2``,
  leaving an empty history right before the call to
  ``oven.chat(messages)``.  Fix: cap the drop count at
  ``len(self.history) - 1`` so the most-recent message always
  survives.

* **`cookbook._HYPER_NIX_2` — dict-aliasing footgun.**
  ``_HYPER_NIX_2`` was constructed with
  ``role_prefixes=_CHATML.role_prefixes`` (and same for
  ``role_suffixes``), so the two templates literally shared the
  same dict object.  Mutating ``COOKBOOK.get("chatml")``'s
  prefix table silently corrupted ``hyper-nix.2``.  Fix: copy
  the dicts at construction time.

* **`flour.Flour.process` — crashes on tensor input.**  The
  guard ``if produced_ids:`` raised
  ``RuntimeError: Boolean value of Tensor with more than one
  value is ambiguous`` when callers passed a ``torch.Tensor``.
  Fix: normalise ``produced_ids`` to a plain ``list[int]`` at
  the top of ``process`` and switch the gating to a length
  check; tensors, numpy arrays, and one-shot generators now all
  work.

* **`pressure_cooker.UniversalCooker.select` — breaks Pascal
  (sm_61) GPUs.**  The selector unconditionally returned
  ``ProCooker`` (which inherits ``InductionCooker`` with
  ``fused=True`` + CUDA graphs) on any CUDA device, but fused
  AdamW and ``torch.cuda.CUDAGraph`` both require compute
  capability ≥ 7.0.  A 1080 / 1080 Ti / Titan Xp user calling
  ``universal_cooker(model.parameters())`` would crash with
  ``RuntimeError: fused=True requires CUDA capability >= 7.0``.
  Fix: new ``_is_pre_volta(device)`` helper; the selector now
  detects Pascal and forces ``fused=False`` (with
  ``foreach=_HAS_FOREACH``) on a plain ``InductionCooker``.

🛡️ **14 new regression tests** in ``tests/test_v051_1.py`` —
one per behavioural requirement of the fixes (stop-marker
absence in stream / token-callback / done-callback; trim
preserves freshest user; cookbook dicts are independent and
non-aliasing; flour accepts torch tensors / generators / empty
inputs; ``_is_pre_volta`` returns False on CPU and the Pascal
selector path forces ``fused=False``).

🎨 **Project logo wired in.**  ``assets/logo.png`` is now
referenced from the top of the README (with a raw GitHub URL so
PyPI renders it on the project page) and is shipped in the sdist
via ``MANIFEST.in``.  ``DEFAULT_REPO_ID`` and the ``Homepage``
URL also updated to point at ``ray0rf1re/hyper-Nix.2``.

🔧 **Memory-leak audit (CPU + Pascal-GPU paths).**  Manually
exercised ``deep_fryer.LightFry`` (fry / un_fry over 50 iters,
``torch.Generator`` and ``torch.Tensor`` object counts both
delta-zero), ``Bell.iter_complete`` (20 streaming runs,
delta-zero), ``CodeOven.chat`` (10 turns, delta-zero).  No leaks
introduced by the v0.51.0 chat surface.

Final: 621 tests pass, 1 skipped (matplotlib).

---

## 0.51.0

✨ **Chat-first release.** Five new modules + first-class support
for the new ``ray0rf1re/hyper-Nix.2`` chat checkpoint.

* **`hypernix.cookbook` — chat-template registry.**
  Different model families use wildly different prompt formats
  (ChatML, Llama 3 turn tags, Alpaca, Vicuna, plain ``role:
  content``) and getting one wrong silently makes a chat model
  behave like a base model.  ``cookbook`` ships every common
  template as a dataclass and resolves the right one from a
  short name or HF repo id::

      from hypernix.cookbook import COOKBOOK, for_model

      tmpl = for_model("ray0rf1re/hyper-Nix.2")  # picks "hyper-nix.2"
      prompt = tmpl.apply(messages, add_generation_prompt=True)

  Built-in templates: ``chatml``, ``hyper-nix.2`` (ChatML +
  HyperNix-flavoured default system prompt), ``llama3``,
  ``llama2``, ``alpaca``, ``vicuna``, ``plain``.  Wired into
  ``CodeOven._format_chat`` as the layer-2 fallback (after
  ``tokenizer.apply_chat_template`` if present, before the plain
  ``role: content`` last-resort) so a freshly-downloaded
  hyper-Nix.2 snapshot Just Works for chat without any extra
  configuration.

* **`hypernix.countertop` — multi-turn chat session.**
  Persistent workspace bound to an oven::

      from hypernix.old_oven import preheat
      from hypernix.countertop import Countertop

      oven = preheat("hyper-nix.2")
      chat = Countertop(oven, system="You are a helpful chef.")
      print(chat.say("How do I dice an onion?"))
      print(chat.say("And a shallot?"))
      chat.save("session.json")

  Auto-resolves the chat template from ``oven.repo_id``,
  optionally streams through a :class:`Bell`, optionally cleans
  replies through a :class:`Flour`, trims oldest turns when the
  rendered transcript exceeds ``max_history_tokens``, and
  round-trips to JSON for resumable sessions.

* **`hypernix.menu` — system-prompt presets.**
  Named registry of personas: ``default`` / ``concise`` /
  ``code-helper`` / ``judge`` / ``creative`` / ``chef`` /
  ``hyper-nix``.  Pairs with the ``persona=`` kwarg on
  ``countertop()`` so you can say
  ``countertop(oven, persona="judge")`` instead of pasting the
  judge prompt by hand.  Persists with ``Menu.save / Menu.load``.

* **`hypernix.bell` — streaming-token callback.**
  Wraps any oven exposing ``model`` + ``_decode`` + ``_format_chat``
  so generation streams a token at a time::

      bell = Bell()
      bell.on_token(lambda tok, idx: print(tok, end="", flush=True))
      bell.on_done(lambda full: print(f"\\n[done, {len(full)} chars]"))
      bell.stream_chat(oven, messages, max_new_tokens=128)

  Or pull tokens out of the iterator yourself::

      for tok in bell.iter_chat(oven, messages):
          ...

  ``stdout_bell()`` and ``file_bell(path)`` are ready-made
  variants.  Bells accept a ``flour=`` so live logits processing
  applies during streaming, not just at the end.

* **`hypernix.flour` — chat-quality logits processor.**
  *The reason hypernix's chat surface is "better than raw
  transformers for chatting".*  Bundles every chat-quality
  heuristic you'd otherwise wire by hand on top of vanilla
  transformers:
    * **repetition penalty** (OpenAI-style multiplicative),
    * **frequency penalty** (linear in count),
    * **presence penalty** (linear, once per unique token),
    * **no-repeat n-gram** blocking,
    * **bad-word / phrase** suppression,
    * **role-leak suppression** — strips
      ``<|im_start|>user`` / ``[INST]`` / ``user:`` tokens the
      assistant would otherwise hallucinate, and cuts the reply
      at any half-emitted next-turn marker,
    * **stop-sequence detection** on **decoded text** rather than
      raw token ids — so ``"<|im_end|>"`` works even when the
      tokenizer splits it into 3 BPE pieces.
  ``Flour.smart_default(template="hyper-nix.2")`` applies all of
  the above with values tuned for chat.  ``Flour.aggressive()``
  cranks up the penalties for models that loop a lot.
  ``Flour.off()`` is a no-op.

🌶️ **First-class support for ``ray0rf1re/hyper-Nix.2``.**

* New ``KNOWN_MODELS`` entry plus the aliases ``hyper-nix.2`` /
  ``hyper-nix2`` / ``hypernix2`` / ``hyper-nix`` / ``hypernix``,
  all routing to ``ray0rf1re/hyper-Nix.2``.  The chat-aware
  ``hyper-nix`` / ``hypernix`` short names now resolve to v2
  (was v1 in 0.50).
* ``DEFAULT_REPO_ID`` updated to ``ray0rf1re/hyper-Nix.2`` so
  ``preheat()`` with no args downloads the chat-tuned model.
* New ``ARCH_PRESETS["hypernix2"]`` / ``["hyper-nix.2"]`` for
  fresh-init from-scratch chat models with the same Llama-shape
  config as v1.
* ``CodeOven.repo_id`` is now persisted on the oven so
  ``_format_chat`` can resolve the cookbook template
  automatically — no more ``role: content`` fallback for v2.

🛡️ **56 new tests** in ``tests/test_v051.py``: cookbook templates
(ChatML / Llama 2/3 / Alpaca / Vicuna / plain + ``for_model``
resolver), menu CRUD + persistence, bell streaming with a stub
oven (no real weights needed), countertop session lifecycle
(say / reset / trim / save / load / persona / flour-cleanup),
flour logits processor (repetition penalty math, no-repeat n-gram
ban, role-leak detection, decoded-text stop-match,
``clean_reply`` after generation), and hyper-Nix.2 wiring (alias
table, default repo id, oven ``repo_id`` plumbing).

Final: 607 tests pass, 1 skipped (matplotlib).

---

## 0.50.0

✨ **Four new kitchen modules.**

* **`hypernix.whisk` — checkpoint averaging.**
  Three modes for blending N saved snapshots into one set of
  weights, all working on plain ``dict[str, Tensor]``:
    * ``swa_average(items)`` — uniform Stochastic Weight Average
      (mean across all N).
    * ``ema(items, decay=0.99)`` — exponential moving average;
      later inputs weighted ``decay ** (N-1-i)``.
    * ``geometric_mean(items)`` — element-wise geometric mean
      (clamped at ``eps`` for non-positives).
  Inputs may be in-memory state dicts **or** paths to ``.pt`` /
  ``.safetensors``.  Mismatched keys are intersected with a
  warning unless ``strict=True``.  Integer tensors are taken from
  the first checkpoint (averaging them is meaningless).
  ``whisk(items, mode="swa"|"ema"|"geometric-mean")`` is the
  one-shot factory; ``whisk_to_snapshot(items, out_dir, ...)``
  whisks **and** writes a full HF-style snapshot directory in one
  call (best-effort config recovery from a sibling
  ``config.json``).

* **`hypernix.cutting_board` — train / val / test splitting.**
    * ``CuttingBoard(train_ratio, val_ratio, test_ratio,
      seed, shuffle)`` — deterministic random split.  Ratios are
      renormalised if they don't sum to 1.0; ``test_ratio=0`` is
      allowed (you'll get train + val and an empty test slice).
      ``.slice(source)`` returns ``{"train": [...], "val": [...],
      "test": [...]}`` from a corpus path or any iterable of
      strings; ``.slice_to_files(out_dir, suffix=".txt")`` writes
      each slice to its own file.
    * ``StratifiedBoard(label_key="label")`` — stratified split
      that preserves the class distribution from labelled records
      (each unique label is shuffled and split independently,
      then per-class slices are concatenated and shuffled once
      more so the output isn't grouped by class).
    * Convenience: ``cutting_board(source, train=…, val=…,
      test=…, seed=…)`` returns the slice dict directly when
      ``source`` is given, else returns a configured board.

* **`hypernix.apron` — RNG-state guard.**
  An apron protects what's underneath while you cook.  Captures
  every random-number source hypernix or your script might touch
  (Python ``random``, NumPy if installed, PyTorch CPU, every
  CUDA device's RNG) and restores it on exit.  Two ways to use
  it:

      with apron(seed=0):
          # everything inside is deterministic; nothing leaks out.
          random.shuffle(my_list)
          torch.randn(10)

      a = Apron.snapshot(seed=0)
      ...
      a.restore()

  Use it any time a step in your pipeline wants to perturb the
  global RNG (e.g. an evaluator that uses ``torch.randn`` for
  sampling) without leaking the perturbation back to the caller.

* **`hypernix.recipe_book` — named-config registry.**
  Save 12-key brew recipes once, refer to them by name forever.
  ``RecipeBook.add(name, recipe)`` / ``get(name)`` /
  ``remove(name)`` / ``save(path)`` / ``load(path)``.
  ``cook(name, **overrides)`` looks up, applies overrides on top,
  and dispatches by ``kind`` field:
    * ``"instant_pot"`` → ``hypernix.instant_pot.brew``
    * ``"cold_brew"`` → ``hypernix.coffee_maker.cold_brew(...).brew()``
    * ``"espresso"`` → ``hypernix.espresso_maker.espresso_maker(...).pull(prompts)``
  ``RecipeBook.from_builtins()`` ships a handful of ready-to-use
  recipes (``evaluator-quick``, ``ftune-pascal``,
  ``nightly-coldbrew``, ``espresso-eval``).

🐛 **Three bug-fix passes across the codebase.**

Pass 1 — runtime correctness:

* `pressure_cooker._adamw_multitensor`: the private
  ``torch.optim._functional.adamw`` API is **not** stable across
  torch 1.13 → 2.x.  Now wrapped in a try/except (both
  ``ImportError`` on the import and ``TypeError`` at call time),
  with a graceful fall-through to a hand-written
  ``_adamw_scalar_for(params, group)`` so the optimizer keeps
  working on torch versions where the private name was renamed
  or had its signature changed.
* `deep_fryer.LightFry` / `HeavyFry`: replaced the global
  ``torch.manual_seed`` mutation with a per-parameter
  ``torch.Generator(device=flat.device)`` keyed on
  ``self.seed + sum(map(ord, pname))``.  Two consecutive fries
  with the same seed now produce identical noise **without** also
  perturbing the user's training RNG state.
* `food_processor.SliceBlade`: previously accepted any
  ``overlap_chars`` and produced a zero-length step (infinite
  loop) when ``overlap_chars >= slice_chars``.  Now raises
  ``ValueError`` at chunk time with a clear message.
* `industrial_range._parse_pairwise`: the pairwise parser used
  to insist that "tie/tied/equal" be the first character of the
  judge response.  Real judges write things like "Tied — both
  responses are correct" or "Equal quality" — those now correctly
  return ``"T"``.

Pass 2 — UX / error-message clarity:

* `instant_pot.brew`: when ``recipe["dataset"]`` doesn't exist on
  disk, the old behaviour was a confusing ``KeyError`` deep inside
  ``train`` after a 30-second model download.  Now fast-fails with
  ``FileNotFoundError("instant_pot.brew: dataset … does not
  exist")`` before the download starts.
* `microwave._preheat`: a string repo id like ``"nix2.5"`` that
  happened to coincide with an existing local directory was being
  treated as a path even when the directory didn't contain a
  ``config.json``.  The path branch now also requires
  ``config.json`` before short-circuiting the Hub download.
* `cake_pan` `step_timeout` handler: the SIGALRM handler used to
  raise ``BakeOff`` directly without first restoring pristine
  state, leaving the model with a half-applied gradient step.
  Now calls ``self.roll_back()`` before raising.

Pass 3 — discovered during smoke-testing the new modules:

* `apron.Apron.snapshot`: the previous implementation seeded the
  RNGs **before** capturing state, so the ``with apron(seed=42):``
  context-manager exit restored to the seeded state instead of
  the caller's pre-call state.  Now snapshots first, then
  optionally seeds, so exit truly returns the caller to whatever
  they were doing before.

🛡️ **36 new tests** in ``tests/test_v050.py`` covering all four
new modules plus regressions for every bug fix above.

---

## 0.49.0

✨ **`hypernix.lunchbox` — consistent-schema dataset packager.**
Reported: the Hub dataset viewer on a hypernix-built
``ray0rf1re/eval`` dataset crashed with

  Error code: StreamingRowsError
  Exception:  CastError
  Message:    Couldn't cast … because column names don't match

The actual column layout (11 cols incl. ``latency_s``,
``keyword_score``, ``pipeline_meta``) didn't match the
``huggingface`` metadata blob embedded inside the Parquet shards
(only 4 cols).  That happens when shards written at different
schema versions get concatenated.  ``Lunchbox`` makes that
impossible by construction:

  * ``add(**fields)`` collects plain dicts.
  * ``normalize()`` fills every missing cell with ``None``.
  * ``validate()`` rejects mixed non-None types per column
    (str+float in the same column is a Parquet write error).
  * ``pack(path)`` routes through
    ``datasets.Dataset.from_list(...).to_parquet(...)`` so the
    embedded ``huggingface`` metadata is always in sync with the
    actual column set.
  * ``push_to_hub(repo_id)`` does the same for direct uploads.
  * ``Lunchbox.for_eval()`` pre-loads the recommended eval-dataset
    schema (``EVAL_SCHEMA``: id / category / difficulty / tier /
    prompt / reference / model_response / keyword_score /
    latency_s / variant / pipeline_meta).
  * ``pack_jsonl(path)`` writes the same normalised rows as JSON
    Lines — no pyarrow / datasets install required.

``datasets`` is a **lazy** dependency: the first pack / push call
routes through :func:`hypernix.deps.ensure`, respecting
``HYPERNIX_AUTO_INSTALL=0``.

🧪 **+31 new coverage tests** (`tests/test_coverage_beef.py`)
touching gaps in the existing per-module suites: lunchbox
edge cases (empty box, 10 000-row normalise, unicode,
duplicate rows, mixed-types rejection, push-URL shape),
pressure_cooker (amsgrad wiring, closure-form step, foreach
state persistence, repr text), deep_fryer (frozen-param
handling, multi-cycle save/restore, HeavyFry fries frozen
weights), cake_pan (CPU memory-guard no-op, oven-all-bad
zero count, step_count monotonicity), freezer presets (every
CPU has AVX, every GPU has positive bandwidth, lookup-key
normalisation), shakers (determinism, rate=0 identity, empty-
line passthrough), smoke_alarm (time_hours math, save_every=0
silence, unknown-preset error content), plus an end-to-end
evaluator→Lunchbox→JSONL→Table round trip.

Full suite 515 passed, 1 skipped (matplotlib).

---

## 0.48.0

✨ **`pressure_cooker` rewrite — 4 device-tuned tiers + universal
selector + 5 new knobs.**  The base :class:`PressureCooker` keeps
the v0.47 API exactly (warmup / plateau / cosine cooldown + optional
lookahead); on top of it ship four specialised classes and a
selector:

* **`StovetopCooker`** (CPU tier 1) — minimum-memory path:
  ``foreach=False``, ``fused=False``, no AMP.  Use on RAM-
  constrained boxes and old Intel Macs.
* **`ElectricCooker`** (CPU tier 2) — ``foreach=True`` multi-tensor
  path (torch ≥ 1.12) for fast CPU updates when you have the RAM.
* **`InductionCooker`** (GPU tier 1) — ``foreach=True`` +
  ``fused=True`` AdamW kernel on torch ≥ 2.0 + first-class
  ``torch.cuda.amp.GradScaler`` integration.  Pass
  ``grad_scaler=torch.cuda.amp.GradScaler()`` and the cooker
  unscales, inf-skips, and advances the scaler automatically.
* **`ProCooker`** (GPU tier 2) — InductionCooker plus optional
  CUDA-graph capture via ``warmup_graph(step_fn)`` /
  ``replay_graph()`` for a material speedup on fixed-shape steps.

✨ **`universal_cooker(params, prefer_speed=True)`** — probes the
first parameter's device and returns `ElectricCooker` on CPU (or
`StovetopCooker` with `prefer_speed=False`), `ProCooker` on CUDA
(or `InductionCooker`).

✨ **New base-class knobs (opt-in, all backward-compatible):**

* ``grad_scaler=`` — unscales, skips on inf, advances the scaler.
* ``grad_accum_steps=N`` — only the N-th ``step()`` runs the
  optimizer; earlier calls just bump the counter.
* ``foreach=True | False | None`` — selects the multi-tensor path.
* ``fused=True | False | None`` — selects the fused CUDA kernel
  when torch supports it (torch ≥ 2.0, all params on the same
  CUDA device).
* ``amsgrad=`` — forwarded to the inner AdamW.

✨ **Factory convenience:** ``pressure_cooker(params, tier="...")``
accepts any of ``"pressure-cooker"`` / ``"stovetop"`` / ``"electric"``
/ ``"induction"`` / ``"pro"``.  Unknown tiers raise
``ValueError`` with the full list.

🔧 `describe()` method on the base class returns a dict of the
active knobs for logging / provenance.

Tests (`tests/test_pressure_cooker_v048.py`, 19 new):

* v0.47 signature + LR schedule + phase labels unchanged (backward
  compat).
* Every tier's defaults (`foreach`, `fused`, `grad_scaler`) verified.
* Universal selector picks Electric on CPU (fast) or Stovetop
  (safe).
* Grad-accumulation: N-1 no-op steps then one real update.
* GradScaler: skip-on-inf path *and* update-on-finite path via a
  fake scaler so we don't need CUDA to test.
* Scalar vs. foreach inner path produce the same weight update to
  within fp rounding.
* Factory tier lookup + error paths.
* Lookahead slow-weight population survives the rewrite.

Full suite 469 passed, 1 skipped (matplotlib).

Docs: README subsystem table row rewritten to list all five tiers,
wiki/Home.md version history picks up 0.48.0 + backfills 0.47.1.

---

## 0.47.0

✨ **`deep_fryer`** — 2-tier model-weight perturbation.  `LightFry`
(t1): 2% of elements, 0.1× param-std Gaussian noise — use as a
regulariser between epochs.  `HeavyFry` (t2): 30% of elements,
0.5× noise, plus configurable zero-rate for sparse destruction —
use to generate deliberately-bad-model negatives for training a
judge, or for robustness testing.  Both are in-place and reversible
via `save_pristine()` / `un_fry()`.

✨ **`cake_pan`** — hybrid CPU + GPU training guard.  Wraps each
step in `bake(fn)` which catches NaN / Inf in the loss (and
optionally gradients), enforces a wall-time watchdog via SIGALRM,
monitors GPU memory and offloads matching modules when pressure
passes `free_gb_trip`, and rolls back to the last pristine state
on trouble — raising `BakeOff(reason, step)` for the caller.
`CakePan.oven(batches, step_fn)` is the fire-and-forget loop
wrapper with automatic retry + skip.

✨ **CPU preset expansion — now 48 total** (was 16, **×3**).
Adds 7th-gen i5 (7200U, 7300HQ, 7400, 7600K), i9 (7900X, 7980XE);
11th-gen i5 (11400, 11600K, 11320H), i9 (11900K); 12th-gen i5
(12400, 12500, 12600K), i9 (12900K, 12900HX); 13th-gen i5 (13400,
13500, 13600K), i9 (13900K, 13900HX); 14th-gen i5 (14400, 14500,
14600K), i9 (14900K, 14900KS, 14900HX); Core Ultra 5 Series 1
(125H, 135H, 228V), Series 2 (225K, 235K); Core Ultra 9 Series 1
(185H).

✨ **GPU preset expansion — now 71 total** (was 20, **×3.5**).
Adds the rest of GTX 10 (1050, 1050 Ti, 1060, 1070, 1070 Ti), GTX
16 (1650, 1650 Super, 1660, 1660 Super), RTX 20 (2060, 2060 Super,
2070, 2070 Super), full RTX 30 (3050, 3060, 3060 Ti, 3070, 3070
Ti, 3080, 3090, 3090 Ti), full RTX 40 (4060, 4060 Ti 8/16GB, 4070,
4070 Ti, 4080, 4090), full Blackwell consumer RTX 50 (5070, 5070
Ti, 5080, 5090).  **Apple Silicon** via MPS: M1 / M1 Pro / M1 Max
/ M1 Ultra, M2 / M2 Pro / M2 Max, M3 / M3 Pro / M3 Max, M4 / M4
Pro / M4 Max.  **AMD**: Radeon RX 6800 XT / 6900 XT / 7900 XT /
7900 XTX, Instinct MI250X / MI300X.  Non-CUDA devices (Apple,
AMD) use the `(0, 0)` sentinel for `compute_capability`.

Tests (`tests/test_v047_deep_fryer_cake_pan_presets.py`, 76 tests):
every fryer tier + pattern filter + unknown-tier error; cake_pan
loss/grad NaN detection, snapshot writes, oven retry counting,
pristine rollback; every new CPU preset spec + preset count bound;
every new GPU preset vram + count bound; compute-capability
sentinels for Apple + AMD.  **Full suite 447 passed**, 1 skipped
(matplotlib).

---

## 0.46.1

🛡️ **`nix` short-name fallback chain.**
`KNOWN_MODELS["nix"]` now points at `Nix-ai/Nix-2.7a` (was
`ray0rf1re/Nix2.5`).  `download_model("nix")` consults a new
`FALLBACK_CHAINS` registry and tries in order:
`Nix-ai/Nix-2.7a` → `Nix-ai/Nix2.6-mm` → `ray0rf1re/Nix2.5`,
falling through only when an earlier candidate 404s / is gated /
hits a network error.  Explicit `org/repo` ids bypass the chain.
Six regression tests in `tests/test_nix_fallback.py` cover the
happy path, fallthrough, exhaustion, and explicit-repo bypass.

---

## 0.46.0

✨ **`salt_shaker`** — 3-tier gentle data augmentation.

- `FromTheBag` (t1): per-character substitution at `rate`, preserves
  line length.
- `HandCrusher` (t2): adjacent-token swaps at `rate`.
- `PoshSaltDish` (t3): independent drop / duplicate / swap rates
  with word-level granularity.

All three share a `Shaker` base, a deterministic `seed`, and plug
into `sink.Sink.pour(...)` like the pans.

✨ **`pepper_shaker`** — 3-tier sharp perturbations.

- `SmallShaker` (t1): random token masking with configurable
  `mask_token` (default `[MASK]`).
- `Dish` (t2): typo injection (drop / duplicate an internal char);
  preserves first + last character so words stay recognisable.
- `TallHandmade` (t3): negation injection; prepends `negator`
  (default `"NOT"`) at `rate`.

✨ **`torch_compat`** — portability shim for **old Intel Macs with
torch 1.13**.  Provides version-gated fallbacks for
`torch.nn.RMSNorm` (needs ≥ 2.4) and
`torch.nn.functional.scaled_dot_product_attention` (needs ≥ 2.0).
`HyperNixModel` + `NanoNanoModel` now route through the shim, so
identical outputs on modern and legacy torch.

✨ **`[legacy-torch]` extra** — companion dep pins that co-install
with torch 1.13: `numpy<2`, `safetensors>=0.3.1`,
`huggingface-hub>=0.16`, `tqdm>=4.64`, `sentencepiece>=0.1.99`.
Does **not** relax the main torch pin; you must install torch 1.13
first yourself.  See `scripts/install_macos_legacy.sh`.

🔧 **`scripts/install_macos_legacy.sh`** — one-shot installer that
pins torch 1.13.1 CPU, installs hypernix with `--no-deps`, then
pulls the legacy-torch extras, and smoke-tests
`torch_compat.describe()`.

📚 New `wiki/macOS-legacy.md` documents what works, what doesn't,
and how to size training on old Intel Macs (`OldFreezer` + a
`GasAlarm(preset="i7-7660u")`-style budget).

---

## 0.45.3

🛡️ **`smoke_alarm.GasAlarm` accepts `preset=`.** One-string shortcut
that resolves against `GPU_PRESETS` first, then `CPU_PRESETS`. Works
on the class (`GasAlarm(..., preset="i7-7700hq")`), on the factory
(`gas_alarm(..., preset="h100")`), and on the selector
(`auto_alarm(..., preset="rtx-3080-ti")`). Unknown names raise
`ValueError` with the full list of valid presets.

🛡️ Explicit `cpu=` / `gpu=` instances still win over a conflicting
`preset=` hint — no silent overwrite.

🔧 Shared `_resolve_preset` helper in `smoke_alarm.py`.

## 0.45.2

🐛 **Every pan accepts `context_length=` and `max_chars=`.** Reported:
`FryingPan(context_length=CONTEXT_LEN)` raised a bare `TypeError`.
Both are now keyword-only fields on the `Pan` base class; when set,
lines are truncated to fit. `context_length` is treated as
`max_chars = context_length * 4` (English-BPE heuristic); the direct
`max_chars=` wins when both are set. For precise chunking by tokens
use `hypernix.food_processor` instead.

## 0.45.1

🐛 **Pan positional-argument fix.** `Pan` inherited `name: str` as a
dataclass field, so `Skillet(src, "instruct")` silently set
`name="instruct"` and left `mode="chat"`. Fix: `name` is now a
`typing.ClassVar` on every pan — still the pan's label, no longer
part of `__init__`. `GrillPan._seen` (internal dedupe state) marked
`init=False`.

🛡️ `pick_pan` error messages now list valid tiers / valid kwargs
instead of raising `KeyError` or cryptic `TypeError`.

## 0.45.0

✨ **Espresso, blender, toaster, food_processor, smoker** — five new
appliances, each 4 tiers. Shared interface per module.

✨ **+3 microwave tiers** — now `defrost` (preheat-only) / `low_zap`
(deterministic one-liner) / `zap` (existing) / `high_zap`
(long-temp draft) / `chat_zap` (existing). Plus `reheat(oven,
prior_output)` for continuation without rebuild.

✨ **+2 coffee_maker tiers and one new type.**
`FrenchPressMaker` (batch), `PercolatorMaker` (cyclic with optional
convergence), and a new `ColdBrewMaker` (long single brew with
mandatory JSON checkpoints, resumes cleanly after a crash).

✨ **CLI `hypernix brew recipe.json`** — runs `instant_pot.brew`
from a JSON recipe. Supports `--set KEY=VALUE` overrides with JSON
literals.

📚 `wiki/Kitchen.md` gets full sections for every new appliance.

## 0.44.0

✨ **Kitchen modules + pressure_cooker optimizer.** Seven new
top-level modules (pans, microwave, table, sink, instant_pot,
coffee_maker, pressure_cooker) covering preprocessing, throwaway
inference, log inspection, file output, end-to-end pipelines,
scheduled repetition, and a custom optimizer.

✨ `pressure_cooker` — `torch.optim.Optimizer` subclass: AdamW +
three-phase LR schedule (linear warmup → plateau → cosine cooldown)
+ Zhang-et-al-2019 Lookahead "pressure seal". No separate scheduler
object; the LR lives inside the optimizer.

📚 README gains a **"Who this is actually for"** section framing the
package around the solo-GPU / consumer-card / QLoRA-to-Hub workflow,
with an explicit disclaimer that `train()` is a smoke-tester, not a
production trainer. New `wiki/Kitchen.md`.

## 0.43.0

✨ **`smoke_alarm`** — four-tier training-step planner + mid-run
monitor. `RadsAlarm` (constants, lightest), `GasAlarm` (CPU/GPU
presets), `ModernAlarm` (warmup-measured), `AutoAlarm` (selector).

✨ **16 CPU presets** (`hypernix.freezer.CPU_PRESETS`): i7 7th gen
(7660U / 7700HQ / 7700K), 11th–14th gen K/H/HX, Core Ultra Series 1
(Meteor / Lunar Lake), Series 2 (Arrow Lake, AVX10).

✨ **20 GPU presets** (`hypernix.freezer.GPU_PRESETS`): Hopper
(H100/H200), Ampere workstation (A4500–A6000), RTX PRO Ada +
Blackwell, RTX 4070 Ti Super / 4080 Super, RTX 3080 Ti, Turing
consumer (1660 Ti, 2080, 2080 Super, 2080 Ti), Pascal (1080, 1080 Ti).

📚 New `wiki/Alarms.md` with both preset tables.

## 0.42.0

✨ **`new_range` / `old_range` / `industrial_range`** — three
sophistication tiers of labeling rubrics that drop into
`mediocre_fridge.collect_responses_from(label_rule=...)`.

- `new_range` — zero-dep first-fail rubric (is_empty, is_refusal,
  math_lacks_digit, is_repetition).
- `old_range` — weighted-mean scored rubric with `None` = "no
  opinion", any-rule-at-0 short-circuits to BAD, references / keywords
  / stopword-filtered overlap built in.
- `industrial_range` — LLM-as-judge wrapper around any CodeOven;
  pointwise + pairwise with caching.

📚 New `wiki/Ranges.md`.

## 0.41.0

✨ **CUDA 6.1 / Pascal support.** `compute_capability`, `is_pascal`,
`pascal_safe_dtype` (fp32 on CPU, fp16 on Pascal / Volta / Turing,
bf16 on Ampere+), `pascal_mode_hints` (one-stop dict of recommended
settings for sm_61).

✨ **`examples/train_hypernix_1_5_gtx1080.py`** — HyperNix 1.5,
verified 92,130,048 params, trains on an 8 GB Pascal card via
`auto_freezer` + `flash_freezer(slow=True)`.

📚 New `wiki/Pascal.md` with a full sm_61 playbook.

## 0.40.0

✨ **`freezer` module** — VRAM manager. `OldFreezer` (8 – 10 GB,
batch=1, fp16, empty_cache each step), `NewFreezer` (11 GB+, batch=8,
fp32/bf16), `FlashFreezer` (OOM-safe retry wrapper with exponential
backoff, wait-for-free-GB, and optional slow-mode that halves
`current_batch_size` on each retry).

📚 New `wiki/Freezer.md`.

## 0.36.0

✨ **`old_fridge` / `mediocre_fridge` / `new_fridge`** — memory
housekeeping (freeze/unfreeze/parameter_stats), judge-training dataset
synthesis, and training-curve plotting.

✨ `examples/train_hypernix_0_1_5_evaluator.py` — end-to-end example
wiring ovens + all three fridges.

📚 New `wiki/Fridges.md`.

## 0.35.0

✨ **Gemma 4, Qwen 3.5 & 3.6, GLM 5.x, Nix collection presets.** New
entries in both `ARCH_PRESETS` (for `new_oven`) and `KNOWN_MODELS`
(for short-name resolution). Config knobs verified against the actual
HuggingFace repos.

## 0.34.0

✨ **AutoModel fallback.** `load_snapshot` routes any non-HyperNix
`model_type` (Gemma, Phi, DeepSeek, GLM, GPT-OSS, …) through a thin
`transformers.AutoModelForCausalLM` wrapper. New ARCH_PRESETS covering
those families.

## 0.33.0

✨ **Windows + macOS support.** Cross-platform `doctor`, path
handling, `llama-quantize` resolution.

✨ **Python 3.13** support (sentencepiece 0.2.1 floor).

✨ **Runtime auto-install.** `HYPERNIX_AUTO_INSTALL` env var (default
on) lets missing runtime deps be installed lazily; `hypernix doctor
--fix` makes it explicit.

## 0.32.1

🐛 Fall back to the slow tokenizer when the `tokenizers` crate is too
old to decode a newer tokenizer.json.

## 0.32.0

✨ **torch 2.7+** (incl. CUDA 11.8 builds).

✨ One-shot PyPI publish via GitHub Actions Trusted Publishing.

## 0.31.0

✨ **Chat REPL.** `hypernix chat --repo-id <short-name>` plus
`CodeOven.chat(turns, ...)`.

✨ **Nano-nano / Nano-mini / nano-nano-927** family — new entries in
`KNOWN_MODELS`.

## 0.30.0

✨ **`old_oven` code-generation wrapper.** `preheat`, `CodeOven`,
`bake_code`, `fill_middle`, `save_pt` / `load_pt`. `--auto-oven`
top-level CLI shortcut.

## 0.21.0

✨ Download every file the model needs — not just weights — so the
output directory is a self-contained snapshot.

## 0.2.0

✨ First subcommand-based CLI. `train` module scaffold. Fixed
`tokenizer.ggml.merges` in GGUF output.

---

## Upgrading

`hypernix` follows no breaking-change policy yet. Patch releases
(`0.45.x`) are always safe to upgrade — they only fix bugs, UX
papercuts, or improve error messages.

Minor releases (`0.N.0`) add features. The usual gotcha is renamed
kwargs from the UX-polish patches above; when in doubt, check the
signature:

```python
import inspect
from hypernix import smoke_alarm, pans

print(inspect.signature(smoke_alarm.GasAlarm))
print(inspect.signature(pans.FryingPan))
```

## Contributing changelog entries

New features should land with a one-paragraph entry at the top of
this file, grouped by emoji legend. Patch releases get a couple of
bullet points; minor releases get a section per subsystem touched.
Keep the tone utilitarian — what changed, how the caller notices,
what to do instead if an old call stopped working.
