"""Unit tests for V0.71.2: hyped TUI Agent, SkillManager, ToolRegistry, multi-provider runners,
and Countertop T1 API key integration.
"""

import os
import tempfile
from pathlib import Path

from hypernix import __version__
from hypernix.countertop import countertop
from hypernix.gatekeeper import Gatekeeper
from hypernix.hyped import (
    CURATED_MODELS,
    HYPED_VERSION,
    SkillManager,
    ToolRegistry,
)
from hypernix.keymaster import Keymaster, KeyScope, KeyType


def test_version_v0712():
    assert __version__ == "0.71.2"
    assert HYPED_VERSION == "v0.71.3"


def test_countertop_t1_integration():
    km = Keymaster()
    meta = km.create(key_type=KeyType.USER, scopes={KeyScope.READ, KeyScope.WRITE})
    gk = Gatekeeper(keymaster=km)

    class MockOven:
        repo_id = "test-model-nix"
        def chat(self, messages, **kwargs):
            return "Mock reply from oven"

    ct = countertop(
        oven=MockOven(),
        t1_key=meta.key,
        keymaster=km,
        gatekeeper=gk,
    )

    assert ct.t1_meta is not None
    assert ct.t1_meta.key_id == meta.key_id

    reply = ct.say("Hello T1 test")
    assert reply == "Mock reply from oven"

    stats = ct.t1_stats()
    assert stats["total_requests"] == 1
    assert stats["lifetime_request_count"] == 1


def test_skill_manager():
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = SkillManager(storage_dir=Path(tmpdir))
        res = sm.create_skill(
            name="multiply_skill",
            description="Multiplies x and y",
            code="def execute(args):\n    return str(args.get('x', 0) * args.get('y', 0))",
        )
        assert "multiply_skill" in res

        skills = sm.list_skills()
        assert len(skills) == 1
        assert skills[0]["name"] == "multiply_skill"

        out = sm.run_skill("multiply_skill", {"x": 6, "y": 7})
        assert out == "42"

        del_res = sm.delete_skill("multiply_skill")
        assert "Deleted" in del_res
        assert len(sm.list_skills()) == 0


def test_tool_registry():
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = SkillManager(storage_dir=Path(tmpdir))
        tr = ToolRegistry(sm)
        assert len(tr.tools) >= 34

        # Test view_file & write_file
        file_path = os.path.join(tmpdir, "sample.txt")
        tr.execute_tool("write_file", {"path": file_path, "content": "Line 1\nLine 2\nLine 3"})
        view_out = tr.execute_tool("view_file", {"path": file_path, "start_line": 1, "end_line": 2})
        assert "Line 1" in view_out
        assert "Line 2" in view_out

        # Test replace_file_content
        tr.execute_tool("replace_file_content", {"path": file_path, "target": "Line 2", "replacement": "Line Two"})
        view_after = tr.execute_tool("view_file", {"path": file_path, "start_line": 1, "end_line": 3})
        assert "Line Two" in view_after

        # Test list_dir
        dir_out = tr.execute_tool("list_dir", {"path": tmpdir})
        assert "sample.txt" in dir_out

        # Test file_info
        info_out = tr.execute_tool("file_info", {"path": file_path})
        assert "Size:" in info_out

        # Test system_info
        sys_out = tr.execute_tool("system_info", {})
        assert "OS:" in sys_out


def test_curated_models_catalog():
    families = {m.family for m in CURATED_MODELS}
    assert len(families) >= 11
    assert "HyperNix" in families
    assert "Nix" in families
    assert "Qwen 3.5" in families
    assert "Nano" in families
    assert "LLaMA 3" in families
    assert "DeepSeek" in families
    assert "Mistral" in families
    assert "Gemma" in families
    assert "Phi" in families
    assert "OpenAI" in families
    assert "Anthropic" in families
