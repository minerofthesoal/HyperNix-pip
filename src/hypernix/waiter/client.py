"""waiter.client — the waiter CLI's T1 API client.

As of Beta 3 this is a **compatibility layer over**
:mod:`hypernix.t1sdk`, not a second implementation. The SDK owns the
transport (retries, backoff, mTLS, multipart, error mapping) and the
complete endpoint surface; this module keeps the method names and the
dict-returning shape that the Beta 1/2 ``waiter`` CLI was written
against, so nothing in ``waiter/cli.py`` had to change and any script
built on ``waiter.client`` keeps working.

Why keep it at all rather than pointing the CLI at the SDK directly:

* **Names.** ``list_models()`` returning a *dict* (with ``count`` and
  ``models``) is what the CLI's table renderers consume. The SDK's
  ``list_models()`` returns typed objects. Renaming across both would
  churn the CLI for no gain, so the shim translates instead.
* **One exception type.** The CLI catches :class:`T1ClientError`
  everywhere. It is now an alias for the SDK's :class:`T1Error`, so that
  single ``except`` still catches every failure the SDK can raise —
  including the more specific subclasses.

New code should import :class:`hypernix.t1sdk.T1Client` directly and get
the typed objects.
"""
from __future__ import annotations

from typing import Any

from ..t1sdk import T1Client as _SDKClient
from ..t1sdk.errors import T1Error
from ..t1sdk.transport import HTTPTransport, RetryPolicy, TLSConfig

# The CLI catches exactly this name. Aliasing (rather than subclassing)
# means every SDK exception — T1AuthError, T1QuotaError, and the rest —
# is caught by `except T1ClientError`, which is what the CLI wants.
T1ClientError = T1Error


class T1Client(_SDKClient):
    """Talks to one T1 API server, with the Beta 1/2 method surface.

    ``base_url`` should not include a trailing slash (e.g.
    ``https://myserver.ts.net:8000``). Constructor arguments are the ones
    the CLI has always passed; everything else comes from the SDK.
    """

    def __init__(
        self,
        base_url: str,
        credential: str | None = None,
        timeout: float = 15.0,
        *,
        retry: RetryPolicy | None = None,
        tls: TLSConfig | None = None,
        transport: HTTPTransport | None = None,
    ) -> None:
        super().__init__(
            base_url,
            credential=credential,
            timeout=timeout,
            retry=retry,
            tls=tls,
            transport=transport,
            user_agent="hypernix-waiter",
        )

    # ------------------------------------------------------------------
    # Overrides returning the raw envelope the CLI's renderers expect.
    # Each one is the SDK call with the typing peeled back off — the
    # request itself, and all its error handling, is the SDK's.
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:  # type: ignore[override]
        return self._get("/status")

    def config(self) -> dict[str, Any]:
        return self._get("/config")

    def list_models(self) -> dict[str, Any]:  # type: ignore[override]
        return self.list_models_raw()

    def get_model(self, model_id: str) -> dict[str, Any]:  # type: ignore[override]
        from ..t1sdk.client import _q

        return self._get(f"/models/{_q(model_id)}")

    def model_usage(self, model_id: str) -> dict[str, Any]:  # type: ignore[override]
        from ..t1sdk.client import _q

        return self._get(f"/models/{_q(model_id)}/usage", auth=True)

    def usage_remaining(self, model_id: str) -> dict[str, Any]:  # type: ignore[override]
        return self._get("/usage/remaining", query={"model_id": model_id}, auth=True)

    def route(self, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        return super().route(**kwargs).raw

    def list_servers(self) -> dict[str, Any]:  # type: ignore[override]
        return self._get("/servers", auth=True)

    def register_server(self, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        return {"server": super().register_server(**kwargs).raw}

    def update_server(self, server_id: str, **fields: Any) -> dict[str, Any]:  # type: ignore[override]
        from ..t1sdk.client import _q

        return self.transport.request(
            "PATCH", f"/servers/{_q(server_id)}", body=fields, auth=True
        ).body

    def list_modules(self) -> dict[str, Any]:  # type: ignore[override]
        return self._get("/modules", auth=True)

    def create_module(self, *, name: str, version: str, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        return {"module": super().create_module(name=name, version=version, **kwargs).raw}

    def upload_module_local(self, module_id: str, file_path: str) -> dict[str, Any]:
        """Beta 1/2 name for the SDK's ``upload_module``."""
        return {"module": self.upload_module(module_id, file_path).raw}

    def get_job(self, job_id: str) -> dict[str, Any]:  # type: ignore[override]
        from ..t1sdk.client import _q

        return self._get(f"/jobs/{_q(job_id)}", auth=True)

    def cancel_job(self, job_id: str) -> dict[str, Any]:  # type: ignore[override]
        from ..t1sdk.client import _q

        return self._post(f"/jobs/{_q(job_id)}/cancel", auth=True, idempotent=True)

    def list_events(self, *, limit: int = 50, since_id: str | None = None, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        return self._get(
            "/events",
            query={"limit": limit, "since_id": since_id, "type": kwargs.get("event_type")},
        )

    def billing_balance(self) -> dict[str, Any]:
        return self.balance()

    def billing_transactions(self) -> dict[str, Any]:
        return self._get("/billing/transactions", auth=True)

    def redeem_payment_token(self, token: str, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        return super().redeem_payment_token(token, **kwargs)


__all__ = ["T1Client", "T1ClientError", "RetryPolicy", "TLSConfig"]
