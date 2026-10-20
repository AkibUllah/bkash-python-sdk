"""Client configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from bkash.retry import RetryPolicy

SANDBOX_BASE_URL = "https://tokenized.sandbox.bka.sh/v1.2.0-beta"
PRODUCTION_BASE_URL = "https://tokenized.pay.bka.sh/v1.2.0-beta"


class Environment(str, Enum):
    SANDBOX = "sandbox"
    PRODUCTION = "production"

    @property
    def base_url(self) -> str:
        return SANDBOX_BASE_URL if self is Environment.SANDBOX else PRODUCTION_BASE_URL


@dataclass(frozen=True)
class BkashConfig:
    """Everything the client needs. Credentials are the four values bKash issues per merchant.

    `token_refresh_margin` is how many seconds before expiry a token is considered stale,
    so a request never goes out with a token that dies in flight.
    """

    app_key: str
    app_secret: str
    username: str
    password: str
    environment: Environment = Environment.SANDBOX
    base_url: str | None = None
    timeout: float = 30.0
    connect_timeout: float = 10.0
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    token_refresh_margin: int = 60
    user_agent: str = "bkash-checkout-python/0.1.0"

    def __post_init__(self) -> None:
        for name in ("app_key", "app_secret", "username", "password"):
            if not getattr(self, name):
                raise ValueError(f"BkashConfig.{name} must not be empty")
        if self.timeout <= 0 or self.connect_timeout <= 0:
            raise ValueError("timeouts must be positive")

    @property
    def resolved_base_url(self) -> str:
        return (self.base_url or self.environment.base_url).rstrip("/")

    @classmethod
    def sandbox(
        cls, app_key: str, app_secret: str, username: str, password: str, **kw: Any
    ) -> BkashConfig:
        return cls(app_key, app_secret, username, password, environment=Environment.SANDBOX, **kw)

    @classmethod
    def production(
        cls, app_key: str, app_secret: str, username: str, password: str, **kw: Any
    ) -> BkashConfig:
        return cls(
            app_key, app_secret, username, password, environment=Environment.PRODUCTION, **kw
        )

    @classmethod
    def from_env(cls, prefix: str = "BKASH_") -> BkashConfig:
        """Build from BKASH_APP_KEY/APP_SECRET/USERNAME/PASSWORD and optional BKASH_ENVIRONMENT."""
        missing = [
            n
            for n in ("APP_KEY", "APP_SECRET", "USERNAME", "PASSWORD")
            if not os.getenv(prefix + n)
        ]
        if missing:
            raise ValueError(
                f"missing environment variables: {', '.join(prefix + m for m in missing)}"
            )
        env = Environment(os.getenv(prefix + "ENVIRONMENT", "sandbox").lower())
        return cls(
            app_key=os.environ[prefix + "APP_KEY"],
            app_secret=os.environ[prefix + "APP_SECRET"],
            username=os.environ[prefix + "USERNAME"],
            password=os.environ[prefix + "PASSWORD"],
            environment=env,
            base_url=os.getenv(prefix + "BASE_URL") or None,
            timeout=float(os.getenv(prefix + "TIMEOUT", "30")),
        )
