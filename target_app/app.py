from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections import deque
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel, Field

from prahari.runtime import configure_runtime
from prahari.store import _redact
from target_app.state import read_state

logger = structlog.get_logger()
configure_runtime("prahari-target")
app = FastAPI(title="Prahari Checkout", version="0.1.0")

REQUESTS = Counter("checkout_requests_total", "Checkout HTTP requests", ["route", "status"])
LATENCY = Histogram("checkout_request_latency_seconds", "Checkout latency", ["route"])
ERRORS = Counter("checkout_errors_total", "Checkout failures", ["route"])
DB_CONNECTIONS = Gauge("checkout_db_connections", "Simulated active DB connections")
LOG_EVENTS: deque[dict[str, object]] = deque(maxlen=500)
REQUEST_SAMPLES: deque[tuple[float, int, float]] = deque(maxlen=10_000)
WINDOW_REQUESTS = Gauge("prahari_window_requests", "Requests observed in the configured SLO window")
WINDOW_ERRORS = Gauge("prahari_window_errors", "Failed requests observed in the configured SLO window")
WINDOW_P95 = Gauge("prahari_window_p95_latency_ms", "Request p95 latency in milliseconds for the configured SLO window")
SLO_WINDOW_SECONDS = max(1, int(os.getenv("PRAHARI_SLO_WINDOW_SECONDS", "300")))

PRODUCTS = [
    {"id": "coffee", "name": "Night Shift Coffee", "price": 299},
    {"id": "sticker", "name": "Prahari Sticker", "price": 99},
]


class CartItem(BaseModel):
    price: int = Field(ge=0)
    quantity: int = Field(default=1, ge=1)


class CheckoutRequest(BaseModel):
    items: list[CartItem]
    discount_code: str | None = None


def _refresh_window(now: float) -> None:
    samples = [sample for sample in REQUEST_SAMPLES if now - sample[0] <= SLO_WINDOW_SECONDS]
    REQUEST_SAMPLES.clear()
    REQUEST_SAMPLES.extend(samples)
    WINDOW_REQUESTS.set(len(samples))
    WINDOW_ERRORS.set(sum(status >= 400 for _, status, _ in samples))
    latencies = sorted(elapsed for _, _, elapsed in samples)
    p95_index = max(0, min(len(latencies) - 1, int(0.95 * len(latencies) + 0.999) - 1))
    WINDOW_P95.set(latencies[p95_index] * 1000 if latencies else 0)


def _record_window_sample(status_code: int, elapsed_seconds: float) -> None:
    REQUEST_SAMPLES.append((time.time(), status_code, elapsed_seconds))
    _refresh_window(time.time())


@app.middleware("http")
async def telemetry(request: Request, call_next: Any) -> JSONResponse:
    started = time.perf_counter()
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    try:
        response = await call_next(request)
    except Exception as error:  # noqa: BLE001
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        ERRORS.labels(request.url.path).inc()
        REQUESTS.labels(request.url.path, "500").inc()
        _record_window_sample(500, elapsed_ms / 1000)
        LOG_EVENTS.append({"request_id": request_id, "route": request.url.path, "status": 500, "error": str(_redact(str(error))), "time": time.time()})
        logger.error("request_failed", request_id=request_id, route=request.url.path, status=500,
                     latency_ms=elapsed_ms, error=str(_redact(str(error))), stack=type(error).__name__)
        return JSONResponse({"detail": "checkout failed", "request_id": request_id}, status_code=500)
    elapsed = time.perf_counter() - started
    LATENCY.labels(request.url.path).observe(elapsed)
    REQUESTS.labels(request.url.path, str(response.status_code)).inc()
    _record_window_sample(response.status_code, elapsed)
    if response.status_code >= 400:
        LOG_EVENTS.append({"request_id": request_id, "route": request.url.path, "status": response.status_code, "error": "http_error", "time": time.time()})
    logger.info("request_complete", request_id=request_id, route=request.url.path,
                status=response.status_code, latency_ms=round(elapsed * 1000, 2), error=None, stack=None)
    response.headers["x-request-id"] = request_id
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/products")
def products() -> list[dict[str, object]]:
    return PRODUCTS


@app.post("/cart")
def cart(items: list[dict[str, object]]) -> dict[str, object]:
    return {"items": items, "count": len(items)}


@app.post("/checkout")
async def checkout(payload: CheckoutRequest) -> dict[str, object]:
    scenario = read_state().get("scenario")
    DB_CONNECTIONS.set(1 if scenario == "config" else 3)
    if scenario == "bad_deploy" and payload.discount_code is None:
        raise ValueError("discount_code cannot be null")
    if scenario == "config":
        await asyncio.sleep(1.7)
    if scenario == "slow_query":
        await asyncio.sleep(1.7)
    if scenario == "dep_outage":
        raise HTTPException(status_code=503, detail="payment provider unavailable")
    total = sum(item.price * item.quantity for item in payload.items)
    return {"order_id": str(uuid.uuid4()), "status": "paid", "total": total}


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    _refresh_window(time.time())
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/debug/state")
def debug_state() -> dict[str, object]:
    return read_state()


@app.get("/debug/logs")
def debug_logs(limit: int = 100) -> list[dict[str, object]]:
    if os.getenv("PRAHARI_ENV", "development").lower() == "production":
        raise HTTPException(status_code=404, detail="Not found.")
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500.")
    return list(LOG_EVENTS)[-limit:]
