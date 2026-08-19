"""waiter.client — a stdlib-only HTTP client for the HyperNix T1 API.

Deliberately built on ``urllib.request`` rather than ``requests``/``httpx``
so the ``waiter`` console script has zero extra runtime dependencies beyond
what ``hypernix`` already installs — it's a thin client, not the API
server, and shouldn't need the ``hypernix[t1api]`` extra just to talk to
one over the network.

Every method returns the parsed JSON body on success and raises
:class:`T1ClientError` (carrying the server's stable error code when the
server sent one) on failure — the waiter CLI catches this one exception
type everywhere instead of a grab-bag of urllib/JSON errors.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class T1ClientError(Exception):
    """Raised for any failed T1 API call.

    Args:
        message: Human-readable summary.
        code: The server's stable error code (e.g. ``MODEL_NOT_SUPPORTED``)
            when the server returned one, else ``None`` (network error,
            non-JSON response, etc).
        status: HTTP status code, if a response was received at all.
        request_id: The server's request ID, if present.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status: int | None = None,
        request_id: str | None = None,
    ) -> None:
        self.code = code
        self.status = status
        self.request_id = request_id
        super().__init__(message)


@dataclass
class T1Client:
    """Talks to one T1 API server. ``base_url`` should NOT include a
    trailing slash (e.g. ``https://myserver.ts.net:8000``)."""

    base_url: str
    credential: str | None = None  # raw T1 key or scoped token; sent as Bearer
    timeout: float = 15.0

    # ------------------------------------------------------------------
    # Low-level request
    # ------------------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
        auth: bool = False,
    ) -> dict[str, Any]:
        url = self._url(path)
        if query:
            url += "?" + urllib.parse.urlencode(query)

        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if auth:
            if not self.credential:
                raise T1ClientError(
                    "This call requires a credential — pass -K/--key or run 'waiter serv -A' first."
                )
            headers["Authorization"] = f"Bearer {self.credential}"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {}
            err = payload.get("error", {})
            raise T1ClientError(
                err.get("message", f"HTTP {exc.code} calling {method} {path}"),
                code=err.get("code"),
                status=exc.code,
                request_id=payload.get("request_id"),
            ) from exc
        except urllib.error.URLError as exc:
            raise T1ClientError(f"Could not reach {url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise T1ClientError(f"Timed out calling {method} {path}") from exc
        except json.JSONDecodeError as exc:
            raise T1ClientError(f"Server returned non-JSON response for {method} {path}") from exc

    # ------------------------------------------------------------------
    # Health / status / config
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def status(self) -> dict[str, Any]:
        return self._request("GET", "/status")

    def config(self) -> dict[str, Any]:
        return self._request("GET", "/config")

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def validate(self, key: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/auth/t1/validate", body={"key": key or self.credential})

    def issue_token(
        self, key: str | None = None, *, ttl_seconds: int | None = None, scopes: list[str] | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"key": key or self.credential}
        if ttl_seconds is not None:
            body["ttl_seconds"] = ttl_seconds
        if scopes is not None:
            body["scopes"] = scopes
        return self._request("POST", "/auth/token", body=body)

    def rotate(self) -> dict[str, Any]:
        return self._request("POST", "/auth/t1/rotate", auth=True)

    def admin_rotate(self, target_key_id: str, *, promote_to_admin: bool = False) -> dict[str, Any]:
        return self._request(
            "POST",
            "/auth/t1/admin/rotate",
            body={"target_key_id": target_key_id, "promote_to_admin": promote_to_admin},
            auth=True,
        )

    # ------------------------------------------------------------------
    # Models
    # ------------------------------------------------------------------

    def list_models(self) -> dict[str, Any]:
        return self._request("GET", "/models")

    def get_model(self, model_id: str) -> dict[str, Any]:
        return self._request("GET", f"/models/{urllib.parse.quote(model_id, safe='')}")

    def model_availability(self, model_id: str) -> dict[str, Any]:
        return self._request("GET", f"/models/{urllib.parse.quote(model_id, safe='')}/availability")

    def model_usage(self, model_id: str) -> dict[str, Any]:
        return self._request(
            "GET", f"/models/{urllib.parse.quote(model_id, safe='')}/usage", auth=True
        )

    # ------------------------------------------------------------------
    # Usage
    # ------------------------------------------------------------------

    def usage_current(self) -> dict[str, Any]:
        return self._request("GET", "/usage/current", auth=True)

    def usage_remaining(self, model_id: str) -> dict[str, Any]:
        return self._request("GET", "/usage/remaining", query={"model_id": model_id}, auth=True)


__all__ = ["T1Client", "T1ClientError"]
