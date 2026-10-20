# Runs the FastAPI checkout example with the SDK installed from this source tree.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY pyproject.toml README.md CHANGELOG.md LICENSE ./
COPY src ./src
RUN pip install --upgrade pip && pip install ".[examples]" "python-multipart>=0.0.9"

COPY examples ./examples

RUN adduser --system --group app && chown -R app:app /srv
USER app

EXPOSE 8000
CMD ["uvicorn", "examples.fastapi_checkout.main:app", "--host", "0.0.0.0", "--port", "8000"]
