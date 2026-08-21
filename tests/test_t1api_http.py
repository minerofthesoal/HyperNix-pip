"""Integration tests for the T1 API's HTTP layer (hypernix.t1api.app).

Requires `pip install hypernix[t1api-test]` (fastapi, pydantic, uvicorn,
httpx). NOTE: these were written against FastAPI 0.115 / Pydantic v2
conventions but could not be executed in the sandbox this module was
authored in (no network access to install fastapi/pydantic/httpx there —
see tests/test_t1api_core.py and tests/test_t1api_auth.py, which exercise
the same enforcement logic through the dependency-free core and WERE
executed and passing). Run this file first thing after installing the
extra and report back anything that doesn't match — the core logic these
routes call has been verified; the FastAPI wiring itself has not.
"""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from hypernix.gatekeeper import Gatekeeper  # noqa: E402
from hypernix.keymaster import Keymaster, KeyScope, KeyType  # noqa: E402
from hypernix.t1api.app import create_app  # noqa: E402
from hypernix.t1api.config import T1APIConfig  # noqa: E402
from hypernix.t1api.registry import ModelRegistry  # noqa: E402
from hypernix.t1api.storage import UsageStore  # noqa: E402


@pytest.fixture
def km(tmp_path) -> Keymaster:
    return Keymaster(store_dir=tmp_path / "keymaster", auto_rotate=False)


@pytest.fixture
def gk(km, tmp_path) -> Gatekeeper:
    return Gatekeeper(keymaster=km, data_dir=tmp_path / "gatekeeper", log_to_file=False)


@pytest.fixture
def registry() -> ModelRegistry:
    return ModelRegistry.load(include_examples=True)


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


class TestHealthStatus:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert "request_id" in resp.json()

    def test_status(self, client, registry):
        resp = client.get("/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["model_count"] == len(registry)
        assert body["beta"] == "beta1"

    def test_request_id_header_present(self, client):
        resp = client.get("/health")
        assert "X-Request-ID" in resp.headers


class TestConfig:
    def test_config_never_leaks_token_secret(self, client):
        resp = client.get("/config")
        assert resp.status_code == 200
        body = resp.json()["config"]
        assert "token_secret" not in body
        assert "test-secret" not in resp.text


class TestModelsEndpoints:
    def test_list_models(self, client, registry):
        resp = client.get("/models")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == len(registry)

    def test_get_model(self, client):
        resp = client.get("/models/nanonix-nano")
        assert resp.status_code == 200
        assert resp.json()["model"]["model_id"] == "nanonix-nano"

    def test_unregistered_model_returns_model_not_supported(self, client):
        resp = client.get("/models/does-not-exist")
        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["code"] == "MODEL_NOT_SUPPORTED"
        assert "request_id" in body

    def test_availability(self, client):
        resp = client.get("/models/nanonix-nano/availability")
        assert resp.status_code == 200
        assert resp.json()["available"] is True

    def test_usage_requires_auth(self, client):
        resp = client.get("/models/nanonix-nano/usage")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "AUTH_MISSING_CREDENTIALS"

    def test_usage_with_auth(self, client, user_key):
        resp = client.get("/models/nanonix-nano/usage", headers=_auth(user_key))
        assert resp.status_code == 200
        body = resp.json()
        assert body["model_id"] == "nanonix-nano"
        assert body["is_exhausted"] is False


class TestAuthEndpoints:
    def test_validate_valid_key(self, client, user_key):
        resp = client.post("/auth/t1/validate", json={"key": user_key})
        assert resp.status_code == 200
        assert resp.json()["active"] is True

    def test_validate_invalid_key(self, client):
        resp = client.post("/auth/t1/validate", json={"key": "not-a-real-key"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "AUTH_INVALID_KEY"

    def test_issue_and_use_scoped_token(self, client, user_key):
        resp = client.post("/auth/token", json={"key": user_key, "scopes": ["read"]})
        assert resp.status_code == 200
        token = resp.json()["token"]
        # Use the scoped token against an authenticated endpoint.
        usage_resp = client.get("/models/nanonix-nano/usage", headers=_auth(token))
        assert usage_resp.status_code == 200

    def test_rotate_own_key(self, client, user_key):
        resp = client.post("/auth/t1/rotate", headers=_auth(user_key))
        assert resp.status_code == 200
        assert resp.json()["rotated_from"] is not None

    def test_admin_rotate_requires_admin(self, client, user_key):
        resp = client.post(
            "/auth/t1/admin/rotate",
            json={"target_key_id": "whatever", "promote_to_admin": False},
            headers=_auth(user_key),
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "AUTH_ADMIN_REQUIRED"

    def test_admin_can_promote(self, client, admin_key, gk, user_key):
        # Resolve key_id the same way T1AuthService does — via Gatekeeper.authenticate.
        target_id = gk.authenticate(user_key).key_id
        resp = client.post(
            "/auth/t1/admin/rotate",
            json={"target_key_id": target_id, "promote_to_admin": True},
            headers=_auth(admin_key),
        )
        assert resp.status_code == 200
        assert resp.json()["key_type"] == "admin"


class TestUsageEndpoints:
    def test_usage_current_requires_auth(self, client):
        resp = client.get("/usage/current")
        assert resp.status_code == 401

    def test_usage_current(self, client, user_key):
        resp = client.get("/usage/current", headers=_auth(user_key))
        assert resp.status_code == 200
        body = resp.json()
        assert "all_time" in body
        assert "by_model" in body

    def test_usage_remaining(self, client, user_key):
        resp = client.get("/usage/remaining", params={"model_id": "nanonix-nano"}, headers=_auth(user_key))
        assert resp.status_code == 200
        assert resp.json()["is_exhausted"] is False

    def test_usage_remaining_unregistered_model(self, client, user_key):
        resp = client.get("/usage/remaining", params={"model_id": "nope"}, headers=_auth(user_key))
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "MODEL_NOT_SUPPORTED"
