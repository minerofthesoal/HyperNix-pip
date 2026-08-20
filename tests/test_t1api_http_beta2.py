"""Integration tests for Beta 2's HTTP layer: servers, modules, jobs,
events, billing, and the POST /models/route addition.

Same caveat as tests/test_t1api_http.py: requires
`pip install hypernix[t1api-test]` and was NOT executed in the sandbox
this was authored in (no network access there). The core logic each route
calls (t1api.servers/.modules/.jobs/.events/.billing/.routing) WAS
executed and is passing — see tests/test_t1api_servers.py,
test_t1api_modules.py, test_t1api_jobs.py, test_t1api_events.py,
test_t1api_billing.py, test_t1api_routing.py. Run this file first thing
after installing the extra and report back anything that doesn't match.
"""
from __future__ import annotations

import time

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from hypernix.gatekeeper import Gatekeeper  # noqa: E402
from hypernix.keymaster import KeyScope, KeyType, Keymaster  # noqa: E402
from hypernix.t1api.app import create_app  # noqa: E402
from hypernix.t1api.config import T1APIConfig  # noqa: E402
from hypernix.t1api.registry import ModelRegistry, ModelStatus  # noqa: E402
from hypernix.t1api.storage import UsageStore  # noqa: E402


_FREE_TIER_MODELS = [
    "nanonix-mini-plus", "nanonanonano-n3", "nanonix-mini-lite",
    "nanonix-mini", "nanonix-nano", "nanonanonanonano-n4",
]


@pytest.fixture
def km(tmp_path) -> Keymaster:
    return Keymaster(store_dir=tmp_path / "keymaster", auto_rotate=False)


@pytest.fixture
def gk(km, tmp_path) -> Gatekeeper:
    return Gatekeeper(keymaster=km, data_dir=tmp_path / "gatekeeper", log_to_file=False)


@pytest.fixture
def registry() -> ModelRegistry:
    reg = ModelRegistry.load(include_examples=True)
    for model_id in _FREE_TIER_MODELS:
        entry = reg.require(model_id)
        entry.status = ModelStatus.AVAILABLE
        entry.is_example_entry = False
        reg.register(entry)
    return reg


@pytest.fixture
def client(km, gk, registry, tmp_path) -> TestClient:
    cfg = T1APIConfig(token_secret="test-secret", db_path=str(tmp_path / "usage.sqlite3"))
    app = create_app(
        config=cfg,
        keymaster=km,
        gatekeeper=gk,
        registry=registry,
        usage_store=UsageStore(tmp_path / "usage.sqlite3"),
    )
    return TestClient(app)


@pytest.fixture
def user_key(km) -> str:
    return km.create(key_type=KeyType.USER, scopes={KeyScope.READ, KeyScope.WRITE}).key


@pytest.fixture
def admin_key(km) -> str:
    return km.create(key_type=KeyType.ADMIN, scopes={KeyScope.ADMIN, KeyScope.READ, KeyScope.WRITE}).key


def _auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


class TestModelRouting:
    def test_automatic_routing_returns_primary(self, client, user_key):
        resp = client.post(
            "/models/route", json={"plan": "free", "input_tokens": 100}, headers=_auth(user_key)
        )
        assert resp.status_code == 200
        assert resp.json()["model_id"] == "nanonix-mini-plus"

    def test_manual_routing_of_available_model_succeeds(self, client, user_key, registry):
        """There's no inference/chat endpoint in Beta 1/2 (the T1 API is a
        control plane, not an inference gateway), so there's no HTTP path
        that actually consumes token quota to drive a model into
        MODEL_QUOTA_EXHAUSTED through this router set. The exhaustion
        behavior itself is fully covered at the core level — see
        test_t1api_routing.py's TestManualSelection. This test only
        confirms manual selection of a non-exhausted model round-trips
        correctly over HTTP.
        """
        resp = client.post(
            "/models/route",
            json={"plan": "free", "model_id": "nanonix-nano"},
            headers=_auth(user_key),
        )
        assert resp.status_code == 200
        assert resp.json()["model_id"] == "nanonix-nano"

    def test_manual_routing_of_unregistered_model_returns_404(self, client, user_key):
        resp = client.post(
            "/models/route", json={"plan": "free", "model_id": "fake-model"}, headers=_auth(user_key)
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "MODEL_NOT_SUPPORTED"


class TestServers:
    def test_register_returns_untrusted_server(self, client, user_key):
        resp = client.post(
            "/servers/register",
            json={"name": "prod-1", "address": "https://prod1.example.com"},
            headers=_auth(user_key),
        )
        assert resp.status_code == 200
        body = resp.json()["server"]
        assert body["trust_level"] == "untrusted"

    def test_register_private_address_rejected_without_flag(self, client, user_key):
        resp = client.post(
            "/servers/register",
            json={"name": "local-1", "address": "http://192.168.1.5:9000"},
            headers=_auth(user_key),
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "SSRF_BLOCKED"

    def test_list_servers(self, client, user_key):
        client.post(
            "/servers/register",
            json={"name": "a", "address": "https://a.example.com"},
            headers=_auth(user_key),
        )
        resp = client.get("/servers", headers=_auth(user_key))
        assert resp.status_code == 200
        assert resp.json()["count"] >= 1

    def test_non_admin_cannot_patch_trust_level(self, client, user_key):
        reg_resp = client.post(
            "/servers/register",
            json={"name": "a", "address": "https://a.example.com"},
            headers=_auth(user_key),
        )
        server_id = reg_resp.json()["server"]["server_id"]
        resp = client.patch(
            f"/servers/{server_id}", json={"trust_level": "trusted"}, headers=_auth(user_key)
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "AUTH_ADMIN_REQUIRED"

    def test_admin_can_promote_trust_level(self, client, admin_key):
        reg_resp = client.post(
            "/servers/register",
            json={"name": "a", "address": "https://a.example.com"},
            headers=_auth(admin_key),
        )
        server_id = reg_resp.json()["server"]["server_id"]
        resp = client.patch(
            f"/servers/{server_id}", json={"trust_level": "trusted"}, headers=_auth(admin_key)
        )
        assert resp.status_code == 200
        assert resp.json()["server"]["trust_level"] == "trusted"

    def test_delete_requires_admin(self, client, user_key):
        reg_resp = client.post(
            "/servers/register",
            json={"name": "a", "address": "https://a.example.com"},
            headers=_auth(user_key),
        )
        server_id = reg_resp.json()["server"]["server_id"]
        resp = client.delete(f"/servers/{server_id}", headers=_auth(user_key))
        assert resp.status_code == 403


class TestModules:
    def test_create_module(self, client, user_key):
        resp = client.post(
            "/modules/create",
            json={"name": "my-mod", "version": "1.0.0"},
            headers=_auth(user_key),
        )
        assert resp.status_code == 200
        assert resp.json()["module"]["status"] == "draft"

    def test_upload_local_activates_module(self, client, user_key):
        create_resp = client.post(
            "/modules/create", json={"name": "my-mod", "version": "1.0.0"}, headers=_auth(user_key)
        )
        module_id = create_resp.json()["module"]["module_id"]
        upload_resp = client.post(
            f"/modules/upload/local?module_id={module_id}",
            files={"file": ("mod.bin", b"module content bytes")},
            headers=_auth(user_key),
        )
        assert upload_resp.status_code == 200
        body = upload_resp.json()["module"]
        assert body["status"] == "active"
        assert body["checksum"] is not None

    def test_upload_remote_marks_pending_fetch(self, client, user_key):
        create_resp = client.post(
            "/modules/create", json={"name": "my-mod", "version": "1.0.0"}, headers=_auth(user_key)
        )
        module_id = create_resp.json()["module"]["module_id"]
        resp = client.post(
            f"/modules/upload/remote?module_id={module_id}",
            json={"source_url": "https://example.com/mod.tar.gz"},
            headers=_auth(user_key),
        )
        assert resp.status_code == 200
        assert resp.json()["module"]["status"] == "pending_fetch"

    def test_upload_remote_ssrf_blocked(self, client, user_key):
        create_resp = client.post(
            "/modules/create", json={"name": "my-mod", "version": "1.0.0"}, headers=_auth(user_key)
        )
        module_id = create_resp.json()["module"]["module_id"]
        resp = client.post(
            f"/modules/upload/remote?module_id={module_id}",
            json={"source_url": "http://169.254.169.254/secret"},
            headers=_auth(user_key),
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "SSRF_BLOCKED"

    def test_other_users_module_not_editable(self, client, user_key, km):
        other_key = km.create(key_type=KeyType.USER, scopes={KeyScope.READ, KeyScope.WRITE}).key
        create_resp = client.post(
            "/modules/create", json={"name": "my-mod", "version": "1.0.0"}, headers=_auth(user_key)
        )
        module_id = create_resp.json()["module"]["module_id"]
        resp = client.patch(
            f"/modules/{module_id}", json={"metadata": {"x": 1}}, headers=_auth(other_key)
        )
        assert resp.status_code == 403

    def test_sync_to_untrusted_server_job_fails(self, client, user_key):
        create_resp = client.post(
            "/modules/create", json={"name": "my-mod", "version": "1.0.0"}, headers=_auth(user_key)
        )
        module_id = create_resp.json()["module"]["module_id"]
        server_resp = client.post(
            "/servers/register",
            json={"name": "s1", "address": "https://s1.example.com"},
            headers=_auth(user_key),
        )
        server_id = server_resp.json()["server"]["server_id"]
        sync_resp = client.post(
            f"/modules/{module_id}/sync", json={"server_id": server_id}, headers=_auth(user_key)
        )
        assert sync_resp.status_code == 200
        job_id = sync_resp.json()["job_id"]

        # job runs in a background thread pool by default -- poll briefly
        deadline = time.time() + 2.0
        while time.time() < deadline:
            job_resp = client.get(f"/jobs/{job_id}", headers=_auth(user_key))
            status = job_resp.json()["job"]["status"]
            if status in ("succeeded", "failed"):
                break
            time.sleep(0.05)
        assert job_resp.json()["job"]["status"] == "failed"
        assert "SERVER_UNTRUSTED" in job_resp.json()["job"]["error"]

    def test_sync_to_trusted_server_succeeds(self, client, admin_key):
        create_resp = client.post(
            "/modules/create", json={"name": "my-mod", "version": "1.0.0"}, headers=_auth(admin_key)
        )
        module_id = create_resp.json()["module"]["module_id"]
        server_resp = client.post(
            "/servers/register",
            json={"name": "s1", "address": "https://s1.example.com"},
            headers=_auth(admin_key),
        )
        server_id = server_resp.json()["server"]["server_id"]
        client.patch(f"/servers/{server_id}", json={"trust_level": "trusted"}, headers=_auth(admin_key))

        sync_resp = client.post(
            f"/modules/{module_id}/sync", json={"server_id": server_id}, headers=_auth(admin_key)
        )
        job_id = sync_resp.json()["job_id"]

        deadline = time.time() + 2.0
        job_resp = None
        while time.time() < deadline:
            job_resp = client.get(f"/jobs/{job_id}", headers=_auth(admin_key))
            if job_resp.json()["job"]["status"] in ("succeeded", "failed"):
                break
            time.sleep(0.05)
        assert job_resp.json()["job"]["status"] == "succeeded"
        assert job_resp.json()["job"]["result"]["deployed_servers"] == [server_id]


class TestJobs:
    def test_create_job_with_unregistered_kind_returns_501(self, client, user_key):
        resp = client.post(
            "/jobs", json={"kind": "not-a-real-kind", "payload": {}}, headers=_auth(user_key)
        )
        assert resp.status_code == 501
        assert resp.json()["error"]["code"] == "NOT_SUPPORTED"

    def test_get_unknown_job_returns_404(self, client, user_key):
        resp = client.get("/jobs/nope", headers=_auth(user_key))
        assert resp.status_code == 404

    def test_cancel_unknown_job_returns_404(self, client, user_key):
        resp = client.post("/jobs/nope/cancel", headers=_auth(user_key))
        assert resp.status_code == 404


class TestEvents:
    def test_list_events_after_server_register(self, client, user_key):
        client.post(
            "/servers/register",
            json={"name": "a", "address": "https://a.example.com"},
            headers=_auth(user_key),
        )
        resp = client.get("/events", headers=_auth(user_key))
        assert resp.status_code == 200
        types = [e["type"] for e in resp.json()["events"]]
        assert "server.registered" in types

    def test_events_filterable_by_type(self, client, user_key):
        client.post(
            "/servers/register",
            json={"name": "a", "address": "https://a.example.com"},
            headers=_auth(user_key),
        )
        resp = client.get("/events?type=server.registered", headers=_auth(user_key))
        events = resp.json()["events"]
        assert len(events) >= 1
        assert all(e["type"] == "server.registered" for e in events)


class TestBilling:
    def test_fresh_balance_is_zero(self, client, user_key):
        resp = client.get("/billing/balance", headers=_auth(user_key))
        assert resp.status_code == 200
        assert resp.json()["balance"] == 0.0

    def test_non_admin_cannot_mint_payment_token(self, client, user_key):
        resp = client.post(
            "/billing/payment-token", json={"amount": 50.0}, headers=_auth(user_key)
        )
        assert resp.status_code == 403

    def test_admin_mint_then_user_redeem(self, client, admin_key, user_key):
        mint_resp = client.post(
            "/billing/payment-token", json={"amount": 50.0}, headers=_auth(admin_key)
        )
        assert mint_resp.status_code == 200
        raw_token = mint_resp.json()["token"]

        redeem_resp = client.post(
            "/billing/redeem", json={"token": raw_token}, headers=_auth(user_key)
        )
        assert redeem_resp.status_code == 200
        assert redeem_resp.json()["balance"] == 50.0

    def test_double_redeem_rejected(self, client, admin_key, user_key):
        mint_resp = client.post(
            "/billing/payment-token", json={"amount": 50.0}, headers=_auth(admin_key)
        )
        raw_token = mint_resp.json()["token"]
        client.post("/billing/redeem", json={"token": raw_token}, headers=_auth(user_key))
        second = client.post("/billing/redeem", json={"token": raw_token}, headers=_auth(user_key))
        assert second.status_code == 409

    def test_non_admin_cannot_add_balance(self, client, user_key):
        resp = client.post(
            "/billing/add-balance",
            json={"account_type": "user", "account_id": "someone", "amount": 10},
            headers=_auth(user_key),
        )
        assert resp.status_code == 403

    def test_admin_add_balance(self, client, admin_key):
        resp = client.post(
            "/billing/add-balance",
            json={"account_type": "user", "account_id": "target-user", "amount": 25.0},
            headers=_auth(admin_key),
        )
        assert resp.status_code == 200
        assert resp.json()["balance"] == 25.0

    def test_transactions_reflect_redemption(self, client, admin_key, user_key):
        mint_resp = client.post(
            "/billing/payment-token", json={"amount": 15.0}, headers=_auth(admin_key)
        )
        raw_token = mint_resp.json()["token"]
        client.post("/billing/redeem", json={"token": raw_token}, headers=_auth(user_key))
        txns = client.get("/billing/transactions", headers=_auth(user_key))
        assert txns.status_code == 200
        assert any(t["kind"] == "redeem" for t in txns.json()["transactions"])
