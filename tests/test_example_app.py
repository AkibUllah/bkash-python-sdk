from __future__ import annotations

from examples.fastapi_checkout.main import app, public_base_url


def test_public_base_url_prefers_explicit_value_then_render_then_localhost() -> None:
    assert public_base_url({"PUBLIC_BASE_URL": "https://shop.example/"}) == "https://shop.example"
    assert (
        public_base_url({"RENDER_EXTERNAL_URL": "https://bkash-demo.onrender.com"})
        == "https://bkash-demo.onrender.com"
    )
    assert (
        public_base_url(
            {"PUBLIC_BASE_URL": "https://shop.example", "RENDER_EXTERNAL_URL": "https://x.y"}
        )
        == "https://shop.example"
    )
    assert public_base_url({}) == "http://localhost:8000"


def test_example_app_openapi_is_exportable_without_credentials() -> None:
    spec = app.openapi()
    assert spec["info"]["title"] == "bKash checkout example"
    assert {"/checkout", "/bkash/callback", "/bkash/ipn", "/health"} <= set(spec["paths"])


def _sandbox_env(monkeypatch) -> None:
    for name in ("BKASH_APP_KEY", "BKASH_APP_SECRET", "BKASH_USERNAME", "BKASH_PASSWORD"):
        monkeypatch.setenv(name, "test-value")


def test_callback_does_not_reflect_untrusted_input(monkeypatch) -> None:
    from examples.fastapi_checkout.main import ORDERS
    from fastapi.testclient import TestClient

    _sandbox_env(monkeypatch)
    ORDERS["TR0011xss"] = {"invoice": "<b>INV-1</b>", "amount": "100.00", "status": "created"}
    try:
        with TestClient(app) as client:
            response = client.get(
                "/bkash/callback", params={"paymentID": "TR0011xss", "status": "<script>x</script>"}
            )
        assert response.status_code == 200
        assert "<script>" not in response.text
        assert "&lt;b&gt;INV-1&lt;/b&gt;" in response.text
        assert ORDERS["TR0011xss"]["status"] == "failure"
    finally:
        ORDERS.pop("TR0011xss", None)


def test_ipn_rejection_does_not_echo_parser_errors(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    _sandbox_env(monkeypatch)
    with TestClient(app) as client:
        response = client.post("/bkash/ipn", content=b"not json")
    assert response.status_code == 400
    assert response.json() == {"error": "invalid IPN message"}
