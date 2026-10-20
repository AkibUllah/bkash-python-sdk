# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-21

### Added
- `BkashClient` and `AsyncBkashClient` for the Tokenized Checkout API: create, execute,
  query, refund and search transaction.
- Token management with caching, early refresh, refresh-token use and grant fallback.
- `RetryPolicy` with exponential backoff and jitter for 5xx, timeouts and connection errors.
- Pydantic v2 request/response models with wire-name aliases and `Decimal` amounts.
- Typed exception hierarchy (`BkashAuthError`, `BkashAPIError`, `BkashTimeoutError`,
  `BkashNetworkError`, `BkashWebhookError`) with documented bKash status codes.
- IPN helpers: `parse_ipn`, `verify_with_search`, `verify_hmac_signature`.
- FastAPI checkout example under `examples/fastapi_checkout`.
- `py.typed` marker; passes `mypy --strict`.

[Unreleased]: https://github.com/AkibUllah/bkash-python-sdk/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/AkibUllah/bkash-python-sdk/releases/tag/v0.1.0
