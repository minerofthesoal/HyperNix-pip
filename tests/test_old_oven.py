"""Tests for hypernix.old_oven (code-generation wrapper around HyperNix)."""
from __future__ import annotations

from pathlib import Path

import pytest
import torch


@pytest.fixture
def tiny_snapshot_dir(tmp_path: Path) -> Path:
    from hypernix import HyperNixConfig, init_from_scratch

    # vocab_size=256 so the byte-tokenizer (which emits UTF-8 byte ids 0..255)
    # fits within the embedding table.
    cfg = HyperNixConfig(
        vocab_size=256, hidden_size=8, intermediate_size=16,
        num_hidden_layers=2, num_attention_heads=2, num_key_value_heads=1,
        max_position_embeddings=32,
    )
    init_from_scratch(str(tmp_path / "tiny"), cfg, tokenizer_source=None, seed=42)
    return tmp_path / "tiny"


def test_preheat_from_local_snapshot(tiny_snapshot_dir: Path) -> None:
    from hypernix import old_oven

    oven = old_oven.preheat(local_dir=tiny_snapshot_dir, device="cpu")
    assert oven.tokenizer_kind == "byte"  # no tokenizer.json => byte fallback
    assert oven.model_dir == tiny_snapshot_dir
    assert oven.device.type == "cpu"


def test_complete_is_deterministic_with_temperature_zero(tiny_snapshot_dir: Path) -> None:
    from hypernix import old_oven

    oven = old_oven.preheat(local_dir=tiny_snapshot_dir, device="cpu")
    out_a = oven.complete(
        "def add(a, b):", max_new_tokens=4, temperature=0.0, stop=(), seed=0,
    )
    out_b = oven.complete(
        "def add(a, b):", max_new_tokens=4, temperature=0.0, stop=(), seed=0,
    )
    assert isinstance(out_a, str)
    assert out_a == out_b


def test_fill_falls_back_without_fim_tokens(tiny_snapshot_dir: Path) -> None:
    """Byte tokenizer has no FIM tokens => .fill() continues the prefix."""
    from hypernix import old_oven

    oven = old_oven.preheat(local_dir=tiny_snapshot_dir, device="cpu")
    out = oven.fill(
        prefix="def add(a, b):\n    return ",
        suffix="\n\nresult = add(1, 2)",
        max_new_tokens=4, temperature=0.0,
    )
    assert isinstance(out, str)


def test_trim_at_stop_cuts_at_first_match() -> None:
    from hypernix.old_oven import _trim_at_stop

    text = "hello world\nclass Foo:\n    pass"
    assert _trim_at_stop(text, ("\nclass ",)) == "hello world"
    assert _trim_at_stop(text, ()) == text  # empty stops -> no trim


def test_save_pt_and_load_pt_roundtrip(tiny_snapshot_dir: Path, tmp_path: Path) -> None:
    from hypernix import old_oven

    oven = old_oven.preheat(local_dir=tiny_snapshot_dir, device="cpu")
    pt_path = tmp_path / "oven.pt"
    oven.save_pt(pt_path)
    assert pt_path.exists() and pt_path.stat().st_size > 0

    restored = old_oven.load_pt(pt_path, device="cpu")
    # Config survives the round trip.
    assert restored.model.config.vocab_size == oven.model.config.vocab_size
    assert restored.model.config.hidden_size == oven.model.config.hidden_size
    # Weights match (first parameter only, as a spot-check).
    orig_sd = oven.model.state_dict()
    new_sd = restored.model.state_dict()
    assert orig_sd.keys() == new_sd.keys()
    for k in orig_sd:
        if orig_sd[k].numel() == 0:
            continue
        assert torch.equal(orig_sd[k], new_sd[k]), f"weight mismatch on {k}"


def test_bake_code_accepts_snapshot_path(tiny_snapshot_dir: Path) -> None:
    """`bake_code` should accept a raw path and preheat internally."""
    from hypernix import old_oven

    out = old_oven.bake_code(
        tiny_snapshot_dir, "def fib(n):",
        max_new_tokens=2, temperature=0.0, stop=(),
    )
    assert isinstance(out, str)
