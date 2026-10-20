"""IPN (Instant Payment Notification) helpers.

bKash delivers IPNs through Amazon SNS. Your IPN endpoint therefore receives two kinds of
POST bodies:

1. `SubscriptionConfirmation` - once, when bKash registers your URL. You must GET the
   `SubscribeURL` to activate the subscription.
2. `Notification` - for each transaction. The transaction payload is a JSON string inside
   the SNS `Message` field.

The payload is not HMAC-signed by bKash, so treat it as a hint: `parse_ipn` gives you typed
data, and `verify_with_search` confirms the transaction against the API before you fulfil
an order. Some merchants front the IPN URL with a relay that adds its own HMAC header;
`verify_hmac_signature` covers that.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from bkash.exceptions import BkashAPIError, BkashWebhookError
from bkash.models import SearchTransactionResponse, TransactionStatus


class IPNSubscriptionConfirmation(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    type: str = Field(alias="Type")
    topic_arn: str | None = Field(default=None, alias="TopicArn")
    subscribe_url: str = Field(alias="SubscribeURL")
    token: str | None = Field(default=None, alias="Token")


class IPNNotification(BaseModel):
    """The transaction fields bKash puts in the SNS message."""

    model_config = ConfigDict(populate_by_name=True, extra="allow", str_strip_whitespace=True)

    trx_id: str = Field(alias="trxID")
    transaction_status: TransactionStatus = Field(alias="transactionStatus")
    amount: Decimal
    currency: str = "BDT"
    date_time: str | None = Field(default=None, alias="dateTime")
    debit_msisdn: str | None = Field(default=None, alias="debitMSISDN")
    receiver_msisdn: str | None = Field(default=None, alias="receiverMSISDN")
    transaction_type: str | None = Field(default=None, alias="transactionType")
    transaction_reference: str | None = Field(default=None, alias="transactionReference")
    merchant_invoice_number: str | None = Field(default=None, alias="merchantInvoiceNumber")
    payment_id: str | None = Field(default=None, alias="paymentID")
    message_id: str | None = None
    topic_arn: str | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, value: Any) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"invalid amount {value!r}") from exc

    @property
    def is_completed(self) -> bool:
        return self.transaction_status is TransactionStatus.COMPLETED

    def matches(self, *, amount: Decimal | str | int, invoice_number: str | None = None) -> bool:
        """Cheap local check before hitting the API: amount (and invoice, if known) agree."""
        if Decimal(str(amount)).quantize(Decimal("0.01")) != self.amount.quantize(Decimal("0.01")):
            return False
        if invoice_number is not None and self.merchant_invoice_number not in (
            None,
            invoice_number,
        ):
            return False
        return True


def _load(body: bytes | str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(body, dict):
        return body
    try:
        text = body.decode("utf-8") if isinstance(body, bytes) else body
        data = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BkashWebhookError(f"IPN body is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise BkashWebhookError("IPN body must be a JSON object")
    return data


def parse_ipn(
    body: bytes | str | dict[str, Any],
) -> IPNNotification | IPNSubscriptionConfirmation:
    """Parse an SNS envelope (or a bare transaction JSON) into a typed object.

    Raises BkashWebhookError on anything that cannot be understood.
    """
    data = _load(body)
    sns_type = data.get("Type")
    try:
        if sns_type == "SubscriptionConfirmation" or (sns_type is None and "SubscribeURL" in data):
            return IPNSubscriptionConfirmation.model_validate(data)
        if sns_type == "Notification":
            message = data.get("Message")
            payload = _load(message) if isinstance(message, str | bytes) else message
            if not isinstance(payload, dict):
                raise BkashWebhookError("SNS Message does not contain a JSON object")
            notification = IPNNotification.model_validate(payload)
            notification.message_id = data.get("MessageId")
            notification.topic_arn = data.get("TopicArn")
            return notification
        if sns_type is None:
            return IPNNotification.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise BkashWebhookError(
            f"IPN payload invalid at {'.'.join(str(p) for p in first['loc'])}: {first['msg']}"
        ) from exc
    raise BkashWebhookError(f"unsupported SNS message type {sns_type!r}")


def verify_hmac_signature(secret: str, body: bytes, signature: str | None) -> bool:
    """Constant-time check of a hex HMAC-SHA256 added by an upstream relay/proxy."""
    if not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def verify_with_search(
    notification: IPNNotification,
    search: SearchTransactionResponse,
) -> bool:
    """Confirm an IPN against the result of `client.search_transaction(notification.trx_id)`."""
    return (
        search.trx_id == notification.trx_id
        and search.transaction_status is TransactionStatus.COMPLETED
        and search.amount.quantize(Decimal("0.01")) == notification.amount.quantize(Decimal("0.01"))
    )


__all__ = [
    "BkashAPIError",
    "IPNNotification",
    "IPNSubscriptionConfirmation",
    "parse_ipn",
    "verify_hmac_signature",
    "verify_with_search",
]
