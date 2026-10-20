"""Typed exceptions. Everything derives from BkashError so callers can catch broadly."""

from __future__ import annotations

from typing import Any

# Status codes documented by bKash for the Tokenized Checkout API (subset most integrations meet).
KNOWN_STATUS_CODES: dict[str, str] = {
    "0000": "Successful",
    "2001": "Invalid App Key",
    "2002": "Invalid Payment ID",
    "2003": "Process failed",
    "2006": "Invalid Amount",
    "2007": "Invalid Currency",
    "2008": "Invalid Intent",
    "2011": "Invalid PIN",
    "2014": "Wrong PIN",
    "2015": "Wrong PIN count exceeded",
    "2017": "Wrong verification limit exceeded",
    "2023": "Insufficient Balance",
    "2025": "Invalid request body",
    "2026": "Reversal amount cannot be greater than original transaction amount",
    "2029": "Duplicate for all transactions",
    "2033": "Transaction not found",
    "2040": "Transaction expired",
    "2041": "Transaction already completed",
    "2056": "Invalid Payment State",
    "2062": "The payment has already been completed",
    "2117": "Payment is already executed",
    "9999": "System error",
}

AUTH_STATUS_CODES: frozenset[str] = frozenset({"2001"})


class BkashError(Exception):
    """Base class for all errors raised by this package."""


class BkashNetworkError(BkashError):
    """The request never produced an HTTP response (DNS, connection reset, TLS)."""


class BkashTimeoutError(BkashNetworkError):
    """The request timed out after exhausting retries."""


class BkashAPIError(BkashError):
    """bKash answered, but with an error (non-0000 statusCode or non-2xx HTTP status)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        error_code: str | None = None,
        response: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.error_code = error_code
        self.response = response or {}
        self.error_message = message
        super().__init__(f"[HTTP {status_code}] {error_code or '-'}: {message}")

    @property
    def description(self) -> str | None:
        """Human-readable meaning of `error_code` when it is a documented bKash code."""
        return KNOWN_STATUS_CODES.get(self.error_code or "")


class BkashAuthError(BkashAPIError):
    """Token grant/refresh failed, or bKash rejected the credentials/token."""


class BkashWebhookError(BkashError):
    """An IPN payload could not be parsed."""
