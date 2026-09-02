"""Running a sub-bit GGUF, which is the half that was missing.

The IQ0.x tiers have been real quantisations since 0.72.3 pt 2 — the
tensors genuinely carry 0.56 bits per weight, the container is a
well-formed GGUF. What they were not was *runnable*. Type ids at 200 and
above are unknown to every llama.cpp, and the reference ``gguf`` Python
reader rejects them outright, so the file was correct, small, and had
nowhere to go. "It is a real quantisation" is not much comfort when
nothing will load it.

So the tests here build an actual llama-architecture model, quantise it
through the whole ladder, and *run* each result. Two things are being
separated deliberately:

* **Does the quantiser work?** Measured at the weights, where the answer
  is arithmetic: IQ0.5 stores 2 signs of every 4, so 75% of signs should
  survive, and if it is 50% the packing is broken.
* **Is the model any good?** Measured at the logits, where the answer at
  half a bit is "no" and is *supposed* to be. A test that demanded good
  output from a 0.5-bit model would be demanding the impossible, and the
  only way to pass it would be to stop quantising.

Confusing the two is how a quantiser ends up secretly not quantising.
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest
import torch

from hypernix.models import hnxrun
from hypernix.models.hnxtokenizer import tokenizer_from_metadata
from hypernix.quant.gguf import GGMLType, GGUFWriter
from hypernix.quant.hyprslug import quantize_gguf

N_LAYER, N_EMBD, N_HEAD, N_KV, N_FF, VOCAB = 2, 64, 4, 2, 128, 256
HEAD_DIM = N_EMBD // N_HEAD

SUB_BIT_TIERS = ["IQ0.9_L", "IQ0.75_M", "IQ0.5_XXXL"]

#: Fraction of signs each tier should preserve, from its own design: it
#: stores ``kept`` of every ``group`` and the rest are reconstructed by
#: repeating the last stored one, which is right half the time.
EXPECTED_SIGN_ACCURACY = {
    "IQ0.9_L": 0.9375,      # 7 of 8 stored, + half of the remaining 1/8
    "IQ0.75_M": 0.875,      # 3 of 4
    "IQ0.5_XXXL": 0.75,     # 2 of 4
}


def _write_model(path: Path, *, seed: int = 0, tokenizer: bool = False) -> Path:
    """A real llama-architecture GGUF: every tensor the graph needs.

    Small enough to run in a test and shaped like the thing it stands
    for -- grouped-query attention included, since a KV head count that
    differs from the query head count is where a forward pass that
    "works" on the easy case falls over.
    """
    rng = np.random.default_rng(seed)
    writer = GGUFWriter(path)
    writer.set_metadata("general.architecture", "llama")
    writer.set_metadata("general.name", "tiny")
    writer.set_metadata("llama.block_count", N_LAYER)
    writer.set_metadata("llama.embedding_length", N_EMBD)
    writer.set_metadata("llama.attention.head_count", N_HEAD)
    writer.set_metadata("llama.attention.head_count_kv", N_KV)
    writer.set_metadata("llama.feed_forward_length", N_FF)
    writer.set_metadata("llama.context_length", 256)
    writer.set_metadata("llama.attention.layer_norm_rms_epsilon", 1e-5)
    writer.set_metadata("llama.rope.freq_base", 10000.0)
    if tokenizer:
        # A byte-level vocabulary: enough to encode and decode real text
        # without shipping a merge table.
        writer.set_metadata("tokenizer.ggml.model", "gpt2")
        tokens = [chr(256 + i) for i in range(VOCAB)]
        for byte in range(256):
            tokens[byte] = _byte_char(byte)
        writer.set_metadata("tokenizer.ggml.tokens", tokens)
        writer.set_metadata("tokenizer.ggml.merges", [])
        writer.set_metadata("tokenizer.ggml.bos_token_id", 1)
        writer.set_metadata("tokenizer.ggml.eos_token_id", 2)

    # GGUF shape is (n_input, n_output) -- fastest dimension first.
    shapes: dict[str, tuple[int, ...]] = {
        "token_embd.weight": (N_EMBD, VOCAB),
        "output_norm.weight": (N_EMBD,),
        "output.weight": (N_EMBD, VOCAB),
    }
    for index in range(N_LAYER):
        shapes[f"blk.{index}.attn_norm.weight"] = (N_EMBD,)
        shapes[f"blk.{index}.attn_q.weight"] = (N_EMBD, N_HEAD * HEAD_DIM)
        shapes[f"blk.{index}.attn_k.weight"] = (N_EMBD, N_KV * HEAD_DIM)
        shapes[f"blk.{index}.attn_v.weight"] = (N_EMBD, N_KV * HEAD_DIM)
        shapes[f"blk.{index}.attn_output.weight"] = (N_HEAD * HEAD_DIM, N_EMBD)
        shapes[f"blk.{index}.ffn_norm.weight"] = (N_EMBD,)
        shapes[f"blk.{index}.ffn_gate.weight"] = (N_EMBD, N_FF)
        shapes[f"blk.{index}.ffn_up.weight"] = (N_EMBD, N_FF)
        shapes[f"blk.{index}.ffn_down.weight"] = (N_FF, N_EMBD)

    payload = {}
    for name, shape in shapes.items():
        count = int(np.prod(shape))
        values = (
            np.ones(count, np.float32)
            if name.endswith("norm.weight")
            else rng.normal(0.0, 0.08, count).astype(np.float32)
        )
        writer.add_tensor(name, shape, int(GGMLType.F32))
        payload[name] = struct.pack(f"<{count}f", *values.tolist())
    writer.write(lambda tensor: payload[tensor.name])
    return path


def _byte_char(byte: int) -> str:
    from hypernix.models.hnxtokenizer import _BYTE_ENCODER

    return _BYTE_ENCODER[byte]


@pytest.fixture(scope="module")
def base_model(tmp_path_factory):
    torch.set_num_threads(1)
    directory = tmp_path_factory.mktemp("hnxrun")
    return _write_model(directory / "tiny.f32.gguf")


@pytest.fixture(scope="module")
def quantised(tmp_path_factory, base_model):
    """Every sub-bit tier, plus an upstream one for comparison."""
    directory = tmp_path_factory.mktemp("hnxrun-quants")
    built = {}
    for tier in [*SUB_BIT_TIERS, "Q4_K_M", "Q8_0"]:
        out = directory / f"tiny.{tier}.gguf"
        quantize_gguf(
            base_model, out, tier, quantize_embeddings=True, quantize_output=True
        )
        built[tier] = out
    return built


class TestItLoadsWhatNothingElseCan:
    @pytest.mark.parametrize("tier", SUB_BIT_TIERS)
    def test_a_sub_bit_model_loads(self, quantised, tier):
        model = hnxrun.load_model(quantised[tier])
        assert model.sub_bit is True
        assert model.config.block_count == N_LAYER
        assert model.config.vocab_size == VOCAB

    @pytest.mark.parametrize("tier", SUB_BIT_TIERS)
    def test_every_tensor_came_back_finite(self, quantised, tier):
        """A dequantiser that divides by a zero scale produces NaN, and a
        model of NaN loads perfectly and generates nothing."""
        model = hnxrun.load_model(quantised[tier])
        for name, tensor in model.tensors.items():
            assert torch.isfinite(tensor).all(), name

    def test_the_reference_gguf_reader_cannot_open_these(self, quantised):
        """Not a defect -- the point. The type ids are deliberately
        outside upstream's range so a stock loader refuses the file by
        name instead of reading a 0.5-bit tensor as Q4_K. This pins that
        it is still true, because if upstream ever allocates 202 the
        collision would be silent and catastrophic.
        """
        gguf = pytest.importorskip("gguf")
        with pytest.raises(Exception):  # noqa: B017 - the library's own type varies
            gguf.GGUFReader(str(quantised["IQ0.5_XXXL"]))

    def test_the_reference_reader_opens_an_upstream_quant(self, quantised):
        """The control. If this also failed, the file would be malformed
        rather than merely carrying a type upstream does not know."""
        gguf = pytest.importorskip("gguf")
        reader = gguf.GGUFReader(str(quantised["Q8_0"]))
        assert len(reader.tensors) > 0

    def test_the_shape_is_read_the_right_way_round(self, base_model):
        """GGUF stores the fastest dimension first, so a weight is
        (n_input, n_output) on disk and (out, in) in a linear layer.
        Backwards, the model loads cleanly and multiplies the wrong way."""
        model = hnxrun.load_model(base_model)
        assert tuple(model.tensors["token_embd.weight"].shape) == (VOCAB, N_EMBD)
        assert tuple(model.tensors["blk.0.ffn_up.weight"].shape) == (N_FF, N_EMBD)
        assert tuple(model.tensors["blk.0.ffn_down.weight"].shape) == (N_EMBD, N_FF)


class TestTheQuantiserItself:
    """Measured at the weights, where the answer is arithmetic."""

    @pytest.mark.parametrize("tier", SUB_BIT_TIERS)
    def test_the_signs_survive_at_the_designed_rate(self, base_model, quantised, tier):
        """The number that says the packing is doing what it claims.

        IQ0.5 stores two signs of every four and reconstructs the other
        two by repeating the last stored one -- right half the time -- so
        75% of signs should come back. 50% would mean the stored signs
        are landing on the wrong weights, which is invisible in file size
        and fatal to the model.
        """
        original = hnxrun.load_model(base_model).tensors["blk.0.ffn_up.weight"]
        restored = hnxrun.load_model(quantised[tier]).tensors["blk.0.ffn_up.weight"]
        accuracy = float((torch.sign(original) == torch.sign(restored)).float().mean())
        expected = EXPECTED_SIGN_ACCURACY[tier]
        assert accuracy == pytest.approx(expected, abs=0.06), (
            f"{tier} kept {accuracy:.1%} of signs; its packing implies {expected:.1%}"
        )

    def test_a_wider_tier_keeps_more_signs(self, base_model, quantised):
        original = hnxrun.load_model(base_model).tensors["blk.0.ffn_up.weight"]

        def _accuracy(tier):
            restored = hnxrun.load_model(quantised[tier]).tensors["blk.0.ffn_up.weight"]
            return float((torch.sign(original) == torch.sign(restored)).float().mean())

        assert _accuracy("IQ0.9_L") > _accuracy("IQ0.75_M") > _accuracy("IQ0.5_XXXL")

    def test_the_file_really_is_smaller(self, base_model, quantised):
        sizes = {t: quantised[t].stat().st_size for t in SUB_BIT_TIERS}
        assert base_model.stat().st_size > sizes["IQ0.9_L"] * 10
        assert sizes["IQ0.9_L"] > sizes["IQ0.75_M"] > sizes["IQ0.5_XXXL"]


class TestItRuns:
    PROMPT = [1, 5, 9, 13, 21]

    @pytest.mark.parametrize("tier", SUB_BIT_TIERS)
    def test_the_forward_pass_produces_usable_logits(self, quantised, tier):
        model = hnxrun.load_model(quantised[tier])
        logits, _cache = hnxrun.forward(model, self.PROMPT)
        assert tuple(logits.shape) == (len(self.PROMPT), VOCAB)
        assert torch.isfinite(logits).all()

    @pytest.mark.parametrize("tier", SUB_BIT_TIERS)
    def test_it_generates_tokens(self, quantised, tier):
        """The whole claim, in one assertion: a 0.5-bit GGUF produces
        tokens."""
        model = hnxrun.load_model(quantised[tier])
        produced = hnxrun.generate_tokens(model, self.PROMPT, max_new_tokens=6)
        assert len(produced) == 6
        assert all(0 <= token < VOCAB for token in produced)

    def test_greedy_generation_is_deterministic(self, quantised):
        model = hnxrun.load_model(quantised["IQ0.5_XXXL"])
        first = hnxrun.generate_tokens(model, self.PROMPT, max_new_tokens=6)
        second = hnxrun.generate_tokens(model, self.PROMPT, max_new_tokens=6)
        assert first == second

    def test_sampling_with_a_seed_is_reproducible(self, quantised):
        model = hnxrun.load_model(quantised["IQ0.9_L"])
        kwargs = {"max_new_tokens": 6, "temperature": 0.8, "seed": 7}
        assert hnxrun.generate_tokens(
            model, self.PROMPT, **kwargs
        ) == hnxrun.generate_tokens(model, self.PROMPT, **kwargs)

    def test_the_kv_cache_agrees_with_a_full_recompute(self, quantised):
        """The classic way this goes quietly wrong: a cache that drifts
        from the uncached path gives output that is plausible and not
        what the model would have said."""
        model = hnxrun.load_model(quantised["IQ0.5_XXXL"])
        sequence = [1, 5, 9, 13, 21, 34]

        full, _ = hnxrun.forward(model, sequence)
        stepped, cache = hnxrun.forward(model, sequence[:3])
        for position, token in enumerate(sequence[3:], start=3):
            stepped, cache = hnxrun.forward(
                model, [token], cache=cache, start_position=position
            )
        assert torch.allclose(full[-1], stepped[-1], atol=1e-4)

    def test_grouped_query_attention_is_actually_grouped(self, base_model):
        model = hnxrun.load_model(base_model)
        assert model.config.head_count == N_HEAD
        assert model.config.head_count_kv == N_KV
        assert model.config.kv_groups == N_HEAD // N_KV

    def test_attention_is_causal(self, base_model):
        """Changing a later token must not move an earlier position's
        logits. A mask off by one is invisible in output that already
        looks like noise."""
        model = hnxrun.load_model(base_model)
        first, _ = hnxrun.forward(model, [1, 5, 9, 13])
        second, _ = hnxrun.forward(model, [1, 5, 9, 99])
        assert torch.allclose(first[:3], second[:3], atol=1e-5)
        assert not torch.allclose(first[3], second[3], atol=1e-3)


class TestFidelityDegradesAsItShould:
    """At the logits, where half a bit is supposed to be bad."""

    PROMPT = [1, 5, 9, 13, 21]

    def _agreement(self, reference, model) -> float:
        got, _ = hnxrun.forward(model, self.PROMPT)
        return float(
            np.corrcoef(reference[-1].numpy(), got[-1].detach().numpy())[0, 1]
        )

    def test_an_upstream_quant_tracks_the_original_closely(self, base_model, quantised):
        base = hnxrun.load_model(base_model)
        reference, _ = hnxrun.forward(base, self.PROMPT)
        agreement = self._agreement(reference, hnxrun.load_model(quantised["Q8_0"]))
        assert agreement > 0.95, (
            f"Q8_0 is meant to be near-lossless and agreed only {agreement:.2f}"
        )

    def test_the_sub_bit_tiers_are_ordered(self, base_model, quantised):
        """Not "good" -- ordered. More bits must not produce a worse
        model, and if they do the packing is wrong somewhere."""
        base = hnxrun.load_model(base_model)
        reference, _ = hnxrun.forward(base, self.PROMPT)
        wide = self._agreement(reference, hnxrun.load_model(quantised["Q4_K_M"]))
        narrow = self._agreement(reference, hnxrun.load_model(quantised["IQ0.5_XXXL"]))
        assert wide > narrow


class TestTheRefusals:
    def test_a_missing_model_says_so(self, tmp_path):
        with pytest.raises(hnxrun.HnxRunError, match="No such model"):
            hnxrun.load_model(tmp_path / "absent.gguf")

    def test_a_file_with_no_embedding_is_not_a_model(self, tmp_path):
        writer = GGUFWriter(tmp_path / "fragment.gguf")
        writer.set_metadata("general.architecture", "llama")
        writer.add_tensor("blk.0.attn_q.weight", (64, 4), int(GGMLType.F32))
        writer.write(lambda _t: struct.pack("<256f", *([0.0] * 256)))
        with pytest.raises(hnxrun.HnxRunError, match="token_embd"):
            hnxrun.load_model(tmp_path / "fragment.gguf")

    def test_an_architecture_it_does_not_implement_is_refused(self, tmp_path):
        """Running the llama graph over a model that is not one produces
        confident nonsense rather than an error, so the name is checked."""
        writer = GGUFWriter(tmp_path / "other.gguf")
        writer.set_metadata("general.architecture", "mamba")
        writer.add_tensor("token_embd.weight", (64, 8), int(GGMLType.F32))
        writer.write(lambda _t: struct.pack("<512f", *([0.01] * 512)))
        with pytest.raises(hnxrun.HnxRunError, match="llama-family"):
            hnxrun.load_model(tmp_path / "other.gguf")

    def test_an_out_of_range_token_is_refused(self, base_model):
        model = hnxrun.load_model(base_model)
        with pytest.raises(hnxrun.HnxRunError, match="out of range"):
            hnxrun.forward(model, [VOCAB + 5])

    def test_an_empty_prompt_is_refused(self, base_model):
        model = hnxrun.load_model(base_model)
        with pytest.raises(hnxrun.HnxRunError, match="no tokens"):
            hnxrun.generate_tokens(model, [])

    def test_text_generation_without_a_tokenizer_says_which_is_missing(self, base_model):
        """Guessing an encoding produces output that reads as a broken
        model rather than as a missing tokenizer."""
        with pytest.raises(hnxrun.HnxRunError, match="no tokenizer"):
            hnxrun.generate_text(base_model, "hello")


class TestTextInAndOut:
    def test_a_model_carrying_its_tokenizer_generates_text(self, tmp_path):
        """End to end from a string, which is what anyone actually
        wants: quantise to half a bit, then talk to it."""
        source = _write_model(tmp_path / "tok.f32.gguf", tokenizer=True)
        out = tmp_path / "tok.iq05.gguf"
        quantize_gguf(
            source, out, "IQ0.5_XXXL", quantize_embeddings=True, quantize_output=True
        )
        text = hnxrun.generate_text(out, "hello", max_new_tokens=4)
        assert isinstance(text, str)

    def test_the_tokenizer_round_trips_ascii(self, tmp_path):
        source = _write_model(tmp_path / "tok.gguf", tokenizer=True)
        model = hnxrun.load_model(source)
        assert model.tokenizer is not None
        ids = model.tokenizer.encode("hello world", add_bos=False)
        assert model.tokenizer.decode(ids) == "hello world"

    def test_a_file_without_tokenizer_metadata_reports_none(self, base_model):
        assert hnxrun.load_model(base_model).tokenizer is None

    def test_tokenizer_from_metadata_needs_tokens(self):
        assert tokenizer_from_metadata({}) is None
        assert tokenizer_from_metadata({"tokenizer.ggml.model": "gpt2"}) is None

    def test_a_sentencepiece_vocabulary_segments_by_score(self):
        """Viterbi over the scores, not longest-match-first: the greedy
        shortcut silently produces a different segmentation."""
        tokenizer = tokenizer_from_metadata({
            "tokenizer.ggml.model": "llama",
            "tokenizer.ggml.tokens": ["<unk>", "▁", "▁a", "b", "▁ab", "a"],
            "tokenizer.ggml.scores": [-100.0, -1.0, -3.0, -1.0, -1.5, -1.0],
        })
        assert tokenizer is not None and tokenizer.kind == "spm"
        # "▁ab" (-1.5) beats "▁a" + "b" (-3 + -1 = -4).
        assert tokenizer.encode("ab", add_bos=False) == [4]


class TestDescribe:
    def test_it_reports_the_architecture_and_the_packing(self, quantised):
        info = hnxrun.describe(quantised["IQ0.5_XXXL"])
        assert info["architecture"] == "llama"
        assert info["block_count"] == N_LAYER
        assert info["sub_bit"] is True
        assert "HNX_IQ0_5" in info["packed_as"]

    def test_an_upstream_quant_is_not_marked_sub_bit(self, quantised):
        info = hnxrun.describe(quantised["Q4_K_M"])
        assert info["sub_bit"] is False
