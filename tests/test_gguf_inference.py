"""`generate` and `chat` reading a GGUF.

Both commands took a snapshot directory — config.json plus safetensors,
loaded through torch — so the one format this package spends most of its
time *producing* was the one format its own inference commands could not
read.

The interesting case is the routing. The sub-bit tiers hyprslug writes
use GGML type ids at 200 and above, which no llama.cpp knows; handing one
to a runtime that does not know them gets either a refusal in someone
else's words or, worse, tensors read as the wrong type. So they go to
HyperNix's own runtime instead, and the upstream types still go to
llama.cpp, which is better at them than anything here will be.
"""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from hypernix.models.ggufrun import (
    GGUFRunError,
    describe_gguf,
    is_gguf,
    load_gguf,
)
from hypernix.quant.gguf import GGMLType, GGUFWriter
from hypernix.quant.hyprslug import quantize_gguf


def _plain_gguf(path: Path, *, name: str = "tiny") -> Path:
    writer = GGUFWriter(path)
    writer.set_metadata("general.architecture", "llama")
    writer.set_metadata("general.name", name)
    writer.add_tensor("blk.0.attn_q.weight", (512, 4), int(GGMLType.F32))
    values = [0.01] * (512 * 4)
    writer.write(lambda t: struct.pack(f"<{len(values)}f", *values))
    return path


class TestDetection:
    def test_a_gguf_is_recognised(self, tmp_path):
        assert is_gguf(_plain_gguf(tmp_path / "m.gguf"))

    def test_it_reads_the_magic_not_the_extension(self, tmp_path):
        """A file named .gguf that is not one should fail as 'not a GGUF',
        not somewhere deep inside a loader."""
        impostor = tmp_path / "lies.gguf"
        impostor.write_bytes(b"I am a text file")
        assert not is_gguf(impostor)

        real = _plain_gguf(tmp_path / "no-extension")
        assert is_gguf(real)

    def test_a_directory_is_not_a_gguf(self, tmp_path):
        assert not is_gguf(tmp_path)

    def test_a_missing_path_is_not_a_gguf(self, tmp_path):
        assert not is_gguf(tmp_path / "absent.gguf")


class TestDescribing:
    def test_it_reports_the_architecture_and_name(self, tmp_path):
        info = describe_gguf(_plain_gguf(tmp_path / "m.gguf", name="tiny-test"))
        assert info["architecture"] == "llama"
        assert info["name"] == "tiny-test"
        assert info["sub_bit"] is False

    def test_it_reports_a_sub_bit_tier(self, tmp_path):
        source = _plain_gguf(tmp_path / "src.gguf")
        out = tmp_path / "sub.gguf"
        quantize_gguf(source, out, "IQ0.5_XXXL")

        info = describe_gguf(out)
        assert info["sub_bit"] is True
        assert info["tier"] == "IQ0.5_XXXL"
        assert info["quantiser"] == "hyprslug"

    def test_a_non_gguf_is_refused_by_name(self, tmp_path):
        bad = tmp_path / "bad.gguf"
        bad.write_bytes(b"nope")
        with pytest.raises(GGUFRunError, match="GGUF magic"):
            describe_gguf(bad)


class TestTheSubBitRouting:
    """Type 200+ has nowhere to go in llama.cpp, and somewhere here."""

    @pytest.mark.parametrize("tier", ["IQ0.9_L", "IQ0.75_M", "IQ0.5_XXXL"])
    def test_a_sub_bit_model_is_not_sent_to_llama_cpp(self, tmp_path, tier, monkeypatch):
        """The routing decision, checked without needing a whole model.

        multilama would either refuse in someone else's words or read a
        0.5-bit tensor as Q4_K and return noise, so it must not be
        reached at all.
        """
        from hypernix.models import multilama

        def _never(*_args, **_kwargs):
            raise AssertionError("a sub-bit GGUF was handed to llama.cpp")

        monkeypatch.setattr(multilama, "load", _never)

        source = _plain_gguf(tmp_path / "src.gguf")
        out = tmp_path / f"{tier}.gguf"
        quantize_gguf(source, out, tier)

        # This fragment is not a runnable model -- it has one tensor --
        # so loading fails, but on the *model's* terms rather than on
        # "no llama.cpp can read this".
        with pytest.raises(GGUFRunError) as caught:
            load_gguf(out)
        assert "token_embd" in str(caught.value)

    def test_an_upstream_quant_still_goes_to_llama_cpp(self, tmp_path, monkeypatch):
        """The other half of the routing. llama.cpp is better at Q4_K_M
        than a reference implementation in torch will ever be."""
        from hypernix.models import multilama

        seen = {}

        def _record(*args, **kwargs):
            seen["called"] = True
            raise multilama.MultiLlamaError("ML-TEST", "stopped here on purpose")

        monkeypatch.setattr(multilama, "load", _record)

        source = _plain_gguf(tmp_path / "src.gguf")
        out = tmp_path / "q4.gguf"
        quantize_gguf(source, out, "Q4_0")

        with pytest.raises(GGUFRunError):
            load_gguf(out)
        assert seen.get("called"), "an upstream quant did not reach llama.cpp"

    def test_describe_still_names_the_tier(self, tmp_path):
        source = _plain_gguf(tmp_path / "src.gguf")
        out = tmp_path / "sub.gguf"
        quantize_gguf(source, out, "IQ0.5_XXXL")
        info = describe_gguf(out)
        assert info["sub_bit"] is True
        assert info["tier"] == "IQ0.5_XXXL"


class TestLoadingRefusals:
    def test_a_missing_model_says_so(self, tmp_path):
        with pytest.raises(GGUFRunError, match="No such model"):
            load_gguf(tmp_path / "absent.gguf")

    def test_a_non_gguf_says_so(self, tmp_path):
        bad = tmp_path / "bad.gguf"
        bad.write_bytes(b"not a model at all")
        with pytest.raises(GGUFRunError, match="not a GGUF"):
            load_gguf(bad)


class TestTheCLIRoutesToIt:
    def test_generate_checks_for_a_gguf(self):
        source = Path("src/hypernix/interfaces/cli.py").read_text()
        generate = source.split("def _run_generate(")[1].split("\ndef ")[0]
        assert "is_gguf" in generate
        assert "generate_with_gguf" in generate

    def test_chat_checks_for_a_gguf(self):
        source = Path("src/hypernix/interfaces/cli.py").read_text()
        chat = source.split("def _run_chat(")[1].split("\ndef ")[0]
        assert "is_gguf" in chat
        assert "load_gguf" in chat

    def test_chat_loads_the_model_once_not_per_turn(self):
        """A GGUF load is seconds to minutes; paying it per message would
        make the REPL unusable."""
        source = Path("src/hypernix/interfaces/cli.py").read_text()
        chat = source.split("def _run_chat(")[1].split("\ndef ")[0]
        turn = chat.split("def turn(")[1]
        assert "load_gguf" not in turn, "the model is reloaded on every turn"

    def test_both_help_texts_mention_gguf(self):
        source = Path("src/hypernix/interfaces/cli.py").read_text()
        for name in ("_run_generate", "_run_chat"):
            body = source.split(f"def {name}(")[1].split("\ndef ")[0]
            assert ".gguf" in body, name
