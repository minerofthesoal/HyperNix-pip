"""t1api.config — environment-variable configuration for the T1 API.

All values are overridable via environment variables so the module can be
"easy to mount into an existing Python server" without editing code. A
``.env`` file is loaded if present (and ``python-dotenv`` is installed);
missing python-dotenv is a soft failure — env vars set some other way still
work.

Nothing in this module holds secrets by value in a way that gets logged or
serialized to ``GET /config`` — see :meth:`T1APIConfig.public_dict`, which
is an explicit allowlist rather than "everything except a blocklist" so a
newly-added secret field can't accidentally leak through that endpoint.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv_if_present(path: str | Path = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(dotenv_path=p)
    except ImportError:
        # Soft-fail: minimal hand-rolled parser so .env still works without
        # the optional python-dotenv dependency installed.
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def _bool_env(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class T1APIConfig:
    """Runtime configuration, resolved once at ``create_app()`` time.

    Every field has an environment-variable equivalent (documented inline)
    so deployments never need to fork this file.
    """

    # --- General -------------------------------------------------------
    mount_prefix: str = field(default_factory=lambda: os.environ.get("T1_MOUNT_PREFIX", ""))
    environment: str = field(default_factory=lambda: os.environ.get("T1_ENVIRONMENT", "development"))

    # --- Storage ---------------------------------------------------------
    db_path: str | None = field(default_factory=lambda: os.environ.get("T1_DB_PATH"))

    # --- Model registry --------------------------------------------------
    registry_path: str | None = field(default_factory=lambda: os.environ.get("T1_MODEL_REGISTRY_PATH"))
    enable_example_models: bool = field(
        default_factory=lambda: _bool_env("T1_ENABLE_EXAMPLE_MODELS", False)
    )

    # --- Routing (Beta 2) -------------------------------------------------
    routing_policy_path: str | None = field(
        default_factory=lambda: os.environ.get("T1_ROUTING_POLICY_PATH")
    )

    # --- Auth --------------------------------------------------------------
    # HMAC secret used to sign scoped tokens minted by POST /auth/token.
    # Never logged; never returned by any endpoint. Rotate by changing this
    # value — outstanding scoped tokens become invalid immediately (they
    # are stateless, so there is nothing else to revoke).
    token_secret: str = field(
        default_factory=lambda: os.environ.get("T1_TOKEN_SECRET", "")
    )
    scoped_token_default_ttl_seconds: int = field(
        default_factory=lambda: int(os.environ.get("T1_TOKEN_DEFAULT_TTL", "3600"))
    )

    # --- Usage -------------------------------------------------------------
    usage_reset_period_seconds: float = field(
        default_factory=lambda: float(os.environ.get("T1_USAGE_RESET_PERIOD_SECONDS", str(86400.0)))
    )

    # --- Networking guardrails (enforced fully starting Beta 2/3; Beta 1
    # only records the config value so the contract is stable) ------------
    cors_allow_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip() for o in os.environ.get("T1_CORS_ALLOW_ORIGINS", "").split(",") if o.strip()
        )
    )

    @classmethod
    def from_env(cls, *, load_dotenv: bool = True, dotenv_path: str | Path = ".env") -> T1APIConfig:
        if load_dotenv:
            _load_dotenv_if_present(dotenv_path)
        return cls()

    def public_dict(self) -> dict[str, object]:
        """Explicit allowlist of config surfaced by GET /config. Never
        includes ``token_secret`` or any future secret field."""
        return {
            "environment": self.environment,
            "mount_prefix": self.mount_prefix,
            "storage_backend": "sqlite",
            "enable_example_models": self.enable_example_models,
            "routing_policy_path": self.routing_policy_path,
            "usage_reset_period_seconds": self.usage_reset_period_seconds,
            "scoped_token_default_ttl_seconds": self.scoped_token_default_ttl_seconds,
        }


__all__ = ["T1APIConfig"]
