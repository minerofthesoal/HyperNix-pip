"""Tests for hypernix.waiter — the client, local config, and CLI dispatch.

Uses a real (stdlib ``http.server``) HTTP server rather than mocking
``urllib`` internals, so these tests exercise the actual request/response
path the ``waiter`` console script uses in production, just against a fake
backend instead of a live T1 API. See ``tests/test_t1api_*.py`` for the
server-side equivalents.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from hypernix.waiter.cli import main
from hypernix.waiter.client import T1Client, T1ClientError
from hypernix.waiter.local_config import WaiterConfigStore, WaiterLocalConfig


class _FakeT1Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D401 - silence default request logging
        pass

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - stdlib naming convention
        routes = {
            "/health": (200, {"status": "ok", "request_id": "r1"}),
            "/status": (
                200,
                {
                    "status": "ok",
                    "environment": "development",
                    "t1_api_version": "0.71.5b1",
                    "hypernix_version": "0.71.5b1",
                    "beta": "beta1",
                    "model_count": 1,
                    "storage_backend": "sqlite",
                    "request_id": "r2",
                },
            ),
            "/models": (
                200,
                {
                    "models": [
                        {
                            "model_id": "nanonix-nano",
                            "display_name": "nanoNix-nano",
                            "version": "1.0",
                            "architecture": "dense",
                            "status": "example",
                            "availability": "public",
                            "minimum_plan": "free",
                            "free_tier_available": True,
                            "routing_priority": 40,
                        }
                    ],
                    "count": 1,
                    "request_id": "r3",
                },
            ),
        }
        if self.path in routes:
            code, payload = routes[self.path]
            self._send(code, payload)
        else:
            self._send(404, {"error": {"code": "NOT_FOUND", "message": "no route"}, "request_id": "r4"})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        body = json.loads(raw or b"{}")
        if self.path == "/auth/t1/validate":
            key = body.get("key", "")
            if key == "T1_bad":
                self._send(
                    401,
                    {"error": {"code": "AUTH_INVALID_KEY", "message": "bad key"}, "request_id": "r5"},
                )
                return
            self._send(
                200,
                {
                    "key_id": "abc12345",
                    "key_type": "admin" if "admin" in key else "user",
                    "scopes": ["read", "write"] + (["admin"] if "admin" in key else []),
                    "active": True,
                    "is_admin": "admin" in key,
                    "expires_at": None,
                    "request_id": "r6",
                },
            )
        else:
            self._send(404, {"error": {"code": "NOT_FOUND", "message": "no route"}, "request_id": "r7"})


@pytest.fixture
def fake_server():
    srv = HTTPServer(("127.0.0.1", 0), _FakeT1Handler)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        srv.shutdown()


# ===========================================================================
# T1Client
# ===========================================================================


class TestT1Client:
    def test_health(self, fake_server):
        client = T1Client(base_url=fake_server)
        assert client.health()["status"] == "ok"

    def test_validate_success(self, fake_server):
        client = T1Client(base_url=fake_server)
        result = client.validate("T1_admin_key")
        assert result["key_id"] == "abc12345"
        assert result["is_admin"] is True

    def test_validate_failure_raises_with_code(self, fake_server):
        client = T1Client(base_url=fake_server)
        with pytest.raises(T1ClientError) as exc_info:
            client.validate("T1_bad")
        assert exc_info.value.code == "AUTH_INVALID_KEY"
        assert exc_info.value.status == 401

    def test_auth_required_call_without_credential_raises_locally(self, fake_server):
        client = T1Client(base_url=fake_server, credential=None)
        with pytest.raises(T1ClientError):
            client.usage_current()

    def test_unreachable_server_raises_clean_error(self):
        client = T1Client(base_url="http://127.0.0.1:1", timeout=1.0)
        with pytest.raises(T1ClientError):
            client.health()


# ===========================================================================
# WaiterLocalConfig / WaiterConfigStore
# ===========================================================================


class TestLocalConfig:
    def test_plain_roundtrip(self, tmp_path):
        store = WaiterConfigStore(tmp_path / "cfg.jsonl", encrypt=False)
        cfg = WaiterLocalConfig(server="s", key="k", port=1234)
        store.save(cfg)
        assert store.load() == cfg

    def test_encrypted_roundtrip(self, tmp_path):
        store = WaiterConfigStore(tmp_path / "cfg.jsonl", encrypt=True)
        cfg = WaiterLocalConfig(server="s", key="k")
        store.save(cfg)
        raw = (tmp_path / "cfg.jsonl").read_text()
        assert "server" not in raw  # not plaintext on disk
        assert store.load() == cfg

    def test_encrypted_file_readable_without_encrypt_flag_on_load(self, tmp_path):
        """The bug this test guards: reading back a file saved with -E
        must work even when the reader didn't pass encrypt=True, since
        real CLI usage often reads via a different subcommand than the
        one that wrote it (see hypernix.waiter.cli's _cmd_config)."""
        write_store = WaiterConfigStore(tmp_path / "cfg.jsonl", encrypt=True)
        cfg = WaiterLocalConfig(server="s", key="k")
        write_store.save(cfg)
        read_store = WaiterConfigStore(tmp_path / "cfg.jsonl", encrypt=False)
        assert read_store.load() == cfg

    def test_missing_file_returns_none(self, tmp_path):
        store = WaiterConfigStore(tmp_path / "nope.jsonl")
        assert store.load() is None


# ===========================================================================
# CLI dispatch (via main())
# ===========================================================================


class TestCliDispatch:
    def test_health_command(self, fake_server, capsys):
        rc = main(["health", "-I", fake_server])
        assert rc == 0

    def test_models_command(self, fake_server, capsys):
        rc = main(["models", "-I", fake_server, "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "nanonix-nano" in out

    def test_whoami_requires_key(self, fake_server):
        rc = main(["whoami", "-I", fake_server])
        assert rc == 1

    def test_whoami_with_key(self, fake_server):
        rc = main(["whoami", "-I", fake_server, "-K", "T1_user_key"])
        assert rc == 0

    def test_unknown_subcommand_returns_1(self):
        rc = main(["not-a-real-command"])
        assert rc == 1

    def test_serv_auto_end_to_end(self, fake_server, tmp_path):
        cfgfile = tmp_path / "cfg.jsonl"
        rc = main(["serv", "-A", "-I", fake_server, "-K", "T1_user_key", "-F", str(cfgfile)])
        assert rc == 0
        assert cfgfile.exists()
        store = WaiterConfigStore(cfgfile)
        saved = store.load()
        assert saved.server == fake_server
        assert saved.key == "T1_user_key"

    def test_serv_auto_encrypted_round_trips_through_config_command(self, fake_server, tmp_path, capsys):
        cfgfile = tmp_path / "cfg.jsonl"
        rc = main(["serv", "-A", "-I", fake_server, "-K", "T1_admin_key", "-E", "-F", str(cfgfile)])
        assert rc == 0
        capsys.readouterr()  # discard 'serv' output before capturing 'config' output below
        rc = main(["config", "-F", str(cfgfile), "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["server"] == fake_server
        assert payload["key"].endswith("…")  # masked, not the raw secret

    def test_serv_no_action_flags_is_an_error(self, fake_server, tmp_path):
        cfgfile = tmp_path / "cfg.jsonl"
        rc = main(["serv", "-I", fake_server, "-K", "T1_user_key", "-F", str(cfgfile)])
        assert rc == 1

    def test_serv_admin_surface_flags_dont_crash_and_dont_pretend_to_work(self, fake_server, tmp_path, capsys):
        """-B/-W/-r/-a have no server endpoint yet — they should be
        accepted, stored locally, and clearly flagged as not enforced,
        never silently dropped or falsely reported as applied."""
        cfgfile = tmp_path / "cfg.jsonl"
        rc = main(
            [
                "serv",
                "-A",
                "-I",
                fake_server,
                "-K",
                "T1_user_key",
                "-F",
                str(cfgfile),
                "-B",
                "1.2.3.4",
                "-W",
                "5.6.7.8",
            ]
        )
        assert rc == 0
        err = capsys.readouterr().err
        assert "Beta 2/3" in err or "not" in err.lower()
