"""t1api.deploy — the deployment coordinator.

One class, :class:`DeploymentCoordinator`, and the job handlers it
exposes. It is the *only* place allowed to depend on the module
registry, the server registry, and the transport at the same time —
keeping that three-way coupling out of all three, so each stays
independently testable and independently reviewable.

The two jobs it provides:

``module_sync``
    Push a module's bytes to one registered server. Beta 2 had this
    handler record a deployment without moving anything; Beta 3 keeps
    its exact contract (same job kind, same payload, same result keys,
    so an existing client sees no change) and makes it actually
    transfer. The trust check that Beta 2 already performed still runs
    *first* — the address is only read from the registry after the
    server has been confirmed trusted, so an untrusted server never gets
    as far as having its address dialled.

``module_fetch``
    Pull a module's registered remote source into local storage. Split
    from ``module_sync`` deliberately: they move bytes in opposite
    directions with opposite threat models (push goes to a server *we*
    trust; fetch comes from a URL we merely validated), and one handler
    doing both would have to hold both sets of assumptions at once.

Both handlers are cancellation-aware in the only place cancellation can
be honoured without leaving a half-written file: before the transfer
starts, and between servers in a multi-target sync. A single HTTP
transfer is not interruptible mid-flight through this interface, so the
handler doesn't pretend otherwise — it checks the flag at the boundaries
it can actually act on.
"""
from __future__ import annotations

import logging
from typing import Any

from .audit import AuditCategory, AuditLog, AuditOutcome
from .errors import T1APIError, T1ErrorCode
from .modules import ModuleRegistry
from .servers import ServerRegistry
from .transport import ModuleTransport, TransferResult

logger = logging.getLogger(__name__)


class DeploymentCoordinator:
    """Composes module registry + server registry + transport."""

    def __init__(
        self,
        modules: ModuleRegistry,
        servers: ServerRegistry,
        transport: ModuleTransport,
        *,
        audit: AuditLog | None = None,
    ) -> None:
        self.modules = modules
        self.servers = servers
        self.transport = transport
        self.audit = audit

    # ------------------------------------------------------------------
    # Push
    # ------------------------------------------------------------------

    def push_to_server(self, module_id: str, server_id: str, *, actor_key_id: str = "") -> TransferResult:
        """Push one module to one server. Trust is checked before the
        address is even read."""
        server = self.servers.require_trusted(server_id)
        entry = self.modules.require(module_id)
        content = self.modules.read_content(module_id)

        try:
            result = self.transport.push_module(
                server_address=server.address,
                module_id=module_id,
                content=content,
                metadata={
                    "name": entry.name,
                    "version": entry.version,
                    "checksum": entry.checksum,
                },
            )
        except T1APIError as exc:
            self._audit(
                "module.deploy",
                outcome=AuditOutcome.FAILURE,
                actor_key_id=actor_key_id,
                resource_id=module_id,
                details={"server_id": server_id, "error_code": exc.code.value, "message": exc.message},
            )
            raise

        self.modules.mark_synced(module_id, server_id)
        self._audit(
            "module.deploy",
            outcome=AuditOutcome.SUCCESS,
            actor_key_id=actor_key_id,
            resource_id=module_id,
            details={
                "server_id": server_id,
                "bytes": result.bytes_transferred,
                "checksum": result.checksum[:16],
            },
        )
        return result

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    def fetch_remote_source(self, module_id: str, *, actor_key_id: str = "") -> TransferResult:
        """Fetch a module's registered remote source into local storage.

        The URL comes from the registry entry, not from the job payload
        — a job payload is client-influenced, and letting it name a URL
        would reintroduce exactly the SSRF hole that registering the
        source through the validated path closes.
        """
        entry = self.modules.require(module_id)
        if not entry.source_url:
            raise T1APIError(
                T1ErrorCode.MODULE_UPLOAD_REJECTED,
                f"Module '{module_id}' has no registered remote source to fetch.",
                details={"module_id": module_id},
                http_status=409,
            )
        # Stage into a temporary file under the module's own storage
        # directory, then hand the bytes to the registry, which does the
        # sanitized final placement. Two steps, but the transport never
        # decides where content lands and the registry never speaks HTTP.
        staging = self.modules.storage_dir / module_id / ".incoming"
        allow_private = self.transport.allow_private_targets
        try:
            result = self.transport.fetch_source(
                entry.source_url, destination=staging, allow_private=allow_private
            )
            content = staging.read_bytes()
            self.modules.stage_fetched(module_id, content=content, filename="fetched.bin")
        except T1APIError as exc:
            self._audit(
                "module.fetch",
                outcome=AuditOutcome.FAILURE,
                actor_key_id=actor_key_id,
                resource_id=module_id,
                details={"error_code": exc.code.value, "message": exc.message},
            )
            raise
        finally:
            staging.unlink(missing_ok=True)

        self._audit(
            "module.fetch",
            outcome=AuditOutcome.SUCCESS,
            actor_key_id=actor_key_id,
            resource_id=module_id,
            details={"bytes": result.bytes_transferred, "checksum": result.checksum[:16]},
        )
        return result

    # ------------------------------------------------------------------
    # Job handlers (registered with the JobQueue in t1api.app)
    # ------------------------------------------------------------------

    def module_sync_handler(self, payload: dict[str, Any], cancel_event: Any) -> dict[str, Any]:
        """``module_sync`` — push a module to one or more servers.

        Accepts Beta 2's ``{"module_id", "server_id"}`` payload and the
        Beta 3 multi-target form ``{"module_id", "server_ids": [...]}``,
        so existing clients keep working unchanged while a
        multi-server deployment doesn't need N jobs.
        """
        module_id = payload["module_id"]
        server_ids = _target_servers(payload)
        actor = payload.get("created_by", "")

        delivered: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        errors: list[T1APIError] = []
        for server_id in server_ids:
            if cancel_event is not None and cancel_event.is_set():
                # Report what actually happened rather than raising: some
                # servers may already hold the module, and a cancelled
                # deployment that silently discards that fact is worse
                # than one that says which targets it reached.
                break
            try:
                result = self.push_to_server(module_id, server_id, actor_key_id=actor)
                delivered.append({"server_id": server_id, **result.to_dict()})
            except T1APIError as exc:
                errors.append(exc)
                failed.append(
                    {"server_id": server_id, "error_code": exc.code.value, "message": exc.message}
                )

        entry = self.modules.require(module_id)
        outcome = {
            "module_id": module_id,
            "server_id": server_ids[0] if server_ids else None,
            "requested_servers": server_ids,
            "delivered": delivered,
            "failed": failed,
            "deployed_servers": entry.deployed_servers,
            "cancelled": bool(cancel_event is not None and cancel_event.is_set()),
        }
        if failed and not delivered:
            # Every target failed, so the job failed — and the reason has
            # to reach the job record rather than being buried in a result
            # payload nobody inspects on a "succeeded" job.
            #
            # Preserve the specific error code when every target failed
            # the same way, and only fall back to the generic
            # TRANSPORT_FAILED when they failed differently. A
            # single-target sync to an untrusted server should say
            # SERVER_UNTRUSTED, not "transport failed" — the caller can
            # act on the first and can only guess at the second.
            codes = {exc.code for exc in errors}
            if len(codes) == 1:
                only = errors[0]
                raise T1APIError(
                    only.code,
                    only.message if len(errors) == 1
                    else f"{only.message} (all {len(errors)} targets failed identically)",
                    details={**outcome, **only.details},
                    http_status=only.http_status,
                )
            raise T1APIError(
                T1ErrorCode.TRANSPORT_FAILED,
                f"Module sync failed for every requested server ({len(failed)}), with differing "
                f"causes: {', '.join(sorted(c.value for c in codes))}.",
                details=outcome,
                http_status=502,
            )
        return outcome

    def module_fetch_handler(self, payload: dict[str, Any], cancel_event: Any) -> dict[str, Any]:
        """``module_fetch`` — stage a module's registered remote source."""
        module_id = payload["module_id"]
        if cancel_event is not None and cancel_event.is_set():
            return {"module_id": module_id, "cancelled": True}
        result = self.fetch_remote_source(module_id, actor_key_id=payload.get("created_by", ""))
        entry = self.modules.require(module_id)
        return {
            "module_id": module_id,
            "status": entry.status.value,
            "checksum": entry.checksum,
            "size_bytes": entry.size_bytes,
            **result.to_dict(),
        }

    # ------------------------------------------------------------------

    def _audit(self, action: str, **kwargs: Any) -> None:
        if self.audit is None:
            return
        self.audit.record(
            action,
            category=AuditCategory.WRITE,
            resource_type="module",
            **kwargs,
        )


def _target_servers(payload: dict[str, Any]) -> list[str]:
    """Normalize the single- and multi-target payload forms into a list."""
    if payload.get("server_ids"):
        return [str(s) for s in payload["server_ids"]]
    if payload.get("server_id"):
        return [str(payload["server_id"])]
    raise T1APIError(
        T1ErrorCode.VALIDATION_ERROR,
        "A module_sync job needs 'server_id' or a non-empty 'server_ids'.",
        http_status=422,
    )


__all__ = ["DeploymentCoordinator"]
