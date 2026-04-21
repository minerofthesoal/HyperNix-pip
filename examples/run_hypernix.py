"""Portable runner for ray0rf1re/hyper-nix.1 in pure PyTorch.

The bootstrap flow (run once on a machine with network access):

    pip install hypernix
    python run_hypernix.py            # downloads the HF snapshot,
                                      # saves ./hypernix.pt, prints output

After that, the directory contains three self-contained files:

    run_hypernix.py       # this script
    hypernix_run.json     # config (edit prompt/sampling/device here)
    hypernix.pt           # torch.load-able bundle (weights + config)

Copy those three anywhere and re-run ``python run_hypernix.py`` — the
script detects the bundle, skips the download, loads straight into a
``CodeOven``, and runs your prompt. No HuggingFace call, no network.

Configuration:
    Edit ``hypernix_run.json`` in place (see comments in that file).
    Or pass ``--config /path/to/other.json``.

Modes:
    "complete"  -> oven.complete(prompt)
    "fill"      -> oven.fill(fill_prefix, fill_suffix)    (FIM)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_config(config_path: Path) -> dict[str, Any]:
    with config_path.open(encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg.pop("_comment", None)
    return cfg


def _save_config(config_path: Path, cfg: dict[str, Any]) -> None:
    config_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def _get_oven(cfg: dict[str, Any], config_dir: Path):
    from hypernix import old_oven

    bundle_path_raw = cfg.get("bundle_path")
    bundle_path = (config_dir / bundle_path_raw).resolve() if bundle_path_raw else None

    # Fast path: a previously-baked bundle is right here — load it offline.
    if bundle_path and bundle_path.exists():
        print(f"[run_hypernix] loading bundle {bundle_path}", file=sys.stderr)
        return old_oven.load_pt(bundle_path, device=cfg.get("device"))

    # Slow path: download the HF snapshot + bake a bundle for next time.
    local_dir = cfg.get("local_dir")
    print(
        f"[run_hypernix] preheating from repo_id={cfg.get('repo_id')!r} "
        f"(local_dir={local_dir!r})",
        file=sys.stderr,
    )
    oven = old_oven.preheat(
        repo_id=cfg.get("repo_id", "ray0rf1re/hyper-nix.1"),
        revision=cfg.get("revision"),
        local_dir=local_dir,
        token=cfg.get("token"),
        device=cfg.get("device"),
        dtype=cfg.get("dtype", "float32"),
    )
    if bundle_path is not None:
        print(f"[run_hypernix] baking bundle -> {bundle_path}", file=sys.stderr)
        oven.save_pt(bundle_path)
    return oven


def _generate(oven, cfg: dict[str, Any]) -> str:
    mode = cfg.get("mode", "complete")
    common = {
        "max_new_tokens": int(cfg.get("max_new_tokens", 128)),
        "temperature": float(cfg.get("temperature", 0.2)),
        "top_k": int(cfg.get("top_k", 40)),
        "top_p": float(cfg.get("top_p", 0.95)),
        "seed": cfg.get("seed"),
    }
    if mode == "fill":
        prefix = cfg.get("fill_prefix")
        suffix = cfg.get("fill_suffix")
        if prefix is None or suffix is None:
            raise SystemExit("mode='fill' requires fill_prefix and fill_suffix in config")
        return oven.fill(prefix=prefix, suffix=suffix, **common)
    if mode == "complete":
        prompt = cfg.get("prompt", "")
        return oven.complete(prompt=prompt, **common)
    raise SystemExit(f"unknown mode: {mode!r} (use 'complete' or 'fill')")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--config", default=None,
        help="Path to hypernix_run.json. Default: next to this script.",
    )
    p.add_argument(
        "--bundle-only", action="store_true",
        help="Download + bake the bundle, then exit without running inference.",
    )
    p.add_argument(
        "--prompt", default=None,
        help="Override config['prompt'] (mode=complete) without editing the JSON.",
    )
    ns = p.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    config_path = Path(ns.config).resolve() if ns.config else script_dir / "hypernix_run.json"
    if not config_path.exists():
        raise SystemExit(f"config not found: {config_path}")

    cfg = _load_config(config_path)
    if ns.prompt is not None:
        cfg["prompt"] = ns.prompt
        cfg["mode"] = "complete"

    oven = _get_oven(cfg, config_path.parent)

    if ns.bundle_only:
        print("[run_hypernix] --bundle-only: skipping inference", file=sys.stderr)
        return 0

    text = _generate(oven, cfg)

    out_raw = cfg.get("output_path")
    if out_raw:
        out_path = (config_path.parent / out_raw).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        print(f"[run_hypernix] wrote {out_path}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
