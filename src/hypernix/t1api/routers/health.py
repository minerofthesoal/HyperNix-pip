"""``GET /health`` and ``GET /status``.

``/health`` is deliberately minimal — no auth, no database access, no
configuration inspection — because it is what a load balancer polls
every few seconds and what an mTLS deployment exempts from client-cert
requirements. It answers exactly one question: is this process serving?

``/status`` is the operator-facing view: version, backend, model count,
and (Beta 3) which protections are actually switched on. It reports
whether each secret is *set*, never its value, and surfaces the
production-config warnings so an operator can see a misconfiguration
from the outside instead of by reading the deployment's environment.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import __t1api_version__, __t1api_version_long__
from ..deps import get_config, get_registry, get_request_id
from ..schemas import HealthResponse, StatusResponse
from ..version import T1_VERSION

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(request_id: str = Depends(get_request_id)) -> HealthResponse:
    return HealthResponse(status="ok", request_id=request_id)


@router.get("/status", response_model=StatusResponse)
def status(
    request_id: str = Depends(get_request_id),
    config=Depends(get_config),
    registry=Depends(get_registry),
) -> StatusResponse:
    import hypernix

    tls = config.tls_settings()
    warnings = config.production_problems()
    return StatusResponse(
        status="ok",
        environment=config.environment,
        t1_api_version=__t1api_version__,
        t1_api_version_long=__t1api_version_long__,
        t1_version=T1_VERSION.to_dict(),
        hypernix_version=getattr(hypernix, "__version__", "unknown"),
        # The betas ended here. "t1-1.0" is the generation a client pins
        # against; the field keeps its name because Beta 3 clients read
        # it and a renamed field is a breaking change for a cosmetic win.
        beta="t1-1.0",
        model_count=len(registry),
        storage_backend=config.storage_backend,
        tls_enabled=tls.tls_enabled,
        mtls_mode="proxy" if tls.behind_proxy else ("direct" if tls.mtls_enabled else "off"),
        rate_limit_enabled=config.rate_limit_enabled,
        audit_enabled=config.audit_enabled,
        network_policy_enabled=config.network_policy_enabled,
        allow_unlisted_clients=config.allow_unlisted_clients,
        remote_deployment_enabled=bool(config.deploy_secret),
        secrets_configured=config.describe_secrets(),
        production_ready=not warnings,
        # Reported on every deployment, not only production ones: seeing
        # what *would* block a production start is exactly what you want
        # while still in staging. The list names settings, never values.
        lmstudio_bridge_enabled=config.lmstudio_enabled,
        lmstudio_configured=bool(config.lmstudio_url),
        hyperlink_enabled=config.hyperlink_enabled,
        production_warnings=warnings,
        request_id=request_id,
    )


__all__ = ["router"]
