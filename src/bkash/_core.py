"""Transport-agnostic pieces shared by the sync and async clients."""

from __future__ import annotations

import logging
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from bkash.config import BkashConfig
from bkash.exceptions import AUTH_STATUS_CODES, BkashAPIError, BkashAuthError

logger = logging.getLogger("bkash")

M = TypeVar("M", bound=BaseModel)

GRANT_PATH = "/tokenized/checkout/token/grant"
REFRESH_PATH = "/tokenized/checkout/token/refresh"
CREATE_PATH = "/tokenized/checkout/create"
EXECUTE_PATH = "/tokenized/checkout/execute"
QUERY_PATH = "/tokenized/checkout/payment/status"
REFUND_PATH = "/tokenized/checkout/payment/refund"
SEARCH_PATH = "/tokenized/checkout/general/searchTransaction"


def build_timeout(config: BkashConfig) -> httpx.Timeout:
    return httpx.Timeout(config.timeout, connect=config.connect_timeout)


def base_headers(config: BkashConfig) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": config.user_agent,
    }


def token_headers(config: BkashConfig) -> dict[str, str]:
    """Grant/refresh authenticate with the portal username/password in headers."""
    return {**base_headers(config), "username": config.username, "password": config.password}


def api_headers(config: BkashConfig, id_token: str) -> dict[str, str]:
    """Every checkout call carries the id_token and the app key."""
    return {**base_headers(config), "Authorization": id_token, "X-App-Key": config.app_key}


def parse_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise BkashAPIError(
            f"non-JSON response: {response.text[:200]!r}", status_code=response.status_code
        ) from exc
    if not isinstance(data, dict):
        raise BkashAPIError("unexpected JSON shape", status_code=response.status_code)
    return data


def raise_for_error(
    response: httpx.Response, data: dict[str, Any], *, auth_call: bool = False
) -> None:
    """bKash signals most errors with HTTP 200 + statusCode != 0000; some with HTTP 4xx/5xx."""
    code = data.get("statusCode")
    message = str(
        data.get("statusMessage") or data.get("errorMessage") or data.get("message") or ""
    )
    code_str = str(code) if code is not None else None
    http_ok = 200 <= response.status_code < 300

    if http_ok and (code_str is None or code_str == "0000"):
        return

    error_cls: type[BkashAPIError] = BkashAPIError
    if auth_call or response.status_code in (401, 403) or (code_str in AUTH_STATUS_CODES):
        error_cls = BkashAuthError
    raise error_cls(
        message or (f"bKash status {code_str}" if code_str else f"HTTP {response.status_code}"),
        status_code=response.status_code,
        error_code=code_str,
        response=data,
    )


def parse_model(response: httpx.Response, model: type[M], *, auth_call: bool = False) -> M:
    data = parse_json(response)
    raise_for_error(response, data, auth_call=auth_call)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise BkashAPIError(
            f"response did not match {model.__name__}: {exc.errors()[0].get('msg', exc)}",
            status_code=response.status_code,
            error_code=str(data.get("statusCode")) if data.get("statusCode") else None,
            response=data,
        ) from exc


def is_unauthorized(response: httpx.Response) -> bool:
    """True when the id_token was rejected and a refresh + single retry is worth it."""
    if response.status_code == 401:
        return True
    if 200 <= response.status_code < 300:
        try:
            code = response.json().get("statusCode")
        except ValueError:
            return False
        return str(code) in AUTH_STATUS_CODES
    return False
