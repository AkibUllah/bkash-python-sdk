"""Synchronous client."""

from __future__ import annotations

import time
from collections.abc import Callable
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
from bkash.auth import TokenManager
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


class BkashClient:
    """Sync client for the bKash Tokenized Checkout API.

        with BkashClient(config) as client:
            created = client.create_payment(amount="1500.00", ...)
            ...
            executed = client.execute_payment(created.payment_id)

    Pass `http_client` to reuse a configured httpx.Client (proxies, custom transport, mocking).
    """

    def __init__(
        self,
        config: BkashConfig,
        *,
        http_client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(
            base_url=config.resolved_base_url, timeout=build_timeout(config)
        )
        self._sleep = sleep
        self._tokens = TokenManager(config, self._send_token_request, clock=clock)

    # -- lifecycle -------------------------------------------------------------
    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> BkashClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- public API ------------------------------------------------------------
    def grant_token(self) -> str:
        """Force a fresh token grant. Normally unnecessary: tokens are managed automatically."""
        return self._tokens.get_token(force=True)

    def create_payment(
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
        return self.create_payment_from_request(request)

    def create_payment_from_request(self, request: CreatePaymentRequest) -> CreatePaymentResponse:
        return self._call(CREATE_PATH, request.to_wire(), CreatePaymentResponse)

    def execute_payment(self, payment_id: str) -> ExecutePaymentResponse:
        return self._call(EXECUTE_PATH, {"paymentID": payment_id}, ExecutePaymentResponse)

    def query_payment(self, payment_id: str) -> QueryPaymentResponse:
        return self._call(QUERY_PATH, {"paymentID": payment_id}, QueryPaymentResponse)

    def refund(
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
        return self._call(REFUND_PATH, request.to_wire(), RefundResponse)

    def search_transaction(self, trx_id: str) -> SearchTransactionResponse:
        return self._call(SEARCH_PATH, {"trxID": trx_id}, SearchTransactionResponse)

    # -- internals -------------------------------------------------------------
    def _send_token_request(
        self, path: str, headers: dict[str, str], body: dict[str, str]
    ) -> httpx.Response:
        return self._post_with_retry(path, headers, body)

    def _call(self, path: str, body: dict[str, Any], model: type[M]) -> M:
        token = self._tokens.get_token()
        response = self._post_with_retry(path, api_headers(self.config, token), body)
        if is_unauthorized(response):
            logger.info("token rejected on %s; refreshing once", path)
            token = self._tokens.get_token(force=True)
            response = self._post_with_retry(path, api_headers(self.config, token), body)
        return parse_model(response, model)

    def _post_with_retry(
        self, path: str, headers: dict[str, str], body: dict[str, Any]
    ) -> httpx.Response:
        policy = self.config.retry
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._http.post(path, json=body, headers=headers)
            except httpx.TimeoutException as exc:
                if not policy.can_retry(attempt):
                    raise BkashTimeoutError(f"{path} timed out after {attempt} attempt(s)") from exc
                self._backoff(policy.delay_for(attempt), path, attempt, repr(exc))
                continue
            except httpx.NetworkError as exc:
                if not policy.can_retry(attempt):
                    raise BkashNetworkError(f"{path}: {exc}") from exc
                self._backoff(policy.delay_for(attempt), path, attempt, repr(exc))
                continue
            if policy.should_retry_response(response) and policy.can_retry(attempt):
                self._backoff(
                    policy.delay_for(attempt), path, attempt, f"HTTP {response.status_code}"
                )
                continue
            return response

    def _backoff(self, delay: float, path: str, attempt: int, reason: str) -> None:
        logger.warning(
            "retrying %s (attempt %s) after %s: sleeping %.2fs", path, attempt, reason, delay
        )
        if delay > 0:
            self._sleep(delay)
