"""hypernix.t1sdk — the official Python SDK for the HyperNix T1 API.

Zero dependencies beyond the standard library, on purpose: an SDK is a
*client*, and it must import on machines that never install the
``hypernix[t1api]`` server extra.

    from hypernix.t1sdk import T1Client

    client = T1Client("https://t1.example.com", credential="T1_...")
    print(client.status().t1_api_version)

    for model in client.list_models():
        print(model.model_id, model.status)

    decision = client.route(input_tokens=1200)
    print("use", decision.model_id, "because", decision.reason)

Errors are a hierarchy, so you catch the category you care about::

    from hypernix.t1sdk import T1QuotaError

    try:
        decision = client.route(model_id="nanonix-mini")
    except T1QuotaError as exc:
        print("exhausted:", exc.code, "retry after", exc.retry_after)

mTLS and a private CA::

    from hypernix.t1sdk import T1Client, TLSConfig

    client = T1Client(
        "https://t1.internal",
        credential=key,
        tls=TLSConfig(
            client_certfile="client.crt",
            client_keyfile="client.key",
            ca_certs="internal-ca.pem",
        ),
    )

``hypernix.waiter.client.T1Client`` is a thin compatibility layer over
this SDK, keeping the Beta 1/2 method names the ``waiter`` CLI was
written against.
"""
from __future__ import annotations

from .client import T1Client
from .errors import (
    T1AuthError,
    T1Error,
    T1NotFoundError,
    T1NotSupportedError,
    T1QuotaError,
    T1ServerError,
    T1TransportError,
    T1ValidationError,
)
from .models import (
    CostReport,
    Event,
    Job,
    KeyInfo,
    Model,
    ModelUsage,
    Module,
    RoutingDecision,
    Server,
    ServerStatus,
)
from .transport import HTTPTransport, Response, RetryPolicy, TLSConfig

# Tracks the T1 API's own version (t1api/version.py), not the hypernix
# package's: the SDK implements an API contract, and its version should
# say which one.
__sdk_version__ = "1.0.26.8.0.1"

__all__ = [
    "__sdk_version__",
    "T1Client",
    "HTTPTransport",
    "Response",
    "RetryPolicy",
    "TLSConfig",
    "T1Error",
    "T1AuthError",
    "T1NotFoundError",
    "T1NotSupportedError",
    "T1QuotaError",
    "T1ServerError",
    "T1TransportError",
    "T1ValidationError",
    "CostReport",
    "Event",
    "Job",
    "KeyInfo",
    "Model",
    "ModelUsage",
    "Module",
    "RoutingDecision",
    "Server",
    "ServerStatus",
]
