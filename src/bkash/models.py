"""Pydantic v2 models for bKash requests and responses.

bKash uses camelCase with a few all-caps acronyms (paymentID, trxID, bkashURL). Every model
accepts the wire names and exposes snake_case attributes; `extra="allow"` keeps undocumented
fields reachable through `model_extra` instead of failing on new API fields.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


class TransactionStatus(str, Enum):
    INITIATED = "Initiated"
    COMPLETED = "Completed"
    FAILED = "Failed"
    CANCELLED = "Cancelled"
    PENDING = "Pending"
    REFUNDED = "Refunded"
    PARTIAL_REFUNDED = "Partial Refunded"
    EXPIRED = "Expired"
    UNKNOWN = "Unknown"

    @classmethod
    def _missing_(cls, value: object) -> TransactionStatus:
        return cls.UNKNOWN


def _validate_amount(value: Decimal | str | int) -> Decimal:
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"invalid amount {value!r}") from exc
    if amount <= 0:
        raise ValueError("amount must be positive")
    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("amount may have at most two decimal places")
    return amount.quantize(Decimal("0.01"))


class _Wire(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow", str_strip_whitespace=True)


class _ApiResponse(_Wire):
    status_code: str | None = Field(default=None, alias="statusCode")
    status_message: str | None = Field(default=None, alias="statusMessage")

    @property
    def ok(self) -> bool:
        return self.status_code in (None, "0000")


# -- auth -------------------------------------------------------------------------
class TokenResponse(_ApiResponse):
    id_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600
    refresh_token: str | None = None


# -- create ------------------------------------------------------------------------
class CreatePaymentRequest(_Wire):
    """Body for /tokenized/checkout/create. `mode` 0011 is the standard checkout (URL) flow."""

    mode: Literal["0011", "0001", "0000"] = "0011"
    payer_reference: str = Field(alias="payerReference", min_length=1, max_length=255)
    callback_url: str = Field(alias="callbackURL", min_length=1)
    amount: Decimal
    currency: Literal["BDT"] = "BDT"
    intent: Literal["sale", "authorization"] = "sale"
    merchant_invoice_number: str = Field(
        alias="merchantInvoiceNumber", min_length=1, max_length=255
    )
    agreement_id: str | None = Field(default=None, alias="agreementID")
    merchant_association_info: str | None = Field(default=None, alias="merchantAssociationInfo")

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, value: Decimal | str | int) -> Decimal:
        return _validate_amount(value)

    @field_serializer("amount")
    def _serialize_amount(self, value: Decimal) -> str:
        return f"{value:.2f}"

    def to_wire(self) -> dict[str, object]:
        return self.model_dump(by_alias=True, exclude_none=True)


class CreatePaymentResponse(_ApiResponse):
    payment_id: str = Field(alias="paymentID")
    bkash_url: str | None = Field(default=None, alias="bkashURL")
    callback_url: str | None = Field(default=None, alias="callbackURL")
    success_callback_url: str | None = Field(default=None, alias="successCallbackURL")
    failure_callback_url: str | None = Field(default=None, alias="failureCallbackURL")
    cancelled_callback_url: str | None = Field(default=None, alias="cancelledCallbackURL")
    amount: Decimal
    intent: str = "sale"
    currency: str = "BDT"
    payment_create_time: str | None = Field(default=None, alias="paymentCreateTime")
    transaction_status: TransactionStatus = Field(alias="transactionStatus")
    merchant_invoice_number: str | None = Field(default=None, alias="merchantInvoiceNumber")
    agreement_id: str | None = Field(default=None, alias="agreementID")


# -- execute -----------------------------------------------------------------------
class ExecutePaymentResponse(_ApiResponse):
    payment_id: str = Field(alias="paymentID")
    trx_id: str | None = Field(default=None, alias="trxID")
    transaction_status: TransactionStatus = Field(alias="transactionStatus")
    amount: Decimal
    currency: str = "BDT"
    intent: str = "sale"
    payment_execute_time: str | None = Field(default=None, alias="paymentExecuteTime")
    merchant_invoice_number: str | None = Field(default=None, alias="merchantInvoiceNumber")
    payer_reference: str | None = Field(default=None, alias="payerReference")
    customer_msisdn: str | None = Field(default=None, alias="customerMsisdn")
    agreement_id: str | None = Field(default=None, alias="agreementID")

    @property
    def is_completed(self) -> bool:
        return self.transaction_status is TransactionStatus.COMPLETED and bool(self.trx_id)


# -- query -------------------------------------------------------------------------
class QueryPaymentResponse(_ApiResponse):
    payment_id: str = Field(alias="paymentID")
    mode: str | None = None
    payment_create_time: str | None = Field(default=None, alias="paymentCreateTime")
    payment_execute_time: str | None = Field(default=None, alias="paymentExecuteTime")
    amount: Decimal
    currency: str = "BDT"
    intent: str = "sale"
    merchant_invoice: str | None = Field(default=None, alias="merchantInvoice")
    transaction_status: TransactionStatus = Field(alias="transactionStatus")
    verification_status: str | None = Field(default=None, alias="verificationStatus")
    user_verification_status: str | None = Field(default=None, alias="userVerificationStatus")
    payer_reference: str | None = Field(default=None, alias="payerReference")
    trx_id: str | None = Field(default=None, alias="trxID")

    @property
    def is_completed(self) -> bool:
        return self.transaction_status is TransactionStatus.COMPLETED


# -- refund ------------------------------------------------------------------------
class RefundRequest(_Wire):
    payment_id: str = Field(alias="paymentID", min_length=1)
    trx_id: str = Field(alias="trxID", min_length=1)
    amount: Decimal
    sku: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=255)

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, value: Decimal | str | int) -> Decimal:
        return _validate_amount(value)

    @field_serializer("amount")
    def _serialize_amount(self, value: Decimal) -> str:
        return f"{value:.2f}"

    def to_wire(self) -> dict[str, object]:
        return self.model_dump(by_alias=True)


class RefundResponse(_ApiResponse):
    completed_time: str | None = Field(default=None, alias="completedTime")
    transaction_status: TransactionStatus = Field(alias="transactionStatus")
    original_trx_id: str | None = Field(default=None, alias="originalTrxID")
    refund_trx_id: str | None = Field(default=None, alias="refundTrxID")
    amount: Decimal
    currency: str = "BDT"
    charge: Decimal | None = None


# -- search ------------------------------------------------------------------------
class SearchTransactionResponse(_ApiResponse):
    trx_id: str = Field(alias="trxID")
    transaction_status: TransactionStatus = Field(alias="transactionStatus")
    transaction_type: str | None = Field(default=None, alias="transactionType")
    amount: Decimal
    currency: str = "BDT"
    customer_msisdn: str | None = Field(default=None, alias="customerMsisdn")
    organization_short_code: str | None = Field(default=None, alias="organizationShortCode")
    initiation_time: str | None = Field(default=None, alias="initiationTime")
    completed_time: str | None = Field(default=None, alias="completedTime")
    transaction_reference: str | None = Field(default=None, alias="transactionReference")
