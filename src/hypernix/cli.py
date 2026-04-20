"""Command-line interface for the hypernix package."""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterable
from pathlib import Path

from .convert import convert_to_gguf
from .download import download_model
from .quantize import quantize_gguf

# Preferred user-facing quant labels (one per file).
DEFAULT_QUANTS: list[str] = ["fp32", "fp16", "q8_0", "q6_k", "q4_k_m"]

# Normalize aliases -> canonical label used in output filenames.
_ALIAS = {
    "fp32": "fp32",
    "f32": "fp32",
    "fp16": "fp16",
    "f16": "fp16",
    "q8": "q8_0",
    "q8_0": "q8_0",
    "q6": "q6_k",
    "q6_k": "q6_k",
    "q4km": "q4_k_m",
    "q4_k_m": "q4_k_m",
    "q5km": "q5_k_m",
    "q5_k_m": "q5_k_m",
}


def _canonical(quant: str) -> str:
    key = quant.lower().replace("-", "_")
    if key not in _ALIAS:
        raise SystemExit(
            f"Unknown quant {quant!r}. Valid: {sorted(set(_ALIAS))}"
        )
    return _ALIAS[key]


def _plan(quants: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for q in quants:
        c = _canonical(q)
        if c not in seen:
            seen.append(c)
    return seen


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hypernix",
        description="Download and quantize the HyperNix PyTorch model to GGUF.",
    )
    p.add_argument(
        "--repo-id",
        default="ray0rf1re/hyper-nix.1",
        help="HuggingFace repo id (default: ray0rf1re/hyper-nix.1).",
    )
    p.add_argument("--revision", default=None)
    p.add_argument(
        "--model-dir",
        default=None,
        help="Use an existing local snapshot instead of downloading.",
    )
    p.add_argument(
        "--output-dir",
        default="./hypernix-gguf",
        help="Where to write the GGUF files.",
    )
    p.add_argument(
        "--name",
        default="HyperNix",
        help="Model display name written into the GGUF header.",
    )
    p.add_argument(
        "--arch",
        default="hypernix",
        help="GGUF architecture id (keep default unless you know what you're doing).",
    )
    p.add_argument(
        "--quants",
        nargs="*",
        default=DEFAULT_QUANTS,
        metavar="QUANT",
        help=(
            "Quantization formats to produce. "
            f"Valid: {sorted(set(_ALIAS))}. Default: {' '.join(DEFAULT_QUANTS)}"
        ),
    )
    p.add_argument(
        "--n-head",
        type=int,
        default=None,
        help="Override the attention-head count if it can't be inferred.",
    )
    p.add_argument(
        "--context-length",
        type=int,
        default=None,
        help="Override context length written into the GGUF header.",
    )
    p.add_argument(
        "--threads",
        type=int,
        default=max(1, (os.cpu_count() or 2) // 2),
        help="Threads for llama-quantize.",
    )
    p.add_argument(
        "--llama-quantize",
        default=None,
        help="Path to the llama-quantize binary (defaults to PATH / llama_cpp).",
    )
    p.add_argument(
        "--no-auto-fetch",
        dest="auto_fetch",
        action="store_false",
        default=True,
        help="Disable auto-download of a prebuilt llama-quantize from GitHub "
        "releases when none is found locally.",
    )
    p.add_argument(
        "--keep-intermediate",
        action="store_true",
        help="Keep the fp16 GGUF used as the source for k-quants.",
    )
    p.add_argument("--token", default=None, help="HuggingFace access token.")
    p.add_argument(
        "--upload-to",
        default=None,
        metavar="REPO_ID",
        help="After quantization, upload every produced GGUF to this HF repo "
        "(e.g. ray0rf1re/HyperNix.1-gguf). Requires --token or `huggingface-cli login`.",
    )
    p.add_argument(
        "--upload-private",
        action="store_true",
        help="Create the target upload repo as private if it doesn't exist.",
    )
    return p


def _pick_source_for(q: str, produced: dict[str, Path]) -> Path:
    """K-quants need an fp16/fp32 source. Prefer fp16, fall back to fp32."""
    if "fp16" in produced:
        return produced["fp16"]
    if "fp32" in produced:
        return produced["fp32"]
    raise RuntimeError(
        f"Cannot produce {q!r}: neither an fp16 nor fp32 GGUF has been built yet."
    )


def _run_fetch_llama_quantize(raw: list[str]) -> int:
    """`hypernix fetch-llama-quantize [--force]` subcommand handler."""
    from .fetcher import cache_dir, cached_binary, fetch_llama_quantize

    sub = argparse.ArgumentParser(
        prog="hypernix fetch-llama-quantize",
        description="Download a prebuilt CPU llama-quantize into the user cache.",
    )
    sub.add_argument(
        "--force",
        action="store_true",
        help="Ignore any cached binary and re-download.",
    )
    sub.add_argument("--quiet", action="store_true", help="Suppress progress output.")
    ns = sub.parse_args(raw)

    existing = cached_binary()
    if existing and not ns.force:
        print(f"[hypernix] already cached: {existing}", file=sys.stderr)
        return 0
    path = fetch_llama_quantize(force=ns.force, quiet=ns.quiet)
    print(f"[hypernix] {path}", file=sys.stderr)
    print(f"[hypernix] cache dir: {cache_dir()}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == "doctor":
        from .doctor import run

        return run()
    if raw and raw[0] == "fetch-llama-quantize":
        return _run_fetch_llama_quantize(raw[1:])
    args = _build_parser().parse_args(raw)
    plan = _plan(args.quants)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.model_dir:
        model_dir = Path(args.model_dir).resolve()
        if not model_dir.exists():
            print(f"--model-dir {model_dir} does not exist", file=sys.stderr)
            return 2
    else:
        print(f"[hypernix] downloading {args.repo_id} ...", file=sys.stderr)
        model_dir = download_model(repo_id=args.repo_id, revision=args.revision, token=args.token)
    print(f"[hypernix] model dir: {model_dir}", file=sys.stderr)

    base_name = args.repo_id.split("/")[-1].replace(".", "-")
    produced: dict[str, Path] = {}

    # Always emit fp32 or fp16 first (they are the source for k-quants).
    need_fp16 = any(q not in {"fp32", "fp16"} for q in plan) or "fp16" in plan
    need_fp32 = "fp32" in plan

    if need_fp32:
        out = output_dir / f"{base_name}-fp32.gguf"
        convert_to_gguf(
            model_dir,
            out,
            dtype="fp32",
            arch_name=args.arch,
            name=args.name,
            n_head_hint=args.n_head,
            context_length=args.context_length,
        )
        produced["fp32"] = out

    if need_fp16:
        out = output_dir / f"{base_name}-fp16.gguf"
        convert_to_gguf(
            model_dir,
            out,
            dtype="fp16",
            arch_name=args.arch,
            name=args.name,
            n_head_hint=args.n_head,
            context_length=args.context_length,
        )
        produced["fp16"] = out

    # k-quants
    for q in plan:
        if q in {"fp32", "fp16"}:
            continue
        src = _pick_source_for(q, produced)
        out = output_dir / f"{base_name}-{q}.gguf"
        quantize_gguf(
            source_gguf=src,
            output_gguf=out,
            quant_type=q,
            threads=args.threads,
            llama_quantize_bin=args.llama_quantize,
            auto_fetch=args.auto_fetch,
        )
        produced[q] = out

    # Cleanup: drop the intermediate fp16 unless asked to keep it or the user
    # explicitly requested it.
    if not args.keep_intermediate and "fp16" in produced and "fp16" not in plan:
        try:
            produced["fp16"].unlink()
            produced.pop("fp16")
        except OSError:
            pass

    print("[hypernix] done:", file=sys.stderr)
    for q, path in produced.items():
        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"  {q:<8} {size_mb:8.1f} MB  {path}", file=sys.stderr)

    if args.upload_to:
        from .upload import upload_gguf

        print(f"[hypernix] uploading {len(produced)} file(s) to {args.upload_to} ...", file=sys.stderr)
        url = upload_gguf(
            files=list(produced.values()),
            repo_id=args.upload_to,
            token=args.token,
            private=args.upload_private,
        )
        print(f"[hypernix] uploaded: {url}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
