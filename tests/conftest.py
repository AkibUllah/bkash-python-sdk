from __future__ import annotations

import pytest
import respx

from bkash import AsyncBkashClient, BkashClient, BkashConfig, RetryPolicy

BASE = "https://tokenized.sandbox.bka.sh/v1.2.0-beta"

TOKEN_OK = {
    "statusCode": "0000",
    "statusMessage": "Successful",
    "id_token": "tok_first",
    "token_type": "Bearer",
    "expires_in": 3600,
    "refresh_token": "ref_first",
}

CREATE_OK = {
    "statusCode": "0000",
    "statusMessage": "Successful",
    "paymentID": "TR0011abc123",
    "bkashURL": "https://sandbox.payment.bkash.com/?paymentId=TR0011abc123",
    "callbackURL": "https://shop.example/bkash/callback",
    "successCallbackURL": "https://shop.example/bkash/callback?paymentID=TR0011abc123&status=success",
    "failureCallbackURL": "https://shop.example/bkash/callback?paymentID=TR0011abc123&status=failure",
    "cancelledCallbackURL": "https://shop.example/bkash/callback?paymentID=TR0011abc123&status=cancel",
    "amount": "1500.00",
    "intent": "sale",
    "currency": "BDT",
    "paymentCreateTime": "2026-10-20T14:03:11:540 GMT+0600",
    "transactionStatus": "Initiated",
    "merchantInvoiceNumber": "INV-2026-0001",
}

EXECUTE_OK = {
    "statusCode": "0000",
    "statusMessage": "Successful",
    "paymentID": "TR0011abc123",
    "trxID": "9HK7A2B3C4",
    "transactionStatus": "Completed",
    "amount": "1500.00",
    "currency": "BDT",
    "intent": "sale",
    "paymentExecuteTime": "2026-10-20T14:05:02:117 GMT+0600",
    "merchantInvoiceNumber": "INV-2026-0001",
    "payerReference": "01711000000",
    "customerMsisdn": "01711000000",
}

QUERY_OK = {
    "statusCode": "0000",
    "statusMessage": "Successful",
    "paymentID": "TR0011abc123",
    "mode": "0011",
    "paymentCreateTime": "2026-10-20T14:03:11:540 GMT+0600",
    "paymentExecuteTime": "2026-10-20T14:05:02:117 GMT+0600",
    "amount": "1500.00",
    "currency": "BDT",
    "intent": "sale",
    "merchantInvoice": "INV-2026-0001",
    "transactionStatus": "Completed",
    "verificationStatus": "Complete",
    "payerReference": "01711000000",
    "trxID": "9HK7A2B3C4",
}

REFUND_OK = {
    "statusCode": "0000",
    "statusMessage": "Successful",
    "completedTime": "2026-10-21T10:00:00:000 GMT+0600",
    "transactionStatus": "Completed",
    "originalTrxID": "9HK7A2B3C4",
    "refundTrxID": "9HK7R5F6G7",
    "amount": "500.00",
    "currency": "BDT",
    "charge": "0.00",
}

SEARCH_OK = {
    "statusCode": "0000",
    "statusMessage": "Successful",
    "trxID": "9HK7A2B3C4",
    "transactionStatus": "Completed",
    "transactionType": "bKash Tokenized Checkout via API",
    "amount": "1500.00",
    "currency": "BDT",
    "customerMsisdn": "01711000000",
    "organizationShortCode": "50022",
    "initiationTime": "2026-10-20T14:05:00:000 GMT+0600",
    "completedTime": "2026-10-20T14:05:02:117 GMT+0600",
}


@pytest.fixture
def config() -> BkashConfig:
    return BkashConfig.sandbox(
        "app_key_sandbox",
        "app_secret_sandbox",
        "sandbox_user",
        "sandbox_pass",
        retry=RetryPolicy(max_attempts=3, base_delay=0.01, max_delay=0.05, jitter=False),
    )


@pytest.fixture
def mock_api():
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        yield router


@pytest.fixture
def grant_route(mock_api):
    return mock_api.post("/tokenized/checkout/token/grant").respond(200, json=TOKEN_OK)


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def client(config, mock_api, grant_route, sleeps):
    with BkashClient(config, sleep=sleeps.append) as c:
        yield c


@pytest.fixture
async def async_client(config, mock_api, grant_route, sleeps):
    async def record(delay: float) -> None:
        sleeps.append(delay)

    async with AsyncBkashClient(config, sleep=record) as c:
        yield c
