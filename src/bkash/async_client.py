"""Asynchronous client (same surface as BkashClient, awaitable)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from decimal import Decimal
from types import TracebackType
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from bkash._core import (
    CREATE_PATH,
    EXECUTE_PATH,
    QUERY_PATH,
    REFUND_PATH,
    SEARCH_PATH,
    api_headers,
    build_timeout,
    is_unauthorized,
    logger,
    parse_model,
)
from bkash.auth import AsyncTokenManager
from bkash.config import BkashConfig
from bkash.exceptions import BkashNetworkError, BkashTimeoutError
from bkash.models import (
    CreatePaymentRequest,
    CreatePaymentResponse,
    ExecutePaymentResponse,
    QueryPaymentResponse,
    RefundRequest,
    RefundResponse,
    SearchTransactionResponse,
)

M = TypeVar("M", bound=BaseModel)


class AsyncBkashClient:
    """Async client for the bKash Tokenized Checkout API.

    async with AsyncBkashClient(config) as client:
        created = await client.create_payment(amount="1500.00", ...)
    """

    def __init__(
        self,
        config: BkashConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=config.resolved_base_url, timeout=build_timeout(config)
        )
        self._sleep = sleep
        self._tokens = AsyncTokenManager(config, self._send_token_request, clock=clock)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> AsyncBkashClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # -- public API ------------------------------------------------------------
    async def grant_token(self) -> str:
        return await self._tokens.get_token(force=True)

    async def create_payment(
        self,
        *,
        amount: Decimal | str | int,
        payer_reference: str,
        callback_url: str,
        merchant_invoice_number: str,
        intent: str = "sale",
        mode: str = "0011",
        agreement_id: str | None = None,
    ) -> CreatePaymentResponse:
        request = CreatePaymentRequest(
            amount=amount,
            payer_reference=payer_reference,
            callback_url=callback_url,
            merchant_invoice_number=merchant_invoice_number,
            intent=intent,
            mode=mode,
            agreement_id=agreement_id,
        )
        return await self.create_payment_from_request(request)

    async def create_payment_from_request(
        self, request: CreatePaymentRequest
    ) -> CreatePaymentResponse:
        return await self._call(CREATE_PATH, request.to_wire(), CreatePaymentResponse)

    async def execute_payment(self, payment_id: str) -> ExecutePaymentResponse:
        return await self._call(EXECUTE_PATH, {"paymentID": payment_id}, ExecutePaymentResponse)

    async def query_payment(self, payment_id: str) -> QueryPaymentResponse:
        return await self._call(QUERY_PATH, {"paymentID": payment_id}, QueryPaymentResponse)

    async def refund(
        self,
        *,
        payment_id: str,
        trx_id: str,
        amount: Decimal | str | int,
        sku: str,
        reason: str,
    ) -> RefundResponse:
        request = RefundRequest(
            payment_id=payment_id,
            trx_id=trx_id,
            amount=amount,
            sku=sku,
            reason=reason,
        )
        return await self._call(REFUND_PATH, request.to_wire(), RefundResponse)

    async def search_transaction(self, trx_id: str) -> SearchTransactionResponse:
        return await self._call(SEARCH_PATH, {"trxID": trx_id}, SearchTransactionResponse)

    # -- internals -------------------------------------------------------------
    async def _send_token_request(
        self, path: str, headers: dict[str, str], body: dict[str, str]
    ) -> httpx.Response:
        return await self._post_with_retry(path, headers, body)

    async def _call(self, path: str, body: dict[str, Any], model: type[M]) -> M:
        token = await self._tokens.get_token()
        response = await self._post_with_retry(path, api_headers(self.config, token), body)
        if is_unauthorized(response):
            logger.info("token rejected on %s; refreshing once", path)
            token = await self._tokens.get_token(force=True)
            response = await self._post_with_retry(path, api_headers(self.config, token), body)
        return parse_model(response, model)

    async def _post_with_retry(
        self, path: str, headers: dict[str, str], body: dict[str, Any]
    ) -> httpx.Response:
        policy = self.config.retry
        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self._http.post(path, json=body, headers=headers)
            except httpx.TimeoutException as exc:
                if not policy.can_retry(attempt):
                    raise BkashTimeoutError(f"{path} timed out after {attempt} attempt(s)") from exc
                await self._backoff(policy.delay_for(attempt), path, attempt, repr(exc))
                continue
            except httpx.NetworkError as exc:
                if not policy.can_retry(attempt):
                    raise BkashNetworkError(f"{path}: {exc}") from exc
                await self._backoff(policy.delay_for(attempt), path, attempt, repr(exc))
                continue
            if policy.should_retry_response(response) and policy.can_retry(attempt):
                await self._backoff(
                    policy.delay_for(attempt), path, attempt, f"HTTP {response.status_code}"
                )
                continue
            return response

    async def _backoff(self, delay: float, path: str, attempt: int, reason: str) -> None:
        logger.warning(
            "retrying %s (attempt %s) after %s: sleeping %.2fs", path, attempt, reason, delay
        )
        if delay > 0:
            await self._sleep(delay)
