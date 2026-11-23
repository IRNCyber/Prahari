"""Initialize opt-in error reporting and tracing for every application entrypoint."""

from __future__ import annotations

import os
from threading import Lock

_lock = Lock()
_configured = False


def configure_runtime(service_name: str) -> None:
    global _configured
    from prahari.settings import load_environment, validate_environment

    load_environment()
    validate_environment()
    with _lock:
        if _configured:
            return
        import sentry_sdk

        from otel.tracing import configure_tracing

        dsn = os.getenv("SENTRY_DSN", "").strip()
        if dsn:
            sentry_sdk.init(
                dsn=dsn,
                traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
                send_default_pii=False,
            )
        configure_tracing(service_name)
        _configured = True
