"""hypernix.audio.features — log-mel frames, without a DSP dependency.

A wake-word model does not see audio. It sees a short stack of log-mel
frames — a few tens of milliseconds each — and decides whether the last
second of them contained the phrase. So this is the whole input surface
of :mod:`hypernix.audio.wakeup`, and it is small enough to own rather
than depend on.

Numpy is used when it is there, and the pure-Python path is not a
fallback nobody runs: it is what makes the feature extractor testable
without pulling the scientific stack into a unit test, and the two are
checked against each other.

The mel scale here is the standard HTK formula. Not a choice so much as
the thing every other implementation uses, which matters because a model
trained on one mel definition and served on another sees a systematically
shifted spectrum and quietly gets worse.
"""
from __future__ import annotations

import cmath
import math
from dataclasses import dataclass

__all__ = [
    "MelConfig",
    "hz_to_mel",
    "mel_to_hz",
    "mel_filterbank",
    "log_mel_frames",
    "frame_count",
]


@dataclass(frozen=True)
class MelConfig:
    """Framing and filterbank settings.

    Defaults are the usual small-model wake-word shape: 16 kHz in, 25 ms
    windows every 10 ms, 32 mel bands. 32 rather than 80 because a wake
    word is a handful of phonemes and the extra bands cost model size for
    detail the task does not use.
    """

    sample_rate: int = 16000
    frame_length: int = 400        # 25 ms
    hop_length: int = 160          # 10 ms
    n_fft: int = 512
    n_mels: int = 32
    f_min: float = 20.0
    f_max: float = 7600.0
    #: Floor before the log, so silence is a large negative number rather
    #: than -inf — which propagates as NaN through the first layer.
    epsilon: float = 1e-10


def hz_to_mel(hz: float) -> float:
    return 2595.0 * math.log10(1.0 + hz / 700.0)


def mel_to_hz(mel: float) -> float:
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def mel_filterbank(config: MelConfig) -> list[list[float]]:
    """Triangular filters, one row per mel band.

    Built once and reused: for a 10 ms hop this is called on every frame
    otherwise, and rebuilding a filterbank per frame is most of the cost
    of the whole extractor.
    """
    bins = config.n_fft // 2 + 1
    low = hz_to_mel(config.f_min)
    high = hz_to_mel(min(config.f_max, config.sample_rate / 2))
    points = [
        mel_to_hz(low + (high - low) * i / (config.n_mels + 1))
        for i in range(config.n_mels + 2)
    ]
    bin_for = [
        int(math.floor((config.n_fft + 1) * hz / config.sample_rate)) for hz in points
    ]

    filters: list[list[float]] = []
    for band in range(config.n_mels):
        left, centre, right = bin_for[band], bin_for[band + 1], bin_for[band + 2]
        row = [0.0] * bins
        # A band whose edges collapse onto one bin would be all zeros and
        # contribute nothing; widening it by a bin keeps every band alive
        # at low frequencies where the mel scale is densest.
        if centre == left:
            centre = min(left + 1, bins - 1)
        if right <= centre:
            right = min(centre + 1, bins - 1)
        for index in range(max(0, left), min(centre, bins - 1)):
            row[index] = (index - left) / max(1, centre - left)
        for index in range(max(0, centre), min(right, bins - 1)):
            row[index] = (right - index) / max(1, right - centre)
        filters.append(row)
    return filters


def frame_count(n_samples: int, config: MelConfig) -> int:
    """How many frames *n_samples* yields."""
    if n_samples < config.frame_length:
        return 0
    return 1 + (n_samples - config.frame_length) // config.hop_length


def _hann(length: int) -> list[float]:
    if length == 1:
        return [1.0]
    return [0.5 - 0.5 * math.cos(2.0 * math.pi * i / (length - 1)) for i in range(length)]


def _dft_power(window: list[float], n_fft: int) -> list[float]:
    """Power spectrum via a radix-2 FFT, padded to *n_fft*.

    Written out rather than imported so the pure-Python path is genuinely
    dependency-free. It is O(n log n), which for a 512-point frame is
    fast enough that the numpy path is a convenience rather than a
    necessity for short clips.
    """
    padded = list(window[:n_fft]) + [0.0] * max(0, n_fft - len(window))
    spectrum = _fft([complex(x, 0.0) for x in padded])
    return [abs(value) ** 2 for value in spectrum[: n_fft // 2 + 1]]


def _fft(values: list[complex]) -> list[complex]:
    length = len(values)
    if length <= 1:
        return values
    if length & (length - 1):
        raise ValueError("n_fft must be a power of two")
    even = _fft(values[0::2])
    odd = _fft(values[1::2])
    twiddles = [cmath.exp(-2j * math.pi * k / length) * odd[k] for k in range(length // 2)]
    return (
        [even[k] + twiddles[k] for k in range(length // 2)]
        + [even[k] - twiddles[k] for k in range(length // 2)]
    )


def log_mel_frames(
    samples: list[float],
    config: MelConfig | None = None,
    *,
    filters: list[list[float]] | None = None,
) -> list[list[float]]:
    """Log-mel frames for *samples*: a list of ``n_mels``-long rows."""
    config = config or MelConfig()
    total = frame_count(len(samples), config)
    if total <= 0:
        return []
    filters = filters if filters is not None else mel_filterbank(config)

    try:
        import numpy as np
    except ImportError:
        np = None

    if np is not None:
        data = np.asarray(samples, dtype=np.float64)
        indices = (
            np.arange(config.frame_length)[None, :]
            + config.hop_length * np.arange(total)[:, None]
        )
        windows = data[indices] * np.hanning(config.frame_length)
        spectrum = np.abs(np.fft.rfft(windows, n=config.n_fft)) ** 2
        banks = spectrum @ np.asarray(filters, dtype=np.float64).T
        return np.log(np.maximum(banks, config.epsilon)).tolist()

    hann = _hann(config.frame_length)
    out: list[list[float]] = []
    for index in range(total):
        start = index * config.hop_length
        window = [
            samples[start + i] * hann[i] for i in range(config.frame_length)
        ]
        power = _dft_power(window, config.n_fft)
        out.append([
            math.log(max(sum(p * f for p, f in zip(power, row, strict=True)), config.epsilon))
            for row in filters
        ])
    return out
