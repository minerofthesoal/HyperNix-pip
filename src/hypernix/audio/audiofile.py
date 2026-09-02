"""hypernix.audio.audiofile — read audio without a mandatory dependency.

The wake-word trainer takes a folder of whatever the operator has: WAV
from a recorder, MP3 from a phone, FLAC from an archive, and MP3
fragments from a stream that was cut into pieces. That is four decoders,
and requiring a specific one would mean the common case — a folder of
mixed formats — fails on the second file.

So: WAV is decoded here, in pure Python, because it is a format and not
a codec and shipping a dependency for it would be silly. Everything else
is handed to ffmpeg if it is installed, or to ``soundfile``/``librosa``
if they are, and if none of those exist the file is skipped with a
message naming what would let it be read — not an ImportError halfway
through a folder.

Fragmented MP3
--------------
A stream cut into pieces is a set of files that are individually
decodable but only meaningful in order. ``load_fragments`` sorts them
naturally (``part2`` before ``part10``) and concatenates the decoded
audio, so a folder of fragments trains as one recording rather than as N
recordings that each start mid-word.
"""
from __future__ import annotations

import array
import logging
import re
import shutil
import struct
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "AudioError",
    "Audio",
    "SUPPORTED_SUFFIXES",
    "decoders_available",
    "load_audio",
    "load_fragments",
    "iter_audio_files",
    "resample",
]

#: What the loader will attempt. Anything else is skipped by name.
SUPPORTED_SUFFIXES = (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".opus", ".aiff")

#: Everything downstream works at this rate; a wake word does not need
#: more, and mismatched rates are the most common silent bug in an audio
#: pipeline.
TARGET_SAMPLE_RATE = 16000


class AudioError(Exception):
    """A file could not be read, with a reason worth printing."""


@dataclass
class Audio:
    """Mono float samples in [-1, 1], and the rate they are at."""

    samples: list[float]
    sample_rate: int
    source: str = ""

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sample_rate if self.sample_rate else 0.0

    def to_rate(self, rate: int) -> Audio:
        if rate == self.sample_rate:
            return self
        return Audio(
            resample(self.samples, self.sample_rate, rate), rate, self.source
        )


def decoders_available() -> dict[str, bool]:
    """Which decoders this machine actually has."""
    have = {"wav": True, "ffmpeg": shutil.which("ffmpeg") is not None}
    for name in ("soundfile", "librosa"):
        try:
            __import__(name)
            have[name] = True
        except Exception:  # noqa: BLE001
            have[name] = False
    return have


def resample(samples: list[float], source_rate: int, target_rate: int) -> list[float]:
    """Linear resampling.

    Not the highest-quality method available, and deliberately so: a wake
    word is a 1-2 second clip of speech being fed to a mel filterbank
    that will throw away most of this detail anyway, and a dependency on
    a resampling library would be a dependency on the whole scientific
    stack for one function.
    """
    if source_rate == target_rate or not samples:
        return list(samples)
    ratio = target_rate / source_rate
    out_length = max(1, int(len(samples) * ratio))
    out: list[float] = []
    for index in range(out_length):
        position = index / ratio
        left = int(position)
        right = min(left + 1, len(samples) - 1)
        fraction = position - left
        out.append(samples[left] * (1.0 - fraction) + samples[right] * fraction)
    return out


def _load_wav(path: Path) -> Audio:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())

    if width == 1:
        # 8-bit WAV is unsigned, centred on 128 — treating it as signed
        # gives audio that is inverted and offset, which sounds like
        # loud noise rather than like a bug.
        raw = [(byte - 128) / 128.0 for byte in frames]
    elif width == 2:
        values = array.array("h")
        values.frombytes(frames[: len(frames) // 2 * 2])
        raw = [v / 32768.0 for v in values]
    elif width == 4:
        values = array.array("i")
        values.frombytes(frames[: len(frames) // 4 * 4])
        raw = [v / 2147483648.0 for v in values]
    elif width == 3:
        raw = []
        for offset in range(0, len(frames) - 2, 3):
            chunk = frames[offset:offset + 3]
            value = struct.unpack("<i", chunk + (b"\xff" if chunk[2] & 0x80 else b"\x00"))[0]
            raw.append(value / 8388608.0)
    else:
        raise AudioError(f"{path}: {width * 8}-bit WAV is not supported.")

    if channels > 1:
        # Averaged, not left-channel-only: a wake word recorded on a
        # stereo mic can be quieter on one side, and taking one channel
        # would silently halve the signal for those recordings.
        raw = [
            sum(raw[i:i + channels]) / channels
            for i in range(0, len(raw) - channels + 1, channels)
        ]
    return Audio(raw, rate, str(path))


def _load_via_ffmpeg(path: Path, rate: int) -> Audio:
    """Decode anything ffmpeg can, straight to mono 16-bit at *rate*."""
    command = [
        "ffmpeg", "-v", "error", "-i", str(path),
        "-f", "s16le", "-acodec", "pcm_s16le",
        "-ac", "1", "-ar", str(rate), "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=300, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise AudioError(f"{path}: ffmpeg failed: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip().splitlines()
        raise AudioError(f"{path}: ffmpeg refused it: {detail[-1] if detail else 'no detail'}")
    values = array.array("h")
    values.frombytes(result.stdout[: len(result.stdout) // 2 * 2])
    return Audio([v / 32768.0 for v in values], rate, str(path))


def _load_via_soundfile(path: Path) -> Audio:
    import soundfile  # type: ignore

    data, rate = soundfile.read(str(path), dtype="float32", always_2d=True)
    mono = [float(sum(frame) / len(frame)) for frame in data]
    return Audio(mono, int(rate), str(path))


def load_audio(path: str | Path, *, sample_rate: int = TARGET_SAMPLE_RATE) -> Audio:
    """Load *path* as mono float samples at *sample_rate*.

    Raises :class:`AudioError` naming what would let the file be read,
    rather than an ImportError from whichever decoder was tried last.
    """
    path = Path(path)
    if not path.exists():
        raise AudioError(f"No such audio file: {path}")
    suffix = path.suffix.lower()

    if suffix in (".wav", ".wave"):
        try:
            return _load_wav(path).to_rate(sample_rate)
        except (wave.Error, EOFError) as exc:
            # A WAV that the stdlib refuses is often an mp3 named .wav,
            # or a WAV with a codec inside. ffmpeg can usually still read
            # it, so fall through rather than giving up on the file.
            logger.debug("audiofile: stdlib wave refused %s (%s); trying ffmpeg", path, exc)

    have = decoders_available()
    if have["ffmpeg"]:
        return _load_via_ffmpeg(path, sample_rate)
    if have["soundfile"]:
        return _load_via_soundfile(path).to_rate(sample_rate)

    raise AudioError(
        f"{path} needs a decoder for {suffix or 'this format'} and none is "
        "installed. Install ffmpeg (the usual answer, and it reads every "
        "format here) or `pip install soundfile`."
    )


def _natural_key(path: Path) -> list:
    """Sort key that puts ``part2`` before ``part10``.

    Plain lexicographic ordering puts part10 second, so a stream
    reassembled from fragments would have its middle in the wrong place —
    and the result is audio that sounds almost right, which is the worst
    kind of wrong for training data.
    """
    return [
        int(chunk) if chunk.isdigit() else chunk.lower()
        for chunk in re.split(r"(\d+)", path.name)
    ]


def load_fragments(
    paths: list[str | Path], *, sample_rate: int = TARGET_SAMPLE_RATE
) -> Audio:
    """Decode several fragments and join them into one recording."""
    ordered = sorted((Path(p) for p in paths), key=_natural_key)
    if not ordered:
        raise AudioError("No fragments given.")
    samples: list[float] = []
    for path in ordered:
        samples.extend(load_audio(path, sample_rate=sample_rate).samples)
    return Audio(samples, sample_rate, f"{len(ordered)} fragments from {ordered[0].parent}")


def iter_audio_files(directory: str | Path, *, recursive: bool = True):
    """Every readable-looking audio file under *directory*, sorted."""
    root = Path(directory)
    if not root.is_dir():
        raise AudioError(f"Not a directory: {root}")
    pattern = "**/*" if recursive else "*"
    found = [
        path for path in root.glob(pattern)
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    ]
    return sorted(found, key=_natural_key)
