#!/usr/bin/env bash
# Codespaces start hook: run the FastAPI checkout example in the background.
# Real sandbox payments need the four credentials bKash issues per merchant; add them as
# Codespaces secrets (BKASH_APP_KEY, BKASH_APP_SECRET, BKASH_USERNAME, BKASH_PASSWORD) and
# they are picked up here. Without them the app still serves /, /docs and /health, and
# POST /checkout answers 502 from the sandbox instead of redirecting to bKash.
set -euo pipefail
cd "$(dirname "$0")/.."

export BKASH_APP_KEY="${BKASH_APP_KEY:-sandbox-placeholder-app-key}"
export BKASH_APP_SECRET="${BKASH_APP_SECRET:-sandbox-placeholder-app-secret}"
export BKASH_USERNAME="${BKASH_USERNAME:-sandbox-placeholder-username}"
export BKASH_PASSWORD="${BKASH_PASSWORD:-sandbox-placeholder-password}"
export BKASH_ENVIRONMENT="${BKASH_ENVIRONMENT:-sandbox}"
if [ -n "${CODESPACE_NAME:-}" ] && [ -n "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]; then
  export PUBLIC_BASE_URL="https://${CODESPACE_NAME}-8000.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"
fi

if ! curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
  nohup python -m uvicorn examples.fastapi_checkout.main:app --host 0.0.0.0 --port 8000 \
    > /tmp/checkout-example.log 2>&1 &
fi

cat <<MSG

bKash checkout example is starting (log: /tmp/checkout-example.log).
  Demo checkout:  forwarded port 8000, path /
  API docs:       forwarded port 8000, path /docs
  Credentials:    $([ "$BKASH_APP_KEY" = sandbox-placeholder-app-key ] && echo "placeholders (set BKASH_* Codespaces secrets for real sandbox payments)" || echo "from environment")
MSG
