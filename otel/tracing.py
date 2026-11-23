"""Initialize OTLP tracing only when an exporter endpoint is configured."""

from __future__ import annotations

import os
from collections.abc import Callable
from functools import wraps
from threading import Lock
from typing import ParamSpec, TypeVar

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

_lock = Lock()
_initialized = False
P = ParamSpec("P")
R = TypeVar("R")


def configure_tracing(service_name: str) -> None:
    global _initialized
    with _lock:
        if _initialized:
            return
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
        if endpoint.startswith(("http://", "https://")):
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            provider = TracerProvider(
                resource=Resource.create({SERVICE_NAME: service_name}),
            )
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")))
            trace.set_tracer_provider(provider)
        _initialized = True


def get_tracer(name: str):
    return trace.get_tracer(name)


def traced(span_name: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            with get_tracer("prahari").start_as_current_span(span_name) as span:
                try:
                    return function(*args, **kwargs)
                except Exception as error:
                    span.record_exception(error)
                    span.set_status(Status(StatusCode.ERROR))
                    raise

        return wrapped

    return decorate
