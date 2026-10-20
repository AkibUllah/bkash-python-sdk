import httpx
import pytest
import respx

from bkash import BkashAuthError, BkashClient
from tests.conftest import CREATE_OK, TOKEN_OK


def _create(client):
    return client.create_payment(
        amount="1500.00",
        payer_reference="01711000000",
        callback_url="https://shop.example/bkash/callback",
        merchant_invoice_number="INV-2026-0001",
    )


def test_grant_sends_credentials_in_headers_and_app_keys_in_body(client, mock_api, grant_route):
    mock_api.post("/tokenized/checkout/create").respond(200, json=CREATE_OK)
    _create(client)

    assert grant_route.called
    request = grant_route.calls.last.request
    assert request.headers["username"] == "sandbox_user"
    assert request.headers["password"] == "sandbox_pass"
    import json

    assert json.loads(request.content) == {
        "app_key": "app_key_sandbox",
        "app_secret": "app_secret_sandbox",
    }


def test_token_is_cached_across_calls(client, mock_api, grant_route):
    create = mock_api.post("/tokenized/checkout/create").respond(200, json=CREATE_OK)
    _create(client)
    _create(client)
    assert grant_route.call_count == 1
    assert create.call_count == 2
    assert create.calls.last.request.headers["Authorization"] == "tok_first"
    assert create.calls.last.request.headers["X-App-Key"] == "app_key_sandbox"


def test_grant_failure_raises_auth_error(config, mock_api):
    mock_api.post("/tokenized/checkout/token/grant").respond(
        200, json={"statusCode": "2001", "statusMessage": "Invalid App Key"}
    )
    with BkashClient(config) as client, pytest.raises(BkashAuthError) as exc_info:
        _create(client)
    assert exc_info.value.error_code == "2001"
    assert exc_info.value.description == "Invalid App Key"
    assert exc_info.value.status_code == 200


def test_http_401_on_grant_is_auth_error(config, mock_api):
    mock_api.post("/tokenized/checkout/token/grant").respond(401, json={"message": "Unauthorized"})
    with BkashClient(config) as client, pytest.raises(BkashAuthError, match="Unauthorized"):
        client.grant_token()


def test_expired_token_is_refreshed_then_falls_back_to_grant(config, mock_api):
    now = [1000.0]
    grant = mock_api.post("/tokenized/checkout/token/grant").respond(200, json=TOKEN_OK)
    refresh = mock_api.post("/tokenized/checkout/token/refresh")
    refresh.side_effect = [
        httpx.Response(
            200, json={**TOKEN_OK, "id_token": "tok_refreshed", "refresh_token": "ref_2"}
        ),
        httpx.Response(200, json={"statusCode": "2001", "statusMessage": "Invalid App Key"}),
    ]
    create = mock_api.post("/tokenized/checkout/create").respond(200, json=CREATE_OK)

    with BkashClient(config, clock=lambda: now[0]) as client:
        _create(client)
        assert create.calls.last.request.headers["Authorization"] == "tok_first"

        now[0] += 3600 - 30  # inside the 60s refresh margin -> stale
        _create(client)
        assert refresh.call_count == 1
        assert create.calls.last.request.headers["Authorization"] == "tok_refreshed"
        import json

        assert json.loads(refresh.calls.last.request.content)["refresh_token"] == "ref_first"

        now[0] += 3600  # stale again; refresh now rejected -> grant again
        _create(client)
        assert refresh.call_count == 2
        assert grant.call_count == 2


def test_rejected_token_triggers_single_forced_refresh(client, mock_api, grant_route):
    create = mock_api.post("/tokenized/checkout/create")
    create.side_effect = [
        httpx.Response(401, json={"message": "token expired"}),
        httpx.Response(200, json=CREATE_OK),
    ]
    payment = _create(client)
    assert payment.payment_id == "TR0011abc123"
    assert grant_route.call_count == 2
    assert create.call_count == 2


def test_persistent_401_surfaces_auth_error(client, mock_api):
    mock_api.post("/tokenized/checkout/create").respond(401, json={"message": "nope"})
    with pytest.raises(BkashAuthError):
        _create(client)


@respx.mock(base_url="https://tokenized.pay.bka.sh/v1.2.0-beta")
def test_production_environment_uses_live_base_url(respx_mock):
    from bkash import BkashConfig

    grant = respx_mock.post("/tokenized/checkout/token/grant").respond(200, json=TOKEN_OK)
    cfg = BkashConfig.production("k", "s", "u", "p")
    with BkashClient(cfg) as client:
        assert client.grant_token() == "tok_first"
    assert grant.called
