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
