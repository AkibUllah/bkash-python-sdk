from decimal import Decimal

import pytest
from pydantic import ValidationError

from bkash import BkashConfig, CreatePaymentRequest, RefundRequest, RetryPolicy


def test_create_request_requires_two_decimal_positive_amount():
    ok = CreatePaymentRequest(
        amount="99.5", payer_reference="p", callback_url="https://x", merchant_invoice_number="1"
    )
    assert ok.amount == Decimal("99.50")
    assert ok.to_wire()["amount"] == "99.50"

    for bad in ("0", "-1", "1.005", "abc"):
        with pytest.raises((ValidationError, ValueError)):
            CreatePaymentRequest(
                amount=bad,
                payer_reference="p",
                callback_url="https://x",
                merchant_invoice_number="1",
            )


def test_create_request_accepts_wire_names_too():
    req = CreatePaymentRequest.model_validate(
        {
            "amount": "10",
            "payerReference": "01711000000",
            "callbackURL": "https://x",
            "merchantInvoiceNumber": "INV-1",
            "agreementID": "AG-1",
        }
    )
    assert req.payer_reference == "01711000000"
    assert req.to_wire()["agreementID"] == "AG-1"


def test_refund_request_wire_format():
    req = RefundRequest(payment_id="P", trx_id="T", amount=250, sku="SKU", reason="dup")
    assert req.to_wire() == {
        "paymentID": "P",
        "trxID": "T",
        "amount": "250.00",
        "sku": "SKU",
        "reason": "dup",
    }


def test_retry_policy_backoff_schedule_is_exponential_and_capped():
    policy = RetryPolicy(max_attempts=5, base_delay=0.5, max_delay=3.0, jitter=False)
    assert [policy.delay_for(a) for a in range(1, 5)] == [0.5, 1.0, 2.0, 3.0]
    assert policy.can_retry(4) and not policy.can_retry(5)


def test_retry_policy_jitter_scales_within_cap():
    policy = RetryPolicy(base_delay=1.0, max_delay=4.0, jitter=True, rng=lambda: 0.25)
    assert policy.delay_for(1) == 0.25
    assert policy.delay_for(3) == 1.0
    assert RetryPolicy.none().max_attempts == 1
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)


def test_config_validation_and_env_loading(monkeypatch):
    with pytest.raises(ValueError, match="app_key"):
        BkashConfig("", "s", "u", "p")
    with pytest.raises(ValueError, match="timeouts"):
        BkashConfig("k", "s", "u", "p", timeout=0)

    monkeypatch.delenv("BKASH_APP_KEY", raising=False)
    with pytest.raises(ValueError, match="BKASH_APP_KEY"):
        BkashConfig.from_env()

    monkeypatch.setenv("BKASH_APP_KEY", "k")
    monkeypatch.setenv("BKASH_APP_SECRET", "s")
    monkeypatch.setenv("BKASH_USERNAME", "u")
    monkeypatch.setenv("BKASH_PASSWORD", "p")
    monkeypatch.setenv("BKASH_ENVIRONMENT", "production")
    cfg = BkashConfig.from_env()
    assert cfg.resolved_base_url == "https://tokenized.pay.bka.sh/v1.2.0-beta"
    override = BkashConfig("k", "s", "u", "p", base_url="http://localhost:9000/")
    assert override.resolved_base_url == "http://localhost:9000"
