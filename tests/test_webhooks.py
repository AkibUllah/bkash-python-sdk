import json
from decimal import Decimal

import pytest

from bkash import BkashWebhookError, IPNNotification, IPNSubscriptionConfirmation, parse_ipn
from bkash.models import SearchTransactionResponse
from bkash.webhooks import verify_hmac_signature, verify_with_search
from tests.conftest import SEARCH_OK

MESSAGE = {
    "dateTime": "20261020140502",
    "debitMSISDN": "01711000000",
    "trxID": "9HK7A2B3C4",
    "transactionStatus": "Completed",
    "transactionType": "bKash Tokenized Checkout via API",
    "amount": "1500.00",
    "currency": "BDT",
    "transactionReference": "INV-2026-0001",
    "merchantInvoiceNumber": "INV-2026-0001",
    "receiverMSISDN": "01999000000",
}

SNS_ENVELOPE = {
    "Type": "Notification",
    "MessageId": "6f2c1c5e-5c1b-4a9c-9b1d-0d1a2b3c4d5e",
    "TopicArn": "arn:aws:sns:ap-southeast-1:000000000000:bkash-ipn",
    "Message": json.dumps(MESSAGE),
    "Timestamp": "2026-10-20T08:05:03.000Z",
}


def test_parse_sns_notification_envelope():
    ipn = parse_ipn(json.dumps(SNS_ENVELOPE).encode())
    assert isinstance(ipn, IPNNotification)
    assert ipn.trx_id == "9HK7A2B3C4"
    assert ipn.amount == Decimal("1500.00")
    assert ipn.is_completed
    assert ipn.message_id == SNS_ENVELOPE["MessageId"]
    assert ipn.debit_msisdn == "01711000000"


def test_parse_bare_transaction_json_and_dict():
    assert parse_ipn(json.dumps(MESSAGE)).trx_id == "9HK7A2B3C4"
    assert parse_ipn(MESSAGE).merchant_invoice_number == "INV-2026-0001"


def test_parse_subscription_confirmation():
    body = {
        "Type": "SubscriptionConfirmation",
        "TopicArn": "arn:aws:sns:ap-southeast-1:000000000000:bkash-ipn",
        "SubscribeURL": "https://sns.ap-southeast-1.amazonaws.com/?Action=ConfirmSubscription&Token=abc",
        "Token": "abc",
    }
    confirmation = parse_ipn(body)
    assert isinstance(confirmation, IPNSubscriptionConfirmation)
    assert confirmation.subscribe_url.startswith("https://sns.")


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[1,2,3]",
        json.dumps({"Type": "UnsubscribeConfirmation"}),
        json.dumps({"Type": "Notification", "Message": "garbage"}),
        json.dumps({"trxID": "X", "transactionStatus": "Completed", "amount": "abc"}),
        json.dumps({"transactionStatus": "Completed", "amount": "1"}),
    ],
)
def test_invalid_payloads_raise_webhook_error(body):
    with pytest.raises(BkashWebhookError):
        parse_ipn(body)


def test_matches_and_verify_with_search():
    ipn = parse_ipn(MESSAGE)
    assert ipn.matches(amount="1500", invoice_number="INV-2026-0001")
    assert not ipn.matches(amount="1499.99")
    assert not ipn.matches(amount="1500", invoice_number="INV-OTHER")

    search = SearchTransactionResponse.model_validate(SEARCH_OK)
    assert verify_with_search(ipn, search)
    tampered = search.model_copy(update={"amount": Decimal("1.00")})
    assert not verify_with_search(ipn, tampered)


def test_relay_hmac_signature():
    import hashlib
    import hmac

    body = json.dumps(MESSAGE).encode()
    sig = hmac.new(b"relay-secret", body, hashlib.sha256).hexdigest()
    assert verify_hmac_signature("relay-secret", body, sig)
    assert verify_hmac_signature("relay-secret", body, sig.upper())
    assert not verify_hmac_signature("relay-secret", body, "00")
    assert not verify_hmac_signature("relay-secret", body, None)
