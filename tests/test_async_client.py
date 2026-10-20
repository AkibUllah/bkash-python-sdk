import httpx
import pytest

from bkash import BkashTimeoutError, TransactionStatus
from tests.conftest import CREATE_OK, EXECUTE_OK, REFUND_OK


async def test_async_create_and_execute(async_client, mock_api, grant_route):
    mock_api.post("/tokenized/checkout/create").respond(200, json=CREATE_OK)
    mock_api.post("/tokenized/checkout/execute").respond(200, json=EXECUTE_OK)

    created = await async_client.create_payment(
        amount="1500.00",
        payer_reference="01711000000",
        callback_url="https://shop.example/bkash/callback",
        merchant_invoice_number="INV-2026-0001",
    )
    executed = await async_client.execute_payment(created.payment_id)
    assert created.transaction_status is TransactionStatus.INITIATED
    assert executed.is_completed
    assert grant_route.call_count == 1


async def test_async_refund_and_retry(async_client, mock_api, sleeps):
    route = mock_api.post("/tokenized/checkout/payment/refund")
    route.side_effect = [httpx.Response(502, json={}), httpx.Response(200, json=REFUND_OK)]
    refund = await async_client.refund(
        payment_id="TR0011abc123", trx_id="9HK7A2B3C4", amount="500.00", sku="S", reason="r"
    )
    assert refund.refund_trx_id == "9HK7R5F6G7"
    assert sleeps == [0.01]


async def test_async_timeout_exhausts(async_client, mock_api):
    mock_api.post("/tokenized/checkout/execute").side_effect = httpx.ReadTimeout("slow")
    with pytest.raises(BkashTimeoutError):
        await async_client.execute_payment("x")


async def test_async_token_rejected_then_refreshed(async_client, mock_api, grant_route):
    route = mock_api.post("/tokenized/checkout/execute")
    route.side_effect = [
        httpx.Response(200, json={"statusCode": "2001", "statusMessage": "Invalid App Key"}),
        httpx.Response(200, json=EXECUTE_OK),
    ]
    executed = await async_client.execute_payment("x")
    assert executed.is_completed
    assert grant_route.call_count == 2
