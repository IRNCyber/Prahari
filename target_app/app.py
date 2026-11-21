from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from target_app.state import read_state

logger = structlog.get_logger()
app = FastAPI(title="Prahari Checkout", version="0.1.0")

REQUESTS = Counter("checkout_requests_total", "Checkout HTTP requests", ["route", "status"])
LATENCY = Histogram("checkout_request_latency_seconds", "Checkout latency", ["route"])
ERRORS = Counter("checkout_errors_total", "Checkout failures", ["route"])
DB_CONNECTIONS = Gauge("checkout_db_connections", "Simulated active DB connections")

PRODUCTS = [
    {"id": "coffee", "name": "Night Shift Coffee", "price": 299},
    {"id": "sticker", "name": "Prahari Sticker", "price": 99},
]


@app.middleware("http")
async def telemetry(request: Request, call_next: Any) -> JSONResponse:
    started = time.perf_counter()
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    try:
        response = await call_next(request)
    except Exception as error:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        ERRORS.labels(request.url.path).inc()
        REQUESTS.labels(request.url.path, "500").inc()
        logger.error("request_failed", request_id=request_id, route=request.url.path, status=500,
                     latency_ms=elapsed_ms, error=str(error), stack=type(error).__name__)
        return JSONResponse({"detail": "checkout failed", "request_id": request_id}, status_code=500)
    elapsed = time.perf_counter() - started
    LATENCY.labels(request.url.path).observe(elapsed)
    REQUESTS.labels(request.url.path, str(response.status_code)).inc()
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
async def checkout(payload: dict[str, object]) -> dict[str, object]:
    scenario = read_state().get("scenario")
    DB_CONNECTIONS.set(1 if scenario == "config" else 3)
    if scenario == "bad_deploy" and payload.get("discount_code") is None:
        raise ValueError("discount_code cannot be null")
    if scenario == "config":
        await asyncio.sleep(1.7)
    if scenario == "slow_query":
        await asyncio.sleep(1.7)
    if scenario == "dep_outage":
        raise HTTPException(status_code=503, detail="payment provider unavailable")
    total = sum(int(item.get("price", 0)) * int(item.get("quantity", 1)) for item in payload.get("items", []))
    return {"order_id": str(uuid.uuid4()), "status": "paid", "total": total}


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/debug/state")
def debug_state() -> dict[str, object]:
    return read_state()
