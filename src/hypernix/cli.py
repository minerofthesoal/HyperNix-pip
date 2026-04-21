"""Command-line interface for the hypernix package.

Usage:
    hypernix <subcommand> [options]

Subcommands are script-friendly: each one wraps a single public function
from the library and returns a non-zero exit code on failure.

    all                 (default) download -> convert -> [quantize]
    download            fetch a HuggingFace snapshot
    convert             produce fp32 / fp16 GGUF from a snapshot
    quantize            run llama-quantize on an fp16/fp32 GGUF
    verify              read-check a GGUF and print its headers
    info                show package + GGUF header info
    upload              push files to a HuggingFace repo
    doctor              environment diagnostic
    fetch-llama-quantize  pre-seed the llama-quantize cache
    train               training utilities (scratch / expand / loop)

Back-compat: invoking ``hypernix`` with flags and no subcommand runs
``hypernix all`` with those flags, so existing scripts keep working.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterable
from pathlib import Path

DEFAULT_QUANTS: list[str] = ["fp32", "fp16"]

_ALIAS: dict[str, str] = {
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

_SUBCOMMANDS = {
    "all",
    "download",
    "convert",
    "quantize",
    "verify",
    "info",
    "upload",
    "doctor",
    "fetch-llama-quantize",
    "train",
}


def _canonical(quant: str) -> str:
    key = quant.lower().replace("-", "_")
    if key not in _ALIAS:
        raise SystemExit(f"Unknown quant {quant!r}. Valid: {sorted(set(_ALIAS))}")
    return _ALIAS[key]


def _plan(quants: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for q in quants:
        c = _canonical(q)
        if c not in seen:
            seen.append(c)
    return seen


# ---------------------------------------------------------------------------
# `hypernix all` — the pipeline that used to be the only mode of operation.
# ---------------------------------------------------------------------------

def _build_all_parser(prog: str = "hypernix all") -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=prog,
        description="Download the HyperNix PyTorch model and emit GGUF files.",
    )
    p.add_argument("--repo-id", default="ray0rf1re/hyper-nix.1")
    p.add_argument("--revision", default=None)
    p.add_argument("--model-dir", default=None, help="Reuse an existing local snapshot.")
    p.add_argument("--output-dir", default="./hypernix-gguf")
    p.add_argument("--name", default="HyperNix")
    p.add_argument("--arch", default="hypernix")
    p.add_argument(
        "--quants", nargs="*", default=DEFAULT_QUANTS, metavar="QUANT",
        help=f"Valid: {sorted(set(_ALIAS))}. Default: {' '.join(DEFAULT_QUANTS)}",
    )
    p.add_argument("--n-head", type=int, default=None)
    p.add_argument("--context-length", type=int, default=None)
    p.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    p.add_argument("--llama-quantize", default=None)
    p.add_argument(
        "--no-auto-fetch", dest="auto_fetch", action="store_false", default=True,
        help="Disable auto-download of llama-quantize from GitHub releases.",
    )
    p.add_argument("--keep-intermediate", action="store_true")
    p.add_argument("--token", default=None)
    p.add_argument("--upload-to", default=None, metavar="REPO_ID")
    p.add_argument("--upload-private", action="store_true")
    return p


def _pick_source_for(q: str, produced: dict[str, Path]) -> Path:
    if "fp16" in produced:
        return produced["fp16"]
    if "fp32" in produced:
        return produced["fp32"]
    raise RuntimeError(f"Cannot produce {q!r}: need an fp16 or fp32 GGUF first.")


def _run_all(raw: list[str]) -> int:
    from .convert import convert_to_gguf
    from .download import download_model
    from .quantize import quantize_gguf

    args = _build_all_parser().parse_args(raw)
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
    need_fp16 = any(q not in {"fp32", "fp16"} for q in plan) or "fp16" in plan
    need_fp32 = "fp32" in plan

    if need_fp32:
        out = output_dir / f"{base_name}-fp32.gguf"
        convert_to_gguf(
            model_dir, out, dtype="fp32", arch_name=args.arch, name=args.name,
            n_head_hint=args.n_head, context_length=args.context_length,
        )
        produced["fp32"] = out
    if need_fp16:
        out = output_dir / f"{base_name}-fp16.gguf"
        convert_to_gguf(
            model_dir, out, dtype="fp16", arch_name=args.arch, name=args.name,
            n_head_hint=args.n_head, context_length=args.context_length,
        )
        produced["fp16"] = out

    for q in plan:
        if q in {"fp32", "fp16"}:
            continue
        out = output_dir / f"{base_name}-{q}.gguf"
        quantize_gguf(
            source_gguf=_pick_source_for(q, produced), output_gguf=out,
            quant_type=q, threads=args.threads,
            llama_quantize_bin=args.llama_quantize, auto_fetch=args.auto_fetch,
        )
        produced[q] = out

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
        url = upload_gguf(
            files=list(produced.values()), repo_id=args.upload_to,
            token=args.token, private=args.upload_private,
        )
        print(f"[hypernix] uploaded: {url}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# Individual subcommands (script-friendly)
# ---------------------------------------------------------------------------

def _run_download(raw: list[str]) -> int:
    from .download import download_model

    p = argparse.ArgumentParser(prog="hypernix download")
    p.add_argument("--repo-id", default="ray0rf1re/hyper-nix.1")
    p.add_argument("--revision", default=None)
    p.add_argument("--local-dir", default=None)
    p.add_argument("--cache-dir", default=None)
    p.add_argument("--token", default=None)
    ns = p.parse_args(raw)
    path = download_model(
        repo_id=ns.repo_id, revision=ns.revision,
        local_dir=ns.local_dir, cache_dir=ns.cache_dir, token=ns.token,
    )
    print(path)
    return 0


def _run_convert(raw: list[str]) -> int:
    from .convert import convert_to_gguf

    p = argparse.ArgumentParser(prog="hypernix convert")
    p.add_argument("--model-dir", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--dtype", default="fp16", choices=["fp32", "f32", "fp16", "f16"])
    p.add_argument("--arch", default="hypernix")
    p.add_argument("--name", default="HyperNix")
    p.add_argument("--n-head", type=int, default=None)
    p.add_argument("--context-length", type=int, default=None)
    ns = p.parse_args(raw)
    out = convert_to_gguf(
        model_dir=ns.model_dir, output=ns.output, dtype=ns.dtype,
        arch_name=ns.arch, name=ns.name,
        n_head_hint=ns.n_head, context_length=ns.context_length,
    )
    print(out)
    return 0


def _run_quantize(raw: list[str]) -> int:
    from .quantize import quantize_gguf

    p = argparse.ArgumentParser(prog="hypernix quantize")
    p.add_argument("--source", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--type", dest="qtype", required=True,
                   help=f"Quant type. Valid: {sorted(set(_ALIAS))}")
    p.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    p.add_argument("--llama-quantize", default=None)
    p.add_argument("--no-auto-fetch", dest="auto_fetch", action="store_false", default=True)
    ns = p.parse_args(raw)
    out = quantize_gguf(
        source_gguf=ns.source, output_gguf=ns.output, quant_type=ns.qtype,
        threads=ns.threads, llama_quantize_bin=ns.llama_quantize,
        auto_fetch=ns.auto_fetch,
    )
    print(out)
    return 0


def _run_verify(raw: list[str]) -> int:
    """Read-validate a GGUF file by parsing its header with the `gguf` library."""
    p = argparse.ArgumentParser(prog="hypernix verify")
    p.add_argument("gguf", help="Path to a .gguf file")
    p.add_argument("--tensors", action="store_true", help="Also list tensors.")
    ns = p.parse_args(raw)

    from gguf import GGUFReader  # type: ignore

    path = Path(ns.gguf)
    if not path.exists():
        print(f"not found: {path}", file=sys.stderr)
        return 2
    try:
        reader = GGUFReader(str(path), "r")
    except Exception as exc:  # noqa: BLE001
        print(f"[hypernix verify] FAILED to parse {path}: {exc}", file=sys.stderr)
        return 1

    print(f"[hypernix verify] {path}")
    print(f"  version: {reader.version}")
    print(f"  tensors: {len(reader.tensors)}   fields: {len(reader.fields)}")
    for name in sorted(reader.fields):
        f = reader.fields[name]
        try:
            value = f.parts[-1]
            summary = repr(value)[:80]
        except Exception:  # noqa: BLE001
            summary = "<binary>"
        print(f"    {name:<40} {summary}")
    if ns.tensors:
        for t in reader.tensors:
            print(f"    tensor {t.name}  shape={tuple(t.shape)}  type={t.tensor_type.name}")
    return 0


def _run_info(raw: list[str]) -> int:
    p = argparse.ArgumentParser(prog="hypernix info")
    p.add_argument("--gguf", default=None, help="Optional .gguf path to summarize.")
    ns = p.parse_args(raw)
    from . import __version__

    print(f"hypernix {__version__}")
    print(f"python   {sys.version.split()[0]}")
    try:
        import torch
        print(f"torch    {torch.__version__}")
    except Exception:
        pass
    if ns.gguf:
        return _run_verify([ns.gguf])
    return 0


def _run_upload(raw: list[str]) -> int:
    from .upload import upload_gguf

    p = argparse.ArgumentParser(prog="hypernix upload")
    p.add_argument("--repo-id", default="ray0rf1re/HyperNix.1-gguf")
    p.add_argument("--token", default=None)
    p.add_argument("--private", action="store_true")
    p.add_argument("--commit-message", default="Add HyperNix GGUF quantizations")
    p.add_argument("files", nargs="+")
    ns = p.parse_args(raw)
    url = upload_gguf(
        files=ns.files, repo_id=ns.repo_id, token=ns.token,
        private=ns.private, commit_message=ns.commit_message,
    )
    print(url)
    return 0


def _run_fetch_llama_quantize(raw: list[str]) -> int:
    from .fetcher import cache_dir, cached_binary, fetch_llama_quantize

    p = argparse.ArgumentParser(prog="hypernix fetch-llama-quantize")
    p.add_argument("--force", action="store_true")
    p.add_argument("--quiet", action="store_true")
    ns = p.parse_args(raw)
    existing = cached_binary()
    if existing and not ns.force:
        print(f"[hypernix] already cached: {existing}", file=sys.stderr)
        return 0
    path = fetch_llama_quantize(force=ns.force, quiet=ns.quiet)
    print(f"[hypernix] {path}", file=sys.stderr)
    print(f"[hypernix] cache dir: {cache_dir()}", file=sys.stderr)
    return 0


def _run_train(raw: list[str]) -> int:
    """`hypernix train {init,expand,run}` training utilities."""
    from .train import HyperNixConfig, expand_checkpoint, init_from_scratch, train

    p = argparse.ArgumentParser(prog="hypernix train")
    sub = p.add_subparsers(dest="action", required=True)

    p_init = sub.add_parser("init", help="Initialize a fresh HyperNix snapshot.")
    p_init.add_argument("--out-dir", required=True)
    p_init.add_argument("--tokenizer-source", default=None,
                        help="Existing snapshot to copy tokenizer files from.")
    p_init.add_argument("--vocab-size", type=int, default=32000)
    p_init.add_argument("--hidden-size", type=int, default=1024)
    p_init.add_argument("--intermediate-size", type=int, default=4096)
    p_init.add_argument("--num-hidden-layers", type=int, default=16)
    p_init.add_argument("--num-attention-heads", type=int, default=16)
    p_init.add_argument("--num-key-value-heads", type=int, default=None)
    p_init.add_argument("--max-position-embeddings", type=int, default=2048)
    p_init.add_argument("--rope-theta", type=float, default=10000.0)
    p_init.add_argument("--tie-word-embeddings", action="store_true")

    p_exp = sub.add_parser("expand", help="Warm-start a bigger model from a smaller one.")
    p_exp.add_argument("--src-dir", required=True)
    p_exp.add_argument("--dst-dir", required=True)
    p_exp.add_argument("--hidden-size", type=int, default=None)
    p_exp.add_argument("--intermediate-size", type=int, default=None)
    p_exp.add_argument("--num-hidden-layers", type=int, default=None)
    p_exp.add_argument("--num-attention-heads", type=int, default=None)
    p_exp.add_argument("--vocab-size", type=int, default=None)
    p_exp.add_argument("--init-std", type=float, default=0.02)

    p_run = sub.add_parser("run", help="Run a minimal causal-LM training loop.")
    p_run.add_argument("--model-dir", required=True)
    p_run.add_argument("--dataset", required=True, help="Path to a raw-text file.")
    p_run.add_argument("--out-dir", required=True)
    p_run.add_argument("--steps", type=int, default=1000)
    p_run.add_argument("--batch-size", type=int, default=2)
    p_run.add_argument("--context-length", type=int, default=512)
    p_run.add_argument("--lr", type=float, default=3e-4)
    p_run.add_argument("--weight-decay", type=float, default=0.1)
    p_run.add_argument("--grad-clip", type=float, default=1.0)
    p_run.add_argument("--device", default=None)
    p_run.add_argument("--dtype", default="float32", choices=["float32", "float16", "bfloat16"])
    p_run.add_argument("--log-every", type=int, default=10)
    p_run.add_argument("--save-every", type=int, default=500)

    ns = p.parse_args(raw)
    if ns.action == "init":
        cfg = HyperNixConfig(
            vocab_size=ns.vocab_size, hidden_size=ns.hidden_size,
            intermediate_size=ns.intermediate_size,
            num_hidden_layers=ns.num_hidden_layers,
            num_attention_heads=ns.num_attention_heads,
            num_key_value_heads=ns.num_key_value_heads,
            max_position_embeddings=ns.max_position_embeddings,
            rope_theta=ns.rope_theta,
            tie_word_embeddings=ns.tie_word_embeddings,
        )
        out = init_from_scratch(ns.out_dir, cfg, tokenizer_source=ns.tokenizer_source)
    elif ns.action == "expand":
        out = expand_checkpoint(
            ns.src_dir, ns.dst_dir,
            hidden_size=ns.hidden_size, intermediate_size=ns.intermediate_size,
            num_hidden_layers=ns.num_hidden_layers,
            num_attention_heads=ns.num_attention_heads,
            vocab_size=ns.vocab_size, init_std=ns.init_std,
        )
    else:  # run
        out = train(
            ns.model_dir, ns.dataset, ns.out_dir,
            steps=ns.steps, batch_size=ns.batch_size,
            context_length=ns.context_length, lr=ns.lr,
            weight_decay=ns.weight_decay, grad_clip=ns.grad_clip,
            device=ns.device, dtype=ns.dtype,
            log_every=ns.log_every, save_every=ns.save_every,
        )
    print(out)
    return 0


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)

    # No args or first arg isn't a subcommand -> run `all` with the given flags
    # so existing scripts don't break.
    if not raw or raw[0] not in _SUBCOMMANDS:
        return _run_all(raw)

    cmd, rest = raw[0], raw[1:]
    if cmd == "all":
        return _run_all(rest)
    if cmd == "download":
        return _run_download(rest)
    if cmd == "convert":
        return _run_convert(rest)
    if cmd == "quantize":
        return _run_quantize(rest)
    if cmd == "verify":
        return _run_verify(rest)
    if cmd == "info":
        return _run_info(rest)
    if cmd == "upload":
        return _run_upload(rest)
    if cmd == "doctor":
        from .doctor import run
        return run()
    if cmd == "fetch-llama-quantize":
        return _run_fetch_llama_quantize(rest)
    if cmd == "train":
        return _run_train(rest)
    raise SystemExit(f"unknown subcommand: {cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
