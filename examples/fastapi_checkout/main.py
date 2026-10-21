"""Minimal bKash checkout with FastAPI.

Flow: GET /checkout -> create payment -> redirect to bKash -> bKash returns to /bkash/callback
with ?paymentID&status -> execute -> show receipt. IPNs land on /bkash/ipn.

Run:  BKASH_APP_KEY=... BKASH_APP_SECRET=... BKASH_USERNAME=... BKASH_PASSWORD=... \
      uvicorn examples.fastapi_checkout.main:app --reload
"""

from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

import httpx
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from bkash import (
    AsyncBkashClient,
    BkashAPIError,
    BkashConfig,
    BkashError,
    BkashWebhookError,
    IPNSubscriptionConfirmation,
    parse_ipn,
)
from bkash.webhooks import verify_with_search

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("checkout-example")


def public_base_url(environ: dict[str, str] | None = None) -> str:
    """Base URL for callback/IPN URLs: PUBLIC_BASE_URL, else Render's RENDER_EXTERNAL_URL."""
    env = os.environ if environ is None else environ
    url = env.get("PUBLIC_BASE_URL") or env.get("RENDER_EXTERNAL_URL") or "http://localhost:8000"
    return url.rstrip("/")


PUBLIC_BASE_URL = public_base_url()

# In-memory order store; a real app persists orders and the paymentID -> order mapping.
ORDERS: dict[str, dict[str, Any]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.bkash = AsyncBkashClient(BkashConfig.from_env())
    yield
    await app.state.bkash.aclose()


app = FastAPI(title="bKash checkout example", lifespan=lifespan)


def _client(request: Request) -> AsyncBkashClient:
    return request.app.state.bkash


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return """
    <h1>Dhaka Mart - demo checkout</h1>
    <form method="post" action="/checkout">
      <label>Amount (BDT) <input name="amount" value="1500.00"></label><br>
      <label>Your bKash number <input name="msisdn" value="01711000000"></label><br>
      <button type="submit">Pay with bKash</button>
    </form>
    """


@app.post("/checkout")
async def checkout(request: Request, amount: str = Form(...), msisdn: str = Form(...)):
    invoice = f"INV-{secrets.token_hex(4).upper()}"
    try:
        created = await _client(request).create_payment(
            amount=Decimal(amount),
            payer_reference=msisdn,
            callback_url=f"{PUBLIC_BASE_URL}/bkash/callback",
            merchant_invoice_number=invoice,
        )
    except BkashError as exc:
        log.exception("create failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    ORDERS[created.payment_id] = {
        "invoice": invoice,
        "amount": str(created.amount),
        "status": "created",
    }
    if not created.bkash_url:
        raise HTTPException(status_code=502, detail="bKash did not return a checkout URL")
    return RedirectResponse(created.bkash_url, status_code=303)


@app.get("/bkash/callback", response_class=HTMLResponse)
async def callback(request: Request, paymentID: str, status: str):
    order = ORDERS.get(paymentID)
    if order is None:
        raise HTTPException(status_code=404, detail="unknown payment")
    if status != "success":
        order["status"] = status  # "failure" or "cancel"
        return (
            f"<h1>Payment {status}</h1><p>Invoice {order['invoice']}</p><a href='/'>Try again</a>"
        )

    client = _client(request)
    try:
        executed = await client.execute_payment(paymentID)
    except BkashAPIError as exc:
        # 2062/2117: already executed (e.g. duplicate callback). Confirm via query instead.
        if exc.error_code in {"2062", "2117"}:
            queried = await client.query_payment(paymentID)
            if queried.is_completed:
                order.update(status="paid", trx_id=queried.trx_id)
                return _receipt(order)
        order["status"] = "failed"
        return f"<h1>Payment failed</h1><p>{exc.error_code}: {exc.error_message}</p>"

    if executed.is_completed:
        order.update(status="paid", trx_id=executed.trx_id)
        return _receipt(order)
    order["status"] = executed.transaction_status.value
    return f"<h1>Payment {executed.transaction_status.value}</h1>"


def _receipt(order: dict[str, Any]) -> str:
    return (
        f"<h1>Payment received</h1><p>Invoice {order['invoice']}<br>"
        f"Amount ৳{order['amount']}<br>bKash TrxID {order.get('trx_id')}</p>"
    )


@app.post("/bkash/ipn")
async def ipn(request: Request):
    try:
        message = parse_ipn(await request.body())
    except BkashWebhookError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    if isinstance(message, IPNSubscriptionConfirmation):
        async with httpx.AsyncClient(timeout=10) as http:
            await http.get(message.subscribe_url)
        log.info("confirmed IPN subscription for %s", message.topic_arn)
        return {"subscribed": True}

    txn = await _client(request).search_transaction(message.trx_id)
    verified = verify_with_search(message, txn)
    for order in ORDERS.values():
        if order["invoice"] == message.merchant_invoice_number and verified:
            order.update(status="paid", trx_id=message.trx_id)
    log.info(
        "IPN trx=%s status=%s verified=%s", message.trx_id, message.transaction_status, verified
    )
    return {"received": True, "verified": verified}


@app.get("/orders")
async def orders() -> dict[str, Any]:
    return ORDERS


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
