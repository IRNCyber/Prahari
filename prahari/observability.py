"""OpenTelemetry configuration discovery without exporting data implicitly."""

from __future__ import annotations

import os


def otel_status() -> dict[str, object]:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    return {"configured": endpoint.startswith(("http://", "https://")), "endpoint": endpoint.split("//", 1)[0] + "//configured" if endpoint else None}
