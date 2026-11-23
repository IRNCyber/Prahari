"""HTTP detector API and periodic polling worker."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import httpx
import structlog
from fastapi import FastAPI, HTTPException

from agent.loop import run as investigate
from detector.alert import detect
from otel.tracing import traced
from prahari.runtime import configure_runtime
from prahari.store import audit, recent_alerts, record_alert, resolve_alert

TARGET_URL = os.getenv("TARGET_BASE_URL", "http://target_app:8000")
POLL_INTERVAL = max(1, int(os.getenv("DETECTOR_POLL_INTERVAL", "10")))
_poll_task: asyncio.Task[None] | None = None
logger = structlog.get_logger()
configure_runtime("prahari-detector")


@traced("detector.poll")
async def poll_once() -> dict[str, object]:
    try:
        alert = await asyncio.to_thread(detect, TARGET_URL)
    except (httpx.HTTPError, ValueError) as error:
        audit("detector_error", {"error": type(error).__name__, "message": str(error)[:300]}, actor="detector")
        raise HTTPException(status_code=502, detail="Unable to query target telemetry.") from error
    if alert is None:
        for prior in recent_alerts():
            fingerprint = str(prior["fingerprint"])
            if (
                prior["status"] == "firing"
                and fingerprint.endswith(":checkout")
                and resolve_alert(fingerprint)
            ):
                audit("alert_resolved", {"fingerprint": fingerprint}, actor="detector")
        return {"alert": None, "triggered": False}
    stored, should_investigate = record_alert(
        fingerprint=f"{alert.type}:{alert.service}",
        severity="high",
        summary=f"{alert.type} on {alert.service}",
        evidence=alert.evidence,
        suppression_seconds=int(os.getenv("ALERT_SUPPRESSION_SECONDS", "300")),
    )
    if should_investigate:
        audit("alert_fired", stored, actor="detector")
        result = await asyncio.to_thread(investigate, alert.to_dict())
    else:
        result = None
    return {"alert": stored, "triggered": should_investigate, "investigation": result}


async def _poll_forever() -> None:
    failure_count = 0
    while True:
        try:
            await poll_once()
        except Exception as error:
            failure_count += 1
            retry_delay = min(POLL_INTERVAL * 2 ** min(failure_count - 1, 5), 300)
            logger.exception(
                "detector_poll_failed",
                error_type=type(error).__name__,
                retry_in_seconds=retry_delay,
            )
            await asyncio.sleep(retry_delay)
            continue
        failure_count = 0
        await asyncio.sleep(POLL_INTERVAL)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global _poll_task
    if os.getenv("DETECTOR_AUTOSTART", "true").lower() == "true":
        _poll_task = asyncio.create_task(_poll_forever())
    try:
        yield
    finally:
        if _poll_task is not None:
            _poll_task.cancel()
            with suppress(asyncio.CancelledError):
                await _poll_task


app = FastAPI(title="Prahari Detector", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "poll_interval_seconds": POLL_INTERVAL}


@app.post("/detect")
async def detect_now() -> dict[str, object]:
    return await poll_once()
