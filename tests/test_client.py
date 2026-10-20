import json
from decimal import Decimal

import httpx
import pytest

from bkash import (
    BkashAPIError,
    BkashNetworkError,
    BkashTimeoutError,
    TransactionStatus,
)
from tests.conftest import CREATE_OK, EXECUTE_OK, QUERY_OK, REFUND_OK, SEARCH_OK


def test_create_payment_serialises_request_and_parses_response(client, mock_api):
    route = mock_api.post("/tokenized/checkout/create").respond(200, json=CREATE_OK)
    payment = client.create_payment(
        amount=Decimal("1500"),
        payer_reference="01711000000",
        callback_url="https://shop.example/bkash/callback",
        merchant_invoice_number="INV-2026-0001",
    )
    sent = json.loads(route.calls.last.request.content)
    assert sent == {
        "mode": "0011",
        "payerReference": "01711000000",
        "callbackURL": "https://shop.example/bkash/callback",
        "amount": "1500.00",
        "currency": "BDT",
        "intent": "sale",
        "merchantInvoiceNumber": "INV-2026-0001",
    }
    assert payment.payment_id == "TR0011abc123"
    assert payment.bkash_url.startswith("https://sandbox.payment.bkash.com/")
    assert payment.amount == Decimal("1500.00")
    assert payment.transaction_status is TransactionStatus.INITIATED
    assert payment.ok


def test_execute_query_refund_search(client, mock_api):
    mock_api.post("/tokenized/checkout/execute").respond(200, json=EXECUTE_OK)
    mock_api.post("/tokenized/checkout/payment/status").respond(200, json=QUERY_OK)
    refund_route = mock_api.post("/tokenized/checkout/payment/refund").respond(200, json=REFUND_OK)
    mock_api.post("/tokenized/checkout/general/searchTransaction").respond(200, json=SEARCH_OK)

    executed = client.execute_payment("TR0011abc123")
    assert executed.is_completed
    assert executed.trx_id == "9HK7A2B3C4"
    assert executed.customer_msisdn == "01711000000"

    status = client.query_payment("TR0011abc123")
    assert status.is_completed
    assert status.verification_status == "Complete"

    refund = client.refund(
        payment_id="TR0011abc123",
        trx_id="9HK7A2B3C4",
        amount="500",
        sku="SKU-42",
        reason="customer returned one item",
    )
    assert json.loads(refund_route.calls.last.request.content)["amount"] == "500.00"
    assert refund.refund_trx_id == "9HK7R5F6G7"
    assert refund.amount == Decimal("500.00")
    assert refund.charge == Decimal("0.00")

    txn = client.search_transaction("9HK7A2B3C4")
    assert txn.trx_id == "9HK7A2B3C4"
    assert txn.organization_short_code == "50022"


def test_api_error_with_bkash_status_code(client, mock_api):
    mock_api.post("/tokenized/checkout/execute").respond(
        200,
        json={"statusCode": "2062", "statusMessage": "The payment has already been completed"},
    )
    with pytest.raises(BkashAPIError) as exc_info:
        client.execute_payment("TR0011abc123")
    err = exc_info.value
    assert err.error_code == "2062"
    assert err.status_code == 200
    assert "already been completed" in str(err)
    assert err.response["statusCode"] == "2062"


def test_http_error_without_body_code(client, mock_api):
    mock_api.post("/tokenized/checkout/execute").respond(400, json={"errorMessage": "Bad Request"})
    with pytest.raises(BkashAPIError) as exc_info:
        client.execute_payment("x")
    assert exc_info.value.status_code == 400
    assert exc_info.value.error_code is None
    assert exc_info.value.error_message == "Bad Request"


def test_non_json_response_is_api_error(client, mock_api):
    mock_api.post("/tokenized/checkout/execute").respond(502, text="<html>bad gateway</html>")
    with pytest.raises(BkashAPIError, match="non-JSON"):
        client.execute_payment("x")


def test_server_errors_are_retried_with_backoff(client, mock_api, sleeps):
    route = mock_api.post("/tokenized/checkout/create")
    route.side_effect = [
        httpx.Response(503, json={"message": "unavailable"}),
        httpx.Response(500, json={"message": "boom"}),
        httpx.Response(200, json=CREATE_OK),
    ]
    payment = client.create_payment(
        amount="10", payer_reference="x", callback_url="https://x", merchant_invoice_number="1"
    )
    assert payment.payment_id == "TR0011abc123"
    assert route.call_count == 3
    assert sleeps == [0.01, 0.02]  # base * 2^(attempt-1), jitter disabled


def test_retries_exhausted_returns_last_server_error(client, mock_api, sleeps):
    mock_api.post("/tokenized/checkout/execute").respond(503, json={"message": "unavailable"})
    with pytest.raises(BkashAPIError) as exc_info:
        client.execute_payment("x")
    assert exc_info.value.status_code == 503
    assert len(sleeps) == 2  # 3 attempts, 2 waits


def test_timeouts_are_retried_then_raised(client, mock_api, sleeps):
    route = mock_api.post("/tokenized/checkout/execute")
    route.side_effect = httpx.ReadTimeout("slow")
    with pytest.raises(BkashTimeoutError, match="after 3 attempt"):
        client.execute_payment("x")
    assert route.call_count == 3
    assert sleeps == [0.01, 0.02]


def test_connection_error_then_success(client, mock_api):
    route = mock_api.post("/tokenized/checkout/execute")
    route.side_effect = [httpx.ConnectError("refused"), httpx.Response(200, json=EXECUTE_OK)]
    assert client.execute_payment("x").is_completed
    assert route.call_count == 2


def test_connection_errors_exhausted(client, mock_api):
    mock_api.post("/tokenized/checkout/execute").side_effect = httpx.ConnectError("refused")
    with pytest.raises(BkashNetworkError):
        client.execute_payment("x")


def test_unknown_transaction_status_does_not_break_parsing(client, mock_api):
    mock_api.post("/tokenized/checkout/execute").respond(
        200, json={**EXECUTE_OK, "transactionStatus": "SomethingNew", "newField": 1}
    )
    executed = client.execute_payment("x")
    assert executed.transaction_status is TransactionStatus.UNKNOWN
    assert executed.model_extra["newField"] == 1


def test_malformed_success_payload_is_api_error(client, mock_api):
    mock_api.post("/tokenized/checkout/execute").respond(200, json={"statusCode": "0000"})
    with pytest.raises(BkashAPIError, match="did not match ExecutePaymentResponse"):
        client.execute_payment("x")


def test_custom_http_client_is_not_closed_by_sdk(config, mock_api, grant_route):
    from bkash import BkashClient

    http = httpx.Client(base_url="https://tokenized.sandbox.bka.sh/v1.2.0-beta")
    with BkashClient(config, http_client=http) as client:
        client.grant_token()
    assert not http.is_closed
    http.close()
