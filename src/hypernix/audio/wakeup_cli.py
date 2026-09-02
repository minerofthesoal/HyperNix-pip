"""``hypernix wakeup`` — train a wake word, then listen for it.

    hypernix wakeup train "hey nix" --positives ./takes --negatives ./ambient
    hypernix wakeup train "hey nix" --tts --voices 3 --negatives ./ambient
    hypernix wakeup record "hey nix" -o ./takes -n 30
    hypernix wakeup listen --model hey-nix.pt
    hypernix wakeup check --model hey-nix.pt clip.wav
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

__all__ = ["main", "cli_main"]


def _train(ns: argparse.Namespace) -> int:
    from .wakeup import (
        WakeUpConfig,
        WakeUpError,
        build_dataset,
        examples_from_folder,
        save_wakeword,
        synthesize_examples,
        train_wakeword,
    )

    config = WakeUpConfig(
        wake_words=tuple(ns.wake_words),
        window_seconds=ns.window,
        threshold=ns.threshold,
    )

    positives = []
    negatives = []
    try:
        if ns.positives:
            positives += examples_from_folder(
                ns.positives, positive=True, fragments=ns.fragments
            )
        if ns.tts:
            positives += synthesize_examples(
                ns.wake_words,
                voices=tuple(f"voice{i + 1}" for i in range(ns.voices)),
                per_voice=ns.per_voice,
                progress=None if ns.quiet else _synth_progress,
            )
        if ns.negatives:
            negatives += examples_from_folder(ns.negatives, positive=False)
    except WakeUpError as exc:
        print(f"hypernix wakeup: {exc}", file=sys.stderr)
        return 1

    if not positives:
        print(
            "hypernix wakeup: no positive examples. Give --positives a folder, "
            "or --tts to generate them.",
            file=sys.stderr,
        )
        return 2

    dataset = build_dataset(
        positives, negatives, config=config, copies=ns.copies, seed=ns.seed
    )
    for note in dataset.warnings():
        print(f"  ! {note}", file=sys.stderr)

    def _epoch(event: dict) -> None:
        if ns.quiet or event.get("event") != "epoch":
            return
        print(
            f"  epoch {event['epoch']:>3}  loss {event['loss']:.4f}  "
            f"val {event['val_accuracy']:.3f}  "
            f"false-accepts {int(event['false_accepts'])}  "
            f"false-rejects {int(event['false_rejects'])}",
            file=sys.stderr,
        )

    try:
        result = train_wakeword(
            dataset, epochs=ns.epochs, seed=ns.seed,
            progress=_epoch, strict=ns.strict,
        )
    except WakeUpError as exc:
        print(f"hypernix wakeup: {exc}", file=sys.stderr)
        return 1

    output = Path(ns.output or f"{ns.wake_words[0].replace(' ', '-')}.pt")
    save_wakeword(result, output)

    summary = {
        "model": str(output),
        "wake_words": list(ns.wake_words),
        "examples": result["examples"],
        "negative_ratio": round(result["negative_ratio"], 2),
        "val_accuracy": round(result["val_accuracy"], 4),
        "precision": round(result["precision"], 4),
        "recall": round(result["recall"], 4),
        "sources": result["sources"],
        "warnings": result["warnings"],
    }
    print(json.dumps(summary, indent=2) if ns.as_json else _describe(summary))
    return 0


def _synth_progress(event: dict) -> None:
    if event.get("index", 0) % 10 == 0:
        print(
            f"  tts {event['voice']}: {event['index']}/{event['total']} "
            f"of {event['phrase']!r}",
            file=sys.stderr,
        )


def _describe(summary: dict) -> str:
    lines = [
        f"wrote {summary['model']}  ({', '.join(summary['wake_words'])})",
        f"  {summary['examples']} windows, {summary['negative_ratio']}x negatives",
        f"  accuracy {summary['val_accuracy']:.3f}  "
        f"precision {summary['precision']:.3f}  recall {summary['recall']:.3f}",
    ]
    for note in summary["warnings"]:
        lines.append(f"  ! {note}")
    return "\n".join(lines)


def _record(ns: argparse.Namespace) -> int:
    import struct
    import wave

    from .wakeup import TARGET_SAMPLE_RATE, WakeUpError, record_examples

    target = Path(ns.output)
    target.mkdir(parents=True, exist_ok=True)

    def prompt(index: int, total: int) -> None:
        print(f"  [{index}/{total}] say {ns.wake_words[0]!r} …", file=sys.stderr)

    try:
        examples = record_examples(ns.count, seconds=ns.seconds, prompt=prompt)
    except WakeUpError as exc:
        print(f"hypernix wakeup: {exc}", file=sys.stderr)
        return 1

    for index, example in enumerate(examples):
        path = target / f"take-{index:03d}.wav"
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(TARGET_SAMPLE_RATE)
            handle.writeframes(b"".join(
                struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32767))
                for v in example.samples
            ))
    print(f"wrote {len(examples)} takes to {target}")
    return 0


def _check(ns: argparse.Namespace) -> int:
    from .audiofile import AudioError, load_audio
    from .wakeup import WakeUpError, load_detector

    try:
        detector = load_detector(ns.model)
        audio = load_audio(ns.clip, sample_rate=detector.config.sample_rate)
    except (WakeUpError, AudioError) as exc:
        print(f"hypernix wakeup: {exc}", file=sys.stderr)
        return 1

    score = detector.score(audio.samples)
    fired = score >= detector.config.threshold
    if ns.as_json:
        print(json.dumps({
            "clip": str(ns.clip), "confidence": round(score, 4),
            "threshold": detector.config.threshold, "detected": fired,
        }, indent=2))
    else:
        print(f"{score:.4f}  {'DETECTED' if fired else 'no'}  "
              f"(threshold {detector.config.threshold})")
    return 0 if fired else 3


def _listen(ns: argparse.Namespace) -> int:
    from .wakeup import WakeUpError, load_detector

    try:
        detector = load_detector(ns.model)
    except WakeUpError as exc:
        print(f"hypernix wakeup: {exc}", file=sys.stderr)
        return 1

    try:
        import sounddevice  # type: ignore
    except ImportError:
        print(
            "hypernix wakeup: listening needs `pip install sounddevice`. "
            "Use `wakeup check` to score a file instead.",
            file=sys.stderr,
        )
        return 1

    rate = detector.config.sample_rate
    words = ", ".join(detector.config.wake_words) or "the wake word"
    print(f"listening for {words} — Ctrl-C to stop", file=sys.stderr)
    chunk = int(0.1 * rate)
    try:
        with sounddevice.InputStream(
            samplerate=rate, channels=1, dtype="float32", blocksize=chunk
        ) as stream:
            while True:
                data, _ = stream.read(chunk)
                hit = detector.push([float(frame[0]) for frame in data])
                if hit:
                    print(json.dumps(hit) if ns.as_json
                          else f"  wake  ({hit['confidence']:.3f})")
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hypernix wakeup",
        description="Train a wake word and listen for it.",
    )
    subparsers = parser.add_subparsers(dest="command")

    train = subparsers.add_parser("train", help="Train a wake-word model")
    train.add_argument("wake_words", nargs="+", help="The phrase(s) to detect")
    train.add_argument("--positives", help="Folder of recordings of the phrase")
    train.add_argument("--negatives", help="Folder of everything that is not it")
    train.add_argument("--fragments", action="store_true",
                       help="Treat --positives as one recording cut into pieces")
    train.add_argument("--tts", action="store_true",
                       help="Generate positives with TTS (the overnight path)")
    train.add_argument("--voices", type=int, default=1, choices=[1, 2, 3, 4])
    train.add_argument("--per-voice", type=int, default=40)
    train.add_argument("--copies", type=int, default=4,
                       help="Augmented copies per example")
    train.add_argument("--epochs", type=int, default=30)
    train.add_argument("--window", type=float, default=1.5, metavar="SECONDS")
    train.add_argument("--threshold", type=float, default=0.75)
    train.add_argument("--seed", type=int, default=0)
    train.add_argument("--strict", action="store_true",
                       help="Refuse to train on a dataset with warnings")
    train.add_argument("-o", "--output")
    train.add_argument("--json", dest="as_json", action="store_true")
    train.add_argument("-q", "--quiet", action="store_true")

    record = subparsers.add_parser("record", help="Capture takes from a microphone")
    record.add_argument("wake_words", nargs="+")
    record.add_argument("-o", "--output", required=True)
    record.add_argument("-n", "--count", type=int, default=25)
    record.add_argument("--seconds", type=float, default=2.0)

    check = subparsers.add_parser("check", help="Score one clip")
    check.add_argument("clip")
    check.add_argument("--model", required=True)
    check.add_argument("--json", dest="as_json", action="store_true")

    listen = subparsers.add_parser("listen", help="Listen on the microphone")
    listen.add_argument("--model", required=True)
    listen.add_argument("--json", dest="as_json", action="store_true")

    ns = parser.parse_args(argv)
    if ns.command == "train":
        return _train(ns)
    if ns.command == "record":
        return _record(ns)
    if ns.command == "check":
        return _check(ns)
    if ns.command == "listen":
        return _listen(ns)
    parser.print_help()
    return 2


def cli_main() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    cli_main()
