"""Token lifecycle: grant once, reuse until near expiry, refresh, fall back to a fresh grant."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from bkash._core import GRANT_PATH, REFRESH_PATH, logger, parse_model, token_headers
from bkash.config import BkashConfig
from bkash.exceptions import BkashAuthError
from bkash.models import TokenResponse

Clock = Callable[[], float]


@dataclass
class TokenState:
    id_token: str
    refresh_token: str | None
    expires_at: float

    def is_fresh(self, now: float, margin: int) -> bool:
        return now + margin < self.expires_at


class _BaseTokenManager:
    def __init__(self, config: BkashConfig, clock: Clock = time.monotonic) -> None:
        self._config = config
        self._clock = clock
        self._state: TokenState | None = None

    @property
    def current(self) -> TokenState | None:
        return self._state

    def invalidate(self) -> None:
        self._state = None

    def _grant_request(self) -> tuple[str, dict[str, str], dict[str, str]]:
        return (
            GRANT_PATH,
            token_headers(self._config),
            {"app_key": self._config.app_key, "app_secret": self._config.app_secret},
        )

    def _refresh_request(self, refresh_token: str) -> tuple[str, dict[str, str], dict[str, str]]:
        return (
            REFRESH_PATH,
            token_headers(self._config),
            {
                "app_key": self._config.app_key,
                "app_secret": self._config.app_secret,
                "refresh_token": refresh_token,
            },
        )

    def _store(self, response: httpx.Response) -> str:
        token = parse_model(response, TokenResponse, auth_call=True)
        self._state = TokenState(
            id_token=token.id_token,
            refresh_token=token.refresh_token,
            expires_at=self._clock() + token.expires_in,
        )
        return token.id_token

    def _needs_token(self) -> bool:
        return self._state is None or not self._state.is_fresh(
            self._clock(), self._config.token_refresh_margin
        )


class TokenManager(_BaseTokenManager):
    """Thread-safe synchronous token manager."""

    def __init__(
        self,
        config: BkashConfig,
        send: Callable[[str, dict[str, str], dict[str, str]], httpx.Response],
        clock: Clock = time.monotonic,
    ) -> None:
        super().__init__(config, clock)
        self._send = send
        self._lock = threading.Lock()

    def get_token(self, force: bool = False) -> str:
        with self._lock:
            if not force and not self._needs_token() and self._state is not None:
                return self._state.id_token
            if self._state is not None and self._state.refresh_token and not force:
                try:
                    return self._store(
                        self._send(*self._refresh_request(self._state.refresh_token))
                    )
                except BkashAuthError as exc:
                    logger.info(
                        "token refresh rejected (%s); falling back to grant", exc.error_code
                    )
            return self._store(self._send(*self._grant_request()))


class AsyncTokenManager(_BaseTokenManager):
    """asyncio-safe token manager."""

    def __init__(
        self,
        config: BkashConfig,
        send: Callable[[str, dict[str, str], dict[str, str]], Awaitable[httpx.Response]],
        clock: Clock = time.monotonic,
    ) -> None:
        super().__init__(config, clock)
        self._send = send
        self._lock = asyncio.Lock()

    async def get_token(self, force: bool = False) -> str:
        async with self._lock:
            if not force and not self._needs_token() and self._state is not None:
                return self._state.id_token
            if self._state is not None and self._state.refresh_token and not force:
                try:
                    response = await self._send(*self._refresh_request(self._state.refresh_token))
                    return self._store(response)
                except BkashAuthError as exc:
                    logger.info(
                        "token refresh rejected (%s); falling back to grant", exc.error_code
                    )
            return self._store(await self._send(*self._grant_request()))
